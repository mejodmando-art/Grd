import asyncio
import logging
import sys

from telegram.ext import Application

from config import TELEGRAM_TOKEN
from bot.handlers import register_handlers
from trading.monitor import monitor_loop, set_app as set_ema_app
from trading.harpoon_monitor import harpoon_loop, set_app as set_harpoon_app
from database.client import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def main():
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN is not set!")
        sys.exit(1)

    logger.info("🚀 Starting advanced trading bot...")

    await init_db()

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    register_handlers(app)
    set_ema_app(app)
    set_harpoon_app(app)

    logger.info("✅ Bot started. Polling...")
    await app.initialize()
    await app.start()

    # تشغيل المراقبتين في الخلفية
    asyncio.create_task(monitor_loop())
    asyncio.create_task(harpoon_loop())

    await app.updater.start_polling(drop_pending_updates=True)

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())