from __future__ import annotations

import asyncio
import logging
import signal

from app.config import load_settings
from app.healthcheck import start_healthcheck_server
from app.services.runner import TradingBotRunner
from app.utils.logging_config import setup_logging

LOGGER = logging.getLogger(__name__)


async def serve() -> None:
    settings = load_settings()
    health_runner = await start_healthcheck_server(settings.port)
    runner = TradingBotRunner(settings)

    stop_event = asyncio.Event()

    def _stop(*_: object) -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    LOGGER.info("Signal engine started on port %s", settings.port)
    try:
        await runner.run_forever(stop_event)
    finally:
        await health_runner.cleanup()


def main() -> None:
    setup_logging()
    asyncio.run(serve())


if __name__ == "__main__":
    main()
