import asyncio, logging, sys
from telegram.ext import Application
from config import TELEGRAM_TOKEN
from bot.handlers import register_handlers
from trading.monitor import monitor_loop, set_app
from database.client import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)

async def main():
    if not TELEGRAM_TOKEN: sys.exit(1)
    logger.info("🚀 Starting Gate.io bot...")
    await init_db()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    register_handlers(app)
    set_app(app)
    await app.initialize()
    await app.start()
    asyncio.create_task(monitor_loop())
    await app.updater.start_polling(drop_pending_updates=True)
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())