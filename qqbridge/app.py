from __future__ import annotations

import asyncio
from contextlib import suppress
import random
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from .clients import GitHubClient, HermesClient, NapCatClient
from .commands import build_registry
from .message_store import MessageStore
from .router import BridgeService
from .settings import Settings, load_bridge_config
from .skill_api import build_skill_router
from .state import BridgeState


def create_app() -> FastAPI:
    settings = Settings()
    config = load_bridge_config(settings)
    state = BridgeState(settings.state_path, settings.max_history_messages)
    store = MessageStore(settings.message_store_path, settings.message_archive_dir)
    hermes = HermesClient(settings)
    napcat = NapCatClient(settings)
    github = GitHubClient(settings)
    commands = build_registry(settings.admin_prefix, settings.public_prefix)
    service = BridgeService(
        settings=settings,
        config=config,
        state=state,
        store=store,
        hermes=hermes,
        napcat=napcat,
        github=github,
        commands=commands,
    )

    app = FastAPI(title="AgentBridge", version="0.1.0")
    app.state.settings = settings
    app.state.config = config
    app.state.service = service
    app.state.store = store
    app.state.ambient_task = None
    app.state.group_attention_task = None
    app.include_router(
        build_skill_router(settings=settings, config=config, state=state, store=store, napcat=napcat, github=github)
    )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "agentbridge",
            "admins_configured": bool(config.admin_qq_ids),
            "repos_configured": sorted(config.repos),
        }

    @app.post(settings.qqbridge_webhook_path)
    async def onebot_webhook(request: Request) -> dict[str, Any]:
        _verify_webhook_token(request, settings)
        event = await request.json()
        if not isinstance(event, dict):
            raise HTTPException(status_code=400, detail="expected JSON object")
        return await service.handle_event(event)

    @app.post("/ambient/tick")
    async def ambient_tick(request: Request) -> dict[str, Any]:
        _verify_webhook_token(request, settings)
        return await service.tick_ambient()

    @app.post("/group-attention/tick")
    async def group_attention_tick(request: Request) -> dict[str, Any]:
        _verify_webhook_token(request, settings)
        return await service.tick_group_attention()

    app.router.add_event_handler("startup", _make_startup(app, service, settings))
    app.router.add_event_handler("shutdown", _make_shutdown(app))

    return app


def _verify_webhook_token(request: Request, settings: Settings) -> None:
    expected = settings.qqbridge_webhook_token
    if not expected:
        return
    header_token = request.headers.get("x-qqbridge-token")
    authorization = request.headers.get("authorization", "")
    if header_token == expected or authorization == f"Bearer {expected}":
        return
    raise HTTPException(status_code=401, detail="invalid webhook token")


async def _ambient_loop(service: BridgeService, settings: Settings) -> None:
    while True:
        await asyncio.sleep(_next_ambient_delay(settings))
        with suppress(Exception):
            await service.tick_ambient()


async def _group_attention_loop(service: BridgeService, settings: Settings) -> None:
    while True:
        await asyncio.sleep(max(0.2, settings.group_attention_tick_seconds))
        with suppress(Exception):
            await service.tick_group_attention()


def _next_ambient_delay(settings: Settings) -> float:
    mean = max(30, settings.ambient_interval_seconds)
    delay = random.expovariate(1 / mean)
    return max(settings.ambient_jitter_min_seconds, min(settings.ambient_jitter_max_seconds, delay))


def _make_startup(app: FastAPI, service: BridgeService, settings: Settings):
    async def startup() -> None:
        if settings.ambient_enabled:
            app.state.ambient_task = asyncio.create_task(_ambient_loop(service, settings))
        if settings.group_attention_enabled:
            app.state.group_attention_task = asyncio.create_task(_group_attention_loop(service, settings))

    return startup


def _make_shutdown(app: FastAPI):
    async def shutdown() -> None:
        task = app.state.ambient_task
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        attention_task = app.state.group_attention_task
        if attention_task:
            attention_task.cancel()
            with suppress(asyncio.CancelledError):
                await attention_task

    return shutdown
