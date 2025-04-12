import os
from dotenv import load_dotenv
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/config.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения из .env
logger.info("Загрузка переменных окружения из .env...")
load_dotenv()
logger.info("Переменные окружения успешно загружены")

# Определение переменных
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROUP_ID = os.getenv("GROUP_ID")
GROUP_INVITE_LINK = os.getenv("GROUP_INVITE_LINK")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

# Проверка, что переменные загружены
if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN не найден в .env")
    raise ValueError("TELEGRAM_TOKEN не найден в .env")
if not GROQ_API_KEY:
    logger.error("GROQ_API_KEY не найден в .env")
    raise ValueError("GROQ_API_KEY не найден в .env")
if not GROUP_ID:
    logger.error("GROUP_ID не найден в .env")
    raise ValueError("GROUP_ID не найден в .env")
if not GROUP_INVITE_LINK:
    logger.error("GROUP_INVITE_LINK не найден в .env")
    raise ValueError("GROUP_INVITE_LINK не найден в .env")
if not GOOGLE_CREDENTIALS_PATH:
    logger.error("GOOGLE_CREDENTIALS_PATH не найден в .env")
    raise ValueError("GOOGLE_CREDENTIALS_PATH не найден в .env")
if not SPREADSHEET_ID:
    logger.error("SPREADSHEET_ID не найден в .env")
    raise ValueError("SPREADSHEET_ID не найден в .env")

# Вывод токена для отладки
logger.info(f"TELEGRAM_TOKEN: {repr(TELEGRAM_TOKEN)}")
