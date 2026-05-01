from __future__ import annotations

from typing import Any

import httpx

from .settings import RepoConfig, Settings


class HermesClient:
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.hermes_base_url.rstrip("/")
        self.model = settings.hermes_model
        self.timeout = settings.hermes_timeout_seconds

    async def health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{self.base_url}/health")
            response.raise_for_status()
            return response.json()

    async def chat(self, system_prompt: str, history: list[dict[str, str]], user_content: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                *history,
                {"role": "user", "content": user_content},
            ],
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/v1/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
        try:
            return str(data["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"unexpected Hermes response: {data!r}") from exc


class NapCatClient:
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.napcat_base_url.rstrip("/")
        self.access_token = settings.napcat_access_token

    async def health(self) -> dict[str, Any]:
        return await self.call("get_status", {})

    async def send_msg(
        self,
        *,
        message_type: str,
        message: str | list[dict[str, Any]],
        user_id: str | None = None,
        group_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "message_type": message_type,
            "message": message,
            "auto_escape": isinstance(message, str),
        }
        if user_id:
            payload["user_id"] = int(user_id)
        if group_id:
            payload["group_id"] = int(group_id)
        return await self.call("send_msg", payload)

    async def delete_msg(self, message_id: str) -> dict[str, Any]:
        return await self.call("delete_msg", {"message_id": int(message_id)})

    async def set_group_card(self, group_id: str, user_id: str, card: str) -> dict[str, Any]:
        return await self.call("set_group_card", {"group_id": int(group_id), "user_id": int(user_id), "card": card})

    async def set_group_ban(self, group_id: str, user_id: str, duration: int) -> dict[str, Any]:
        return await self.call(
            "set_group_ban",
            {"group_id": int(group_id), "user_id": int(user_id), "duration": max(0, int(duration))},
        )

    async def get_group_info(self, group_id: str) -> dict[str, Any]:
        return await self.call("get_group_info", {"group_id": int(group_id)})

    async def get_group_member_info(self, group_id: str, user_id: str, no_cache: bool = False) -> dict[str, Any]:
        return await self.call(
            "get_group_member_info",
            {"group_id": int(group_id), "user_id": int(user_id), "no_cache": no_cache},
        )

    async def get_group_member_list(self, group_id: str) -> dict[str, Any]:
        return await self.call("get_group_member_list", {"group_id": int(group_id)})

    async def call(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            response = await client.post(f"{self.base_url}/{action}", json=payload)
            response.raise_for_status()
            data = response.json()
        retcode = data.get("retcode")
        if retcode not in (None, 0):
            raise RuntimeError(f"NapCat API error for {action}: {data}")
        return data


class GitHubClient:
    def __init__(self, settings: Settings) -> None:
        self.token = settings.github_token
        self.api_version = settings.github_api_version
        self.base_url = "https://api.github.com"

    async def trigger_workflow(
        self,
        repo: RepoConfig,
        workflow_id: str,
        ref: str,
        inputs: dict[str, str] | None = None,
    ) -> None:
        payload: dict[str, Any] = {"ref": ref}
        if inputs:
            payload["inputs"] = inputs
        await self._request(
            "POST",
            f"/repos/{repo.owner}/{repo.repo}/actions/workflows/{workflow_id}/dispatches",
            json=payload,
            expected={200, 201, 202, 204},
            require_token=True,
        )

    async def list_workflow_runs(
        self,
        repo: RepoConfig,
        workflow_id: str | None = None,
        *,
        branch: str | None = None,
        per_page: int = 5,
    ) -> list[dict[str, Any]]:
        path = f"/repos/{repo.owner}/{repo.repo}/actions/runs"
        if workflow_id:
            path = f"/repos/{repo.owner}/{repo.repo}/actions/workflows/{workflow_id}/runs"
        params: dict[str, Any] = {"per_page": per_page}
        if branch:
            params["branch"] = branch
        data = await self._request("GET", path, params=params)
        return list(data.get("workflow_runs") or [])

    async def list_open_prs(self, repo: RepoConfig, per_page: int = 5) -> list[dict[str, Any]]:
        data = await self._request(
            "GET",
            f"/repos/{repo.owner}/{repo.repo}/pulls",
            params={"state": "open", "per_page": per_page},
        )
        return list(data)

    async def get_pr(self, repo: RepoConfig, number: int) -> dict[str, Any]:
        return await self._request("GET", f"/repos/{repo.owner}/{repo.repo}/pulls/{number}")

    async def get_issue(self, repo: RepoConfig, number: int) -> dict[str, Any]:
        return await self._request("GET", f"/repos/{repo.owner}/{repo.repo}/issues/{number}")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        expected: set[int] | None = None,
        require_token: bool = False,
        **kwargs: Any,
    ) -> Any:
        if require_token and not self.token:
            raise RuntimeError("GITHUB_TOKEN is required for this operation")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self.api_version,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            response = await client.request(method, f"{self.base_url}{path}", **kwargs)
        ok_codes = expected or {200}
        if response.status_code not in ok_codes:
            detail = response.text[:500]
            raise RuntimeError(f"GitHub API {method} {path} failed: {response.status_code} {detail}")
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()
