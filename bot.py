import sys
import io
import logging
import asyncio
import os
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from Config import TELEGRAM_TOKEN
from Commands import register_commands
from Handlers import register_handlers
from Google_sheets import initialize_knowledge_base

# Добавляем текущую директорию в sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Настройка кодировки консоли для Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/main.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Функция для периодического обновления базы знаний (каждые 15 минут)
async def update_knowledge_base_periodically():
    while True:
        logger.info("Периодическое обновление базы знаний...")
        await initialize_knowledge_base()
        await asyncio.sleep(43200)  # 15 минут

async def main():
    """
    Основная функция для запуска бота.
    """
    logger.info("Инициализация бота...")
    bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()

    logger.info("Инициализация диспетчера...")
    register_commands(dp)
    register_handlers(dp)

    logger.info("Бот запущен")
    await initialize_knowledge_base()
    
    # Запускаем фоновую задачу для обновления базы знаний
    asyncio.create_task(update_knowledge_base_periodically())
    
    logger.info("Start polling")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())