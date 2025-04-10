import logging
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from Google_sheets import add_to_knowledge_base
from Config import GROUP_ID, GROUP_INVITE_LINK
from Keyboards import get_main_keyboard

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Определяем состояния для FSM
class AddQAStates(StatesGroup):
    waiting_for_data = State()

async def is_user_in_group(bot: Bot, user_id: int, group_id: str, check_admin: bool = False) -> bool:
    """
    Проверяет, состоит ли пользователь в указанной группе.
    Если check_admin=True, проверяет, является ли пользователь администратором или создателем группы.
    """
    try:
        member = await bot.get_chat_member(chat_id=group_id, user_id=user_id)
        if check_admin:
            return member.status in ["administrator", "creator"]
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.error(f"Ошибка проверки членства в группе {group_id} для пользователя {user_id}: {e}")
        return False

def create_subscription_keyboard() -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру с кнопкой для подписки на закрытую группу.
    """
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Подписаться на группу", url=GROUP_INVITE_LINK)]
    ])
    return keyboard

def create_welcome_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    """
    Создаёт приветственную клавиатуру с кнопками MiniApp и Инструкция.
    """
    # Создаём ссылку на MiniApp
    mini_app_url = f"https://t.me/{bot_username}?startapp=support"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="MiniApp", url=mini_app_url),
            InlineKeyboardButton(text="Инструкция", callback_data="instruction")
        ]
    ])
    return keyboard

def escape_html(text: str) -> str:
    """
    Экранирует специальные HTML-символы в тексте.
    """
    return text.replace("<", "&lt;").replace(">", "&gt;").replace("&", "&amp;")

def register_commands(dp: Dispatcher):
    """
    Регистрирует команды бота.
    """
    logger.info("Начало регистрации команд...")

    async def cmd_start(message: types.Message, bot: Bot):
        """
        Обрабатывает команду /start.
        Проверяет, состоит ли пользователь в группе, и отправляет соответствующее сообщение.
        """
        logger.info(f"Получена команда /start от {message.from_user.id}")

        # Проверяем, состоит ли пользователь в целевой группе
        user_in_group = await is_user_in_group(bot, message.from_user.id, GROUP_ID)
        if not user_in_group:
            logger.info(f"Пользователь {message.from_user.id} не состоит в группе {GROUP_ID}")
            keyboard = create_subscription_keyboard()
            await message.reply(
                "Добрый день! Для использования данного бота вам необходимо подписаться на нашу закрытую группу.",
                reply_markup=keyboard
            )
            return

        # Получаем имя бота для создания ссылки на MiniApp
        bot_username = (await bot.get_me()).username
        keyboard = create_welcome_keyboard(bot_username)
        main_keyboard = get_main_keyboard()
        await message.reply(
            "Добро пожаловать! Я Зелёный, твой умный помощник. Выберите действие: 😊",
            reply_markup=keyboard
        )
        # Отправляем основную клавиатуру
        await message.reply(
            "Задавайте свои вопросы, я готов помочь! 😊",
            reply_markup=main_keyboard
        )

    async def cmd_add_qa(message: types.Message, bot: Bot, state: FSMContext):
        """
        Обрабатывает команду /add_qa для добавления записи в базу знаний.
        Формат: Вопрос: <вопрос> | Ключевые слова: <слова> | Информация: <ответ>
        Доступно только администраторам группы.
        """
        logger.info(f"Получена команда /add_qa от {message.from_user.id}")

        # Проверяем, состоит ли пользователь в целевой группе
        user_in_group = await is_user_in_group(bot, message.from_user.id, GROUP_ID)
        if not user_in_group:
            logger.info(f"Пользователь {message.from_user.id} не состоит в группе {GROUP_ID}")
            keyboard = create_subscription_keyboard()
            await message.reply(
                "Чтобы использовать эту команду, пожалуйста, подпишитесь на нашу закрытую группу.",
                reply_markup=keyboard
            )
            return

        # Проверяем, является ли пользователь администратором группы
        is_admin = await is_user_in_group(bot, message.from_user.id, GROUP_ID, check_admin=True)
        if not is_admin:
            logger.info(f"Пользователь {message.from_user.id} не является администратором группы {GROUP_ID}")
            await message.reply(
                "Эта команда доступна только администраторам группы."
            )
            return

        # Устанавливаем состояние ожидания данных
        await state.set_state(AddQAStates.waiting_for_data)

        # Отправляем шаблон для добавления записи
        template = (
            "Пожалуйста, отправьте информацию в следующем формате:\n\n"
            "<b>Вопрос:</b> [вопрос]\n"
            "<b>Ключевые слова:</b> [слова] (необязательно)\n"
            "<b>Информация:</b> [ответ]\n\n"
            "<b>Пример:</b>\n"
            "Вопрос: Как настроить Wi-Fi?\n"
            "Ключевые слова: Wi-Fi, настройка\n"
            "Информация: 1. Откройте настройки роутера. 2. Выберите сеть. 3. Введите пароль."
        )
        await message.reply(template, parse_mode="HTML")

    async def handle_add_qa_response(message: types.Message, state: FSMContext):
        """
        Обрабатывает ответ пользователя с данными для добавления в базу знаний.
        """
        text = message.text
        logger.info(f"Получен ответ для добавления в базу знаний: {text}")

        try:
            # Парсим текст на части
            parts = text.split("\n")
            question = None
            keywords = ""
            answer = None

            for part in parts:
                part = part.strip()
                if part.startswith("Вопрос:"):
                    question = part.replace("Вопрос:", "").strip()
                elif part.startswith("Ключевые слова:"):
                    keywords = part.replace("Ключевые слова:", "").strip()
                elif part.startswith("Информация:"):
                    answer = part.replace("Информация:", "").strip()

            if not question or not answer:
                await message.reply("Пожалуйста, укажите вопрос и информацию. Ключевые слова необязательны.")
                return

            # Добавляем запись в базу знаний
            success = add_to_knowledge_base(question, keywords, answer)
            if success:
                # Формируем ответ с экранированием текста
                response = (
                    "Запись успешно добавлена в базу знаний! 😊\n\n"
                    f"<b>Вопрос:</b> {escape_html(question)}\n\n"
                    f"<b>Ключевые слова:</b> {escape_html(keywords) if keywords else 'Не указаны'}\n\n"
                    f"<b>Информация:</b> {escape_html(answer)}"
                )
                await message.reply(response, parse_mode="HTML")
            else:
                await message.reply("Не удалось добавить запись в базу знаний. Попробуйте позже.")
        except Exception as e:
            logger.error(f"Ошибка при выполнении команды /add_qa: {e}")
            await message.reply("Произошла ошибка при добавлении записи. Попробуйте позже.")
        finally:
            # Сбрасываем состояние после обработки
            await state.clear()

    async def cmd_inf1(message: types.Message, bot: Bot):
        """
        Обрабатывает команду /inf1.
        Отправляет информацию с заголовком и кнопкой.
        """
        logger.info(f"Получена команда /inf1 от {message.from_user.id}")

        # Проверяем, состоит ли пользователь в целевой группе
        user_in_group = await is_user_in_group(bot, message.from_user.id, GROUP_ID)
        if not user_in_group:
            logger.info(f"Пользователь {message.from_user.id} не состоит в группе {GROUP_ID}")
            keyboard = create_subscription_keyboard()
            await message.reply(
                "Чтобы использовать эту команду, пожалуйста, подпишитесь на нашу закрытую группу.",
                reply_markup=keyboard
            )
            return

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Подробнее", url="https://example.com")]
        ])
        await message.reply(
            "Заголовок 1\n\nИнформация: Здесь будет информация для команды /inf1.",
            reply_markup=keyboard
        )

    async def cmd_inf2(message: types.Message, bot: Bot):
        """
        Обрабатывает команду /inf2.
        Отправляет информацию с заголовком и кнопкой.
        """
        logger.info(f"Получена команда /inf2 от {message.from_user.id}")

        # Проверяем, состоит ли пользователь в целевой группе
        user_in_group = await is_user_in_group(bot, message.from_user.id, GROUP_ID)
        if not user_in_group:
            logger.info(f"Пользователь {message.from_user.id} не состоит в группе {GROUP_ID}")
            keyboard = create_subscription_keyboard()
            await message.reply(
                "Чтобы использовать эту команду, пожалуйста, подпишитесь на нашу закрытую группу.",
                reply_markup=keyboard
            )
            return

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Подробнее", url="https://example.com")]
        ])
        await message.reply(
            "Заголовок 2\n\nИнформация: Здесь будет информация для команды /inf2.",
            reply_markup=keyboard
        )

    # Регистрируем обработчики
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_add_qa, Command("add_qa"))
    dp.message.register(handle_add_qa_response, AddQAStates.waiting_for_data)
    dp.message.register(cmd_inf1, Command("inf1"))
    dp.message.register(cmd_inf2, Command("inf2"))

    logger.info("Команды успешно зарегистрированы")