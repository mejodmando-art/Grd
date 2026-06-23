import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from telegram.ext import Application

from config import TELEGRAM_TOKEN
from bot.handlers import register_handlers
from trading.monitor import monitor_loop, set_app as ema_set_app
from trading.harpoon_monitor import harpoon_loop, set_app as harpoon_set_app
from database.client import init_db
from trading.mexc_client import close_session as close_mexc_session

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)


async def shutdown(tasks):
    """Cancel all tasks gracefully."""
    logger.info("🛑 Shutting down...")
    for task in tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Close HTTP sessions
    await close_mexc_session()
    logger.info("✅ Shutdown complete")


async def main():
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN غير موجود!")
        sys.exit(1)

    logger.info("🚀 GRD Bot starting...")
    await init_db()

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    register_handlers(app)
    ema_set_app(app)
    harpoon_set_app(app)

    await app.initialize()
    await app.start()

    # Create tasks with proper management
    tasks = []
    try:
        tasks.append(asyncio.create_task(monitor_loop(), name="EMA_Monitor"))
        tasks.append(asyncio.create_task(harpoon_loop(), name="HARPOON_Monitor"))

        logger.info("✅ EMA + HARPOON monitors started")
        await app.updater.start_polling(drop_pending_updates=True)

        # Keep running until interrupted
        await asyncio.Event().wait()

    except asyncio.CancelledError:
        logger.info("Received cancellation signal")
    finally:
        await shutdown(tasks)
        await app.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)