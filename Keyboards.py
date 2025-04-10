from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """
    Создаёт основную клавиатуру с кнопками "Новый диалог", "О боте", "Помощь".
    Возвращает объект ReplyKeyboardMarkup для использования в чате.
    """
    # Создаём список кнопок
    buttons = [
        [KeyboardButton(text="Новый диалог")],
        [KeyboardButton(text="О боте"), KeyboardButton(text="Помощь")]
    ]

    # Передаём список кнопок в параметр keyboard
    keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    return keyboard

def get_reaction_keyboard(message_id: int) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру с кнопками реакции (палец вверх/вниз).
    Принимает message_id для привязки реакции к конкретному сообщению.
    """
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👍", callback_data=f"reaction_up_{message_id}"),
            InlineKeyboardButton(text="👎", callback_data=f"reaction_down_{message_id}")
        ]
    ])
    return keyboard

def get_instruction_keyboard() -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру с кнопкой "Инструкция" для сообщения "Помощь".
    """
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Инструкция", callback_data="instruction")]
    ])
    return keyboard

# Инструкции:
# 1. Этот файл содержит клавиатуры для бота.
# 2. Для добавления новых кнопок в основную клавиатуру добавьте новую строку в список `buttons` в `get_main_keyboard()`.
#    Пример: buttons.append([KeyboardButton(text="Новая кнопка")])
# 3. Реакции (палец вверх/вниз) используются для оценки ответов бота и привязаны к message_id.
# 4. Для добавления новых инлайн-кнопок создайте новую функцию, аналогичную `get_instruction_keyboard()`.
#    Пример:
#    def get_custom_keyboard():
#        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Новая кнопка", callback_data="custom")]])
#        return keyboard