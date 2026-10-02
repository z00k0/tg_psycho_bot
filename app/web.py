"""aiohttp webhook application and production lifecycle."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from app.bot.gateway import ThreadedSearchGateway
from app.bot.handlers import BotSearchGateway, create_router
from app.config import Settings
from app.db.capabilities import check_sqlite_fts5_trigram
from app.logging_config import configure_logging

ALLOWED_UPDATES = ["message", "callback_query"]

logger = logging.getLogger("tg_psyco.web")

SETTINGS_KEY = web.AppKey("settings", Settings)
BOT_KEY = web.AppKey("bot", Bot)
DISPATCHER_KEY = web.AppKey("dispatcher", Dispatcher)
GATEWAY_KEY = web.AppKey("gateway", ThreadedSearchGateway)
WEBHOOK_HANDLER_KEY = web.AppKey("webhook_handler", SimpleRequestHandler)
GATEWAY_FACTORY_KEY = web.AppKey("gateway_factory", object)


class LifecycleGateway(BotSearchGateway, Protocol):
    async def is_ready(self) -> bool: ...

    async def close(self) -> None: ...


type GatewayFactory = Callable[[Settings], Awaitable[LifecycleGateway]]


class WebhookAdminError(RuntimeError):
    """Raised when an explicit webhook administration call fails."""


async def _default_gateway_factory(settings: Settings) -> ThreadedSearchGateway:
    return await ThreadedSearchGateway.create(
        settings.database_path,
        result_limit=settings.search_result_limit,
        max_query_length=settings.max_query_length,
    )


async def healthz(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def readyz(request: web.Request) -> web.Response:
    gateway = request.app.get(GATEWAY_KEY)
    try:
        ready = gateway is not None and await gateway.is_ready()
    except Exception:
        ready = False
    status = 200 if ready else 503
    return web.json_response({"status": "ready" if ready else "not_ready"}, status=status)


async def _startup(app: web.Application) -> None:
    settings = app[SETTINGS_KEY]
    bot = app[BOT_KEY]
    dispatcher = app[DISPATCHER_KEY]
    gateway_factory: GatewayFactory = app[GATEWAY_FACTORY_KEY]  # type: ignore[assignment]

    await asyncio.to_thread(check_sqlite_fts5_trigram)
    gateway = await gateway_factory(settings)
    try:
        webhook_set = await bot.set_webhook(
            settings.webhook_url,
            secret_token=settings.webhook_secret,
            allowed_updates=ALLOWED_UPDATES,
        )
        if not webhook_set:
            raise RuntimeError("Telegram rejected webhook registration")
    except BaseException as exc:
        logger.error(
            "webhook_registration_failed",
            extra={
                "event": "webhook_registration_failed",
                "error_type": type(exc).__name__,
            },
        )
        await gateway.close()
        raise

    app[GATEWAY_KEY] = gateway  # type: ignore[assignment]
    dispatcher["gateway"] = gateway
    logger.info(
        "webhook_registered",
        extra={"event": "webhook_registered"},
    )


async def _shutdown(app: web.Application) -> None:
    dispatcher = app[DISPATCHER_KEY]
    gateway = app.get(GATEWAY_KEY)
    dispatcher.workflow_data.pop("gateway", None)
    if gateway is not None:
        await gateway.close()


def create_application(
    settings: Settings,
    *,
    bot: Bot | None = None,
    dispatcher: Dispatcher | None = None,
    gateway_factory: GatewayFactory = _default_gateway_factory,
) -> web.Application:
    """Build a side-effect-free aiohttp application; I/O starts on startup."""

    application = web.Application()
    application[SETTINGS_KEY] = settings
    application[BOT_KEY] = bot_instance = bot or Bot(settings.bot_token)
    application[DISPATCHER_KEY] = dispatcher_instance = dispatcher or Dispatcher()
    application[GATEWAY_FACTORY_KEY] = gateway_factory

    dispatcher_instance.include_router(create_router())
    application.router.add_get("/healthz", healthz)
    application.router.add_get("/readyz", readyz)
    application.on_startup.append(_startup)

    webhook_handler = SimpleRequestHandler(
        dispatcher=dispatcher_instance,
        bot=bot_instance,
        handle_in_background=True,
        secret_token=settings.webhook_secret,
    )
    application[WEBHOOK_HANDLER_KEY] = webhook_handler
    webhook_handler.register(application, path=settings.webhook_path)
    setup_application(application, dispatcher_instance, bot=bot_instance)
    # Wait for webhook tasks and dispatcher shutdown hooks before closing SQLite.
    application.on_shutdown.append(_shutdown)
    return application


def run_server(settings: Settings) -> None:
    configure_logging(secrets=(settings.bot_token, settings.webhook_secret))
    web.run_app(
        create_application(settings),
        host=settings.host,
        port=settings.port,
    )


async def delete_configured_webhook(
    settings: Settings,
    *,
    drop_pending_updates: bool = False,
    bot: Bot | None = None,
) -> None:
    bot_instance = bot or Bot(settings.bot_token)
    try:
        try:
            deleted = await bot_instance.delete_webhook(
                drop_pending_updates=drop_pending_updates
            )
        except Exception as exc:
            logger.error(
                "webhook_removal_failed",
                extra={
                    "event": "webhook_removal_failed",
                    "error_type": type(exc).__name__,
                },
            )
            raise WebhookAdminError("Telegram webhook removal failed") from exc
        if not deleted:
            logger.error(
                "webhook_removal_rejected",
                extra={
                    "event": "webhook_removal_rejected",
                    "error_type": "TelegramRejectedOperation",
                },
            )
            raise WebhookAdminError("Telegram rejected webhook removal")
    finally:
        await bot_instance.session.close()
