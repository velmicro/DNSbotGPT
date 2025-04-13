import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types
from aiogram.types import ParseMode
from aiogram.utils import executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from Prompts import load_prompts
from Handlers import register_handlers
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Инициализация бота
storage = MemoryStorage()
bot = Bot(token=os.getenv("TELEGRAM_TOKEN"), parse_mode=ParseMode.HTML)
dp = Dispatcher(bot, storage=storage)

# Глобальная переменная для хранения настроек и времени последнего изменения
prompts = None
last_modified_time = 0

async def load_prompts_dynamic():
    """
    Загружает настройки из prompts.json, проверяя изменения файла.
    """
    global prompts, last_modified_time
    try:
        # Проверяем время последнего изменения файла
        current_modified_time = os.path.getmtime("prompts.json")
        if current_modified_time != last_modified_time:
            prompts = load_prompts()
            last_modified_time = current_modified_time
            logger.info("Настройки перезагружены из prompts.json")
        return prompts
    except Exception as e:
        logger.error(f"Ошибка при динамической загрузке prompts.json: {e}")
        return prompts if prompts else {}

# Функция для проверки прав администратора
async def is_admin(user_id: int) -> bool:
    prompts = await load_prompts_dynamic()
    admins = prompts.get("settings", {}).get("admins", [])
    return user_id in admins

# Универсальный обработчик команд и текстовых сообщений
@dp.message_handler()
async def handle_message(message: types.Message):
    prompts = await load_prompts_dynamic()
    user_input = message.text.lower().strip()

    # Проверяем команды
    commands = prompts["settings"].get("commands", [])
    for cmd in commands:
        if user_input == cmd["name"].lower():
            if cmd["access"] == "admin" and not await is_admin(message.from_user.id):
                await message.answer("Эта команда доступна только администраторам.")
                return

            # Создаём клавиатуру, если нужно
            reply_markup = None
            if cmd.get("show_keyboard", False):
                buttons = prompts["settings"].get("buttons", [])
                buttons_per_row = prompts["settings"].get("buttons_per_row", 2)
                keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
                button_list = [btn["text"] for btn in sorted(buttons, key=lambda x: x["position"])]
                for i in range(0, len(button_list), buttons_per_row):
                    row = button_list[i:i + buttons_per_row]
                    keyboard.row(*row)
                reply_markup = keyboard

            # Формируем ответ
            if cmd["type"] == "text":
                await message.answer(cmd["response"], reply_markup=reply_markup)
            elif cmd["type"] == "inline_buttons":
                keyboard = types.InlineKeyboardMarkup()
                for btn in cmd["inline_buttons"]:
                    keyboard.add(types.InlineKeyboardButton(text=btn["text"], url=btn["url"]))
                await message.answer(cmd["response"], reply_markup=keyboard)
            return

    # Проверяем кнопки
    buttons = prompts["settings"].get("buttons", [])
    for btn in buttons:
        if user_input == btn["text"].lower():
            await message.answer(btn["response"])
            return

    # Обрабатываем диалоги
    dialogs = prompts.get("dialogs", {})
    if user_input in dialogs:
        await message.answer(dialogs[user_input])
        return

    # Обрабатываем AI-ответы (оставляем как есть)
    # ... (код для AI-ответов остаётся без изменений)

# Регистрация обработчиков (для сценариев, AI и т.д.)
register_handlers(dp)

# Запуск бота
if __name__ == "__main__":
    # Инициализируем настройки при запуске
    prompts = load_prompts()
    last_modified_time = os.path.getmtime("prompts.json")
    executor.start_polling(dp, skip_updates=True)