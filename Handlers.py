import logging
import asyncio
import re
import os
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from Utils import process_message, split_message, is_russian_text
from Config import GROUP_ID, GROUP_INVITE_LINK
from Keyboards import get_reaction_keyboard, get_main_keyboard, get_instruction_keyboard
from Prompts import load_prompts

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

# Логирование реакций
feedback_logger = logging.getLogger("feedback")
feedback_handler = logging.FileHandler("logs/feedback.log", encoding='utf-8')
feedback_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
feedback_logger.addHandler(feedback_handler)
feedback_logger.setLevel(logging.INFO)

# Глобальное хранилище контекста диалогов
dialog_context = {}  # {user_id: [{"role": "user", "content": "вопрос"}, {"role": "assistant", "content": "ответ"}]}

# Загружаем простые диалоги и системные настройки
prompts_data = load_prompts()
simple_dialogs = prompts_data["dialogs"]
system_settings = prompts_data["settings"]

async def is_user_in_group(bot: Bot, user_id: int, group_id: str) -> bool:
    """
    Проверяет, состоит ли пользователь в указанной группе.
    """
    try:
        member = await bot.get_chat_member(chat_id=group_id, user_id=user_id)
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

def register_handlers(dp: Dispatcher):
    """
    Регистрирует обработчики сообщений для бота.
    """
    logger.info("Начало регистрации обработчиков...")

    @dp.message()
    async def handle_message(message: types.Message, bot: Bot):
        """
        Обрабатывает входящие текстовые сообщения, передавая всю логику в process_message.
        """
        logger.info(f"Получено сообщение от {message.from_user.id}: {message.text}")

        # Проверяем, является ли чат личным
        is_private_chat = message.chat.type == "private"

        # Если это группа, проверяем наличие слова "Зелёный"
        if not is_private_chat:
            if not re.search(r"зелёный", message.text.lower()):
                logger.info(f"Сообщение в группе не содержит слово 'Зелёный': {message.text}")
                return

            user_in_group = await is_user_in_group(bot, message.from_user.id, GROUP_ID)
            if not user_in_group:
                logger.info(f"Пользователь {message.from_user.id} не состоит в группе {GROUP_ID}")
                keyboard = create_subscription_keyboard()
                await message.reply(
                    "Чтобы использовать бота в группах, пожалуйста, подпишитесь на нашу закрытую группу.",
                    reply_markup=keyboard
                )
                return

        # Показываем "Зелёный пишет..."
        typing_message = await message.reply("Зелёный пишет…")
        await asyncio.sleep(1)

        query = message.text.strip().lower()
        if not query:
            await typing_message.edit_text("Пожалуйста, отправьте текстовый запрос.")
            return

        # Проверяем, что запрос состоит преимущественно из русских символов
        if not is_russian_text(query):
            await typing_message.edit_text(
                "Запрос содержит слишком много символов не на русском языке. "
                "Пожалуйста, переформулируйте запрос, используя только русский язык! 😔"
            )
            return

        # Обработка нажатий на кнопки основной клавиатуры
        if query == "новый диалог":
            user_id = message.from_user.id
            if user_id in dialog_context:
                del dialog_context[user_id]
            main_keyboard = get_main_keyboard()
            await typing_message.delete()
            await message.reply("Контекст диалога очищен. Новый диалог начат! Задавайте вопросы! 😊",
                               reply_markup=main_keyboard)
            return

        elif query == "о боте":
            main_keyboard = get_main_keyboard()
            await typing_message.delete()
            await message.reply(
                f"Я {system_settings['name']}, {system_settings['role']}! "
                f"Моя цель: {system_settings['goal']}. Чем могу помочь? 😄",
                reply_markup=main_keyboard
            )
            return

        elif query == "помощь":
            instruction_keyboard = get_instruction_keyboard()
            main_keyboard = get_main_keyboard()
            await typing_message.edit_text(
                "Чтобы подробнее разобраться в функционале, откройте инструкцию.",
                reply_markup=instruction_keyboard
            )
            await message.reply("Выберите действие:", reply_markup=main_keyboard)
            return

        # Добавляем сообщение в контекст
        user_id = message.from_user.id
        if user_id not in dialog_context:
            dialog_context[user_id] = []
        dialog_context[user_id].append({"role": "user", "content": query})

        # Проверяем простые диалоги (частичное совпадение)
        for key, response in simple_dialogs.items():
            if key in query:  # Проверяем, содержится ли ключ в запросе
                reaction_keyboard = get_reaction_keyboard(message.message_id)
                await typing_message.edit_text(response, reply_markup=reaction_keyboard)
                dialog_context[user_id].append({"role": "assistant", "content": response})
                return

        # Передаём запрос в process_message
        try:
            response = await process_message(query)
            reaction_keyboard = get_reaction_keyboard(message.message_id)
            message_parts = split_message(response)
            for i, part in enumerate(message_parts):
                if i == 0:
                    await typing_message.edit_text(part, reply_markup=reaction_keyboard)
                else:
                    await message.reply(part)
            dialog_context[user_id].append({"role": "assistant", "content": response})
            if len(dialog_context[user_id]) > 10:
                dialog_context[user_id] = dialog_context[user_id][-10:]
        except Exception as e:
            logger.error(f"Ошибка обработки запроса: {e}")
            await typing_message.edit_text("Произошла ошибка. Пожалуйста, уточните запрос или переформулируйте вопрос. 😔")

    @dp.callback_query(lambda c: c.data.startswith("reaction_"))
    async def handle_reaction(callback: types.CallbackQuery):
        reaction, message_id = callback.data.split("_")[1], callback.data.split("_")[2]
        user_id = callback.from_user.id
        feedback_logger.info(f"Пользователь {user_id} оценил сообщение {message_id}: {reaction}")
        await callback.message.edit_text(f"{callback.message.text}\n\nСпасибо за ваш отзыв! 😊")
        await callback.answer()

    @dp.callback_query()
    async def handle_callback(callback: types.CallbackQuery):
        logger.info(f"Получен callback от {callback.from_user.id}: {callback.data}")
        if callback.data == "instruction":
            main_keyboard = get_main_keyboard()
            await callback.message.edit_text(
                "Инструкция по использованию бота:\n"
                "1. В личных чатах задавайте любые вопросы.\n"
                "2. В группах используйте слово 'Зелёный'.\n"
                "3. Подпишитесь на нашу закрытую группу для полного доступа.",
                reply_markup=None
            )
        await callback.answer()

    logger.info("Обработчики успешно зарегистрированы")