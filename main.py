import asyncio
import logging
import sys

from telegram.ext import Application

from config import TELEGRAM_TOKEN
from bot.handlers import register_handlers
from trading.monitor import monitor_loop, set_app as ema_set_app
from trading.harpoon_monitor import harpoon_loop, set_app as harpoon_set_app
from database.client import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)


async def main():
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN غير موجود!")
        sys.exit(1)

    logger.info("🚀 GRD Bot يبدأ...")
    await init_db()

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    register_handlers(app)
    ema_set_app(app)
    harpoon_set_app(app)

    await app.initialize()
    await app.start()

    # تشغيل كلا الاستراتيجيتين بالتوازي
    asyncio.create_task(monitor_loop())
    asyncio.create_task(harpoon_loop())

    logger.info("✅ EMA + HARPOON monitors started")
    await app.updater.start_polling(drop_pending_updates=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
