from __future__ import annotations

from typing import Any

from .agent_output import parse_agent_plan
from .capabilities import GROUP_AMBIENT_TOOLS, GROUP_IMMEDIATE_TOOLS, PRIVATE_TOOLS
from .clients import GitHubClient, HermesClient, NapCatClient
from .commands import CommandContext, CommandRegistry
from .message_store import MessageStore
from .models import InboundMessage, keyword_hit, mentions_bot, parse_inbound_message, reply_ids
from .prompts import (
    AMBIENT_GROUP_PROMPT,
    GROUP_ATTENTION_PROMPT,
    GROUP_KEYWORD_PROMPT,
    GROUP_MENTION_PROMPT,
    PRIVATE_PROMPT,
    with_persona,
)
from .settings import BridgeConfig, Settings
from .state import BridgeState
from .text import is_skip_response, split_qq_message


class BridgeService:
    def __init__(
        self,
        *,
        settings: Settings,
        config: BridgeConfig,
        state: BridgeState,
        store: MessageStore,
        hermes: HermesClient,
        napcat: NapCatClient,
        github: GitHubClient,
        commands: CommandRegistry,
    ) -> None:
        self.settings = settings
        self.config = config
        self.state = state
        self.store = store
        self.hermes = hermes
        self.napcat = napcat
        self.github = github
        self.commands = commands

    async def handle_event(self, event: dict[str, Any]) -> dict[str, Any]:
        import logging
        log = logging.getLogger("agentbridge.router")
        post_type = event.get("post_type")
        if post_type == "message":
            log.info("[RAW] type=%s user=%s group=%s text=%r",
                     event.get("message_type"), event.get("user_id"),
                     event.get("group_id"), str(event.get("raw_message",""))[:80])
        else:
            log.debug("[RAW] non-message event: post_type=%s", post_type)
        inbound = parse_inbound_message(event)
        if inbound is None:
            return {"ok": True, "action": "ignored", "reason": "not_message"}
        if inbound.user_id == inbound.self_id:
            return {"ok": True, "action": "ignored", "reason": "self_message"}
        if self.state.seen_event(inbound.dedup_key):
            return {"ok": True, "action": "ignored", "reason": "duplicate"}

        log.info("[ROUTE] type=%s group=%s user=%s text=%r", inbound.message_type, inbound.group_id, inbound.user_id, inbound.plain_text[:80])

        if inbound.group_id:
            self.state.append_group_message(
                inbound.group_id,
                inbound.sender_name,
                inbound.user_id,
                inbound.plain_text,
                inbound.message_id,
            )
        self._persist_inbound(inbound)

        if self.commands.is_command_text(inbound.plain_text):
            return await self._handle_command(inbound)

        route = self._route_llm(inbound)
        if route is None:
            if self._queue_group_attention_if_active(inbound):
                log.info("[ROUTE] queued active group attention group=%s", inbound.group_id)
                return {"ok": True, "action": "queued", "reason": "active_group_attention"}
            log.info("[ROUTE] no LLM route for type=%s group=%s", inbound.message_type, inbound.group_id)
            return {"ok": True, "action": "ignored", "reason": "no_route"}
        prompt, allow_skip, reason = route
        log.info("[ROUTE] reason=%s allow_skip=%s", reason, allow_skip)
        if not self.state.allow_user_llm(inbound.user_id, self.settings.user_rate_limit_per_minute):
            return {"ok": True, "action": "ignored", "reason": "rate_limited"}

        run = self._create_run_for_inbound(inbound, reason)
        log.info("[RUN] id=%s tools=%s", run.get("run_id"), run.get("allowed_tools"))
        user_content = self._with_run_context(self._build_user_content(inbound), run, inbound=inbound)
        conversation_key = self._conversation_key(inbound)
        session_id = self.state.hermes_session_id(conversation_key)
        log.info("[LLM] calling hermes session=%s", session_id)
        answer = await self.hermes.chat(prompt, [], user_content, session_id=session_id)
        log.info("[LLM] answer=%r", answer[:200])
        if allow_skip and is_skip_response(answer):
            if inbound.group_id:
                self.state.remove_unread_group_messages(inbound.group_id, [inbound.message_id])
            return {"ok": True, "action": "skipped", "reason": reason}

        # Agent sends messages via tools (qq.send_message etc.), not through bridge auto-send.
        # Response text is for logging/decision only.
        if inbound.group_id:
            self.state.remove_unread_group_messages(inbound.group_id, [inbound.message_id])
        return {"ok": True, "action": "agent_handoff", "reason": reason}

    async def _handle_command(self, inbound: InboundMessage) -> dict[str, Any]:
        is_admin = inbound.user_id in self.config.admin_qq_ids
        base_group_config = self.config.group_config(inbound.group_id)
        effective_group_config = (
            self.state.effective_group_config(inbound.group_id, base_group_config) if inbound.group_id else None
        )
        ctx = CommandContext(
            user_id=inbound.user_id,
            group_id=inbound.group_id,
            is_admin=is_admin,
            conversation_key=self._conversation_key(inbound),
            config=self.config,
            group_config=effective_group_config,
            state=self.state,
            github=self.github,
            hermes=self.hermes,
            napcat=self.napcat,
        )
        result = await self.commands.dispatch(inbound.plain_text, ctx)
        if inbound.group_id:
            self.state.remove_unread_group_messages(inbound.group_id, [inbound.message_id])
        if result is None:
            return {"ok": True, "action": "ignored", "reason": "unknown_or_unauthorized_command"}
        if result.private and inbound.is_group:
            await self._send_private(inbound.user_id, result.text)
        else:
            await self._send_text(inbound, result.text, reply=False)
        return {"ok": True, "action": "command"}

    def _route_llm(self, inbound: InboundMessage) -> tuple[str, bool, str] | None:
        if inbound.is_private:
            return with_persona(PRIVATE_PROMPT, self.settings.bot_persona), False, "private"
        if not inbound.group_id:
            return None

        base = self.config.group_config(inbound.group_id)
        group_config = self.state.effective_group_config(inbound.group_id, base)
        if mentions_bot(inbound, self.config.bot_qq_id, self.config.bot_names):
            return with_persona(GROUP_MENTION_PROMPT, self.settings.bot_persona), False, "mention"

        if any(self.state.is_reply_to_bot(inbound.group_id, reply_id) for reply_id in reply_ids(inbound.segments)):
            return with_persona(GROUP_MENTION_PROMPT, self.settings.bot_persona), False, "reply_to_bot"

        hit = keyword_hit(inbound.plain_text, group_config.keywords)
        if hit:
            return with_persona(GROUP_KEYWORD_PROMPT, self.settings.bot_persona), True, f"keyword:{hit}"

        return None

    def _queue_group_attention_if_active(self, inbound: InboundMessage) -> bool:
        if not self.settings.group_attention_enabled or not inbound.group_id:
            return False
        return self.state.queue_group_attention_message(
            group_id=inbound.group_id,
            user_id=inbound.user_id,
            sender=inbound.sender_name,
            text=inbound.plain_text,
            message_id=inbound.message_id,
            ttl_seconds=self.settings.group_attention_ttl_seconds,
            batch_interval_seconds=self.settings.group_attention_batch_interval_seconds,
            max_buffer_messages=self.settings.group_attention_max_buffer_messages,
        )

    def _persist_inbound(self, inbound: InboundMessage) -> None:
        self.store.add_message(
            message_id=inbound.message_id,
            message_type=inbound.message_type,
            group_id=inbound.group_id,
            user_id=inbound.user_id,
            self_id=inbound.self_id,
            sender_name=inbound.sender_name,
            plain_text=inbound.plain_text,
            raw_message=inbound.raw_message,
            segments=[{"type": segment.type, "data": segment.data} for segment in inbound.segments],
            reply_to=reply_ids(inbound.segments)[0] if reply_ids(inbound.segments) else None,
            at_bot=mentions_bot(inbound, self.config.bot_qq_id, self.config.bot_names),
            is_from_bot=inbound.user_id == inbound.self_id,
            event=inbound.event,
            timestamp=int(inbound.event.get("time") or 0) or None,
        )

    async def tick_ambient(self) -> dict[str, Any]:
        if not self.settings.ambient_enabled:
            return {"ok": True, "action": "ambient_disabled"}
        groups = self.state.ambient_groups_with_unread(self.settings.ambient_min_unread_messages)
        results = []
        for group_id in groups:
            base = self.config.group_config(group_id)
            group_config = self.state.effective_group_config(group_id, base)
            if not group_config.autonomous_enabled:
                continue
            if self.state.active_group_attention(group_id):
                continue
            if not self.state.can_group_autoreply_now(group_id, group_config.min_seconds_between_replies):
                continue
            result = await self._run_ambient_group(group_id)
            results.append({"group_id": group_id, **result})
        return {"ok": True, "action": "ambient_tick", "groups": results}

    async def tick_group_attention(self) -> dict[str, Any]:
        if not self.settings.group_attention_enabled:
            return {"ok": True, "action": "group_attention_disabled"}
        groups = self.state.ready_group_attention_groups()
        results = []
        for group_id in groups:
            batch = self.state.pop_group_attention_batch(
                group_id,
                max_batch_messages=self.settings.group_attention_max_batch_messages,
                batch_interval_seconds=self.settings.group_attention_batch_interval_seconds,
            )
            if not batch:
                continue
            try:
                result = await self._run_group_attention_batch(group_id, batch)
            except Exception:
                self.state.requeue_group_attention_batch(group_id, batch)
                raise
            results.append({"group_id": group_id, "messages": len(batch), **result})
        return {"ok": True, "action": "group_attention_tick", "groups": results}

    async def _run_ambient_group(self, group_id: str) -> dict[str, Any]:
        unread = self.state.unread_group_messages(group_id, self.settings.ambient_max_unread_messages)
        if not unread:
            return {"action": "skipped", "reason": "no_unread"}
        run = self.state.create_agent_run(
            mode="ambient",
            group_id=group_id,
            allowed_tools=GROUP_AMBIENT_TOOLS,
            allowed_repos=list(self.config.repos),
            ttl_seconds=self.settings.agent_run_ttl_seconds,
            max_tool_calls=20,
        )
        user_content = self._with_run_context(self._build_ambient_content(group_id, unread), run)
        session_id = self.state.hermes_session_id(f"group:{group_id}")
        answer = await self.hermes.chat(
            with_persona(AMBIENT_GROUP_PROMPT, self.settings.bot_persona),
            [],
            user_content,
            session_id=session_id,
        )
        plan = parse_agent_plan(answer)
        if plan.should_skip:
            self.state.clear_unread_group_messages(group_id)
            return {"action": "skipped", "reason": "agent_skip"}

        self.state.clear_unread_group_messages(group_id)
        return {"action": "agent_handoff"}

    async def _run_group_attention_batch(self, group_id: str, batch: list[dict[str, Any]]) -> dict[str, Any]:
        if not batch:
            return {"action": "skipped", "reason": "empty_batch"}
        attention_generation = self.state.group_attention_generation(group_id)
        run = self.state.create_agent_run(
            mode="active_dialogue",
            group_id=group_id,
            trigger_message_id=str(batch[-1].get("message_id") or ""),
            allowed_tools=GROUP_IMMEDIATE_TOOLS,
            allowed_repos=list(self.config.repos),
            ttl_seconds=self.settings.agent_run_ttl_seconds,
            max_tool_calls=20,
        )
        user_content = self._with_run_context(self._build_group_attention_content(group_id, batch), run)
        session_id = self.state.hermes_session_id(f"group:{group_id}")
        answer = await self.hermes.chat(
            with_persona(GROUP_ATTENTION_PROMPT, self.settings.bot_persona),
            [],
            user_content,
            session_id=session_id,
        )
        plan = parse_agent_plan(answer)
        if plan.should_skip:
            self.state.remove_unread_group_messages(group_id, [str(item.get("message_id")) for item in batch])
            self.state.close_group_attention_if_generation(group_id, attention_generation)
            return {"action": "skipped", "reason": "agent_skip"}
        self.state.remove_unread_group_messages(group_id, [str(item.get("message_id")) for item in batch])
        self.state.close_group_attention_if_generation(group_id, attention_generation)
        return {"action": "agent_handoff"}

    def _create_run_for_inbound(self, inbound: InboundMessage, reason: str) -> dict[str, Any]:
        if inbound.is_private:
            allowed_tools = PRIVATE_TOOLS
            mode = "private"
        else:
            allowed_tools = GROUP_IMMEDIATE_TOOLS
            mode = "immediate"
        return self.state.create_agent_run(
            mode=mode,
            group_id=inbound.group_id,
            user_id=inbound.user_id,
            trigger_message_id=inbound.message_id,
            allowed_tools=allowed_tools,
            allowed_repos=list(self.config.repos),
            ttl_seconds=self.settings.agent_run_ttl_seconds,
            max_tool_calls=20,
        )

    def _conversation_key(self, inbound: InboundMessage) -> str:
        if inbound.group_id:
            return f"group:{inbound.group_id}"
        return inbound.conversation_key

    def _with_run_context(self, content: str, run: dict[str, Any], inbound=None) -> str:
        tools = ", ".join(run.get("allowed_tools", []))
        context_parts = [
            f"AgentBridge agent_run_id: {run['run_id']}",
            f"run_mode: {run.get('mode')}",
            f"allowed_tools: {tools}",
            f"expires_at_unix: {run.get('expires_at')}",
            f"调用 AgentBridge skill 时必须传 run_id={run['run_id']}。",
        ]
        if inbound:
            if inbound.user_id:
                context_parts.append(f"sender_user_id: {inbound.user_id}")
            if inbound.group_id:
                context_parts.append(f"current_group_id: {inbound.group_id}")
            if inbound.message_id:
                context_parts.append(f"trigger_message_id: {inbound.message_id}")
        return "\n".join(context_parts) + f"\n\n{content}"

    def _build_user_content(self, inbound: InboundMessage) -> str:
        if inbound.is_private:
            return inbound.plain_text
        assert inbound.group_id is not None
        recent = self.state.recent_group_context(inbound.group_id, self.settings.max_group_context_messages)
        stored_recent = self.store.recent_group_messages(inbound.group_id, self.settings.max_group_context_messages)
        if stored_recent:
            recent = stored_recent
        context_lines = [
            f"- {item.get('sender_name') or item.get('sender') or item.get('user_id', '?')}: {item.get('plain_text') or item.get('text', '')}"
            for item in recent
            if item.get("plain_text") or item.get("text")
        ]
        context = "\n".join(context_lines)
        archive = self.store.archive_paths(group_id=inbound.group_id)
        archive_paths = "\n".join(f"- {path}" for path in archive.get("paths", [])[-7:])
        return (
            f"QQ群号：{inbound.group_id}\n"
            f"当前发言人：{inbound.sender_name}({inbound.user_id})\n"
            f"群聊消息归档 JSONL 路径：\n{archive_paths or '- 暂无归档文件'}\n\n"
            f"最近群聊：\n{context}\n\n"
            f"当前消息：{inbound.plain_text}"
        )

    def _build_ambient_content(self, group_id: str, unread: list[dict[str, Any]]) -> str:
        lines = []
        for index, item in enumerate(unread, start=1):
            sender = item.get("sender", item.get("user_id", "?"))
            user_id = item.get("user_id", "?")
            text = item.get("text", "")
            ts = item.get("ts", "")
            message_id = item.get("message_id") or f"ambient:{index}"
            lines.append(f"{index}. message_id={message_id} ts={ts} sender={sender}({user_id}): {text}")
        archive = self.store.archive_paths(group_id=group_id)
        archive_paths = "\n".join(f"- {path}" for path in archive.get("paths", [])[-7:]) or "- 暂无归档文件"
        return (
            f"QQ群号：{group_id}\n"
            f"群聊消息归档 JSONL 路径：\n{archive_paths}\n\n"
            f"以下是你这次查看手机时看到的未读群聊消息。请判断是否需要参与。\n"
            f"未读消息：\n" + "\n".join(lines)
        )

    def _build_group_attention_content(self, group_id: str, batch: list[dict[str, Any]]) -> str:
        batch_lines = []
        for index, item in enumerate(batch, start=1):
            sender = item.get("sender", item.get("user_id", "?"))
            user_id = item.get("user_id", "?")
            text = item.get("text", "")
            ts = item.get("ts", "")
            message_id = item.get("message_id") or f"attention:{index}"
            batch_lines.append(f"{index}. message_id={message_id} ts={ts} sender={sender}({user_id}): {text}")

        recent = self.state.recent_group_context(group_id, self.settings.max_group_context_messages)
        stored_recent = self.store.recent_group_messages(group_id, self.settings.max_group_context_messages)
        if stored_recent:
            recent = stored_recent
        recent_lines = [
            f"- {item.get('sender_name') or item.get('sender') or item.get('user_id', '?')}: {item.get('plain_text') or item.get('text', '')}"
            for item in recent
            if item.get("plain_text") or item.get("text")
        ]
        archive = self.store.archive_paths(group_id=group_id)
        archive_paths = "\n".join(f"- {path}" for path in archive.get("paths", [])[-7:]) or "- 暂无归档文件"
        return (
            f"QQ群号：{group_id}\n"
            f"场景：active_group_attention\n"
            f"说明：你上次在群里发言后，Bridge 为这个群打开了短时注意力窗口。"
            f"下面是倒计时内攒下的一批新消息，不是随机 ambient。\n"
            f"群聊消息归档 JSONL 路径：\n{archive_paths}\n\n"
            f"最近群聊：\n" + "\n".join(recent_lines) + "\n\n"
            f"本批新消息：\n" + "\n".join(batch_lines)
        )

    async def _send_text(self, inbound: InboundMessage, text: str, *, reply: bool) -> None:
        chunks = split_qq_message(text, self.settings.max_message_chars)
        for index, chunk in enumerate(chunks):
            if inbound.is_group and inbound.group_id:
                message: str | list[dict[str, Any]]
                if reply and index == 0:
                    message = [
                        {"type": "reply", "data": {"id": inbound.message_id}},
                        {"type": "text", "data": {"text": chunk}},
                    ]
                else:
                    message = chunk
                data = await self.napcat.send_msg(message_type="group", group_id=inbound.group_id, message=message)
                message_id = _response_message_id(data)
                if message_id:
                    self.state.add_bot_message_id(inbound.group_id, message_id)
                self.state.mark_group_replied(inbound.group_id)
            else:
                await self._send_private(inbound.user_id, chunk)

    async def _send_private(self, user_id: str, text: str) -> None:
        chunks = split_qq_message(text, self.settings.max_message_chars)
        for chunk in chunks:
            await self.napcat.send_msg(message_type="private", user_id=user_id, message=chunk)


def _response_message_id(data: dict[str, Any]) -> str | None:
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    message_id = payload.get("message_id") if isinstance(payload, dict) else None
    return str(message_id) if message_id is not None else None
