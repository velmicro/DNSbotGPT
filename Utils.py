from groq import AsyncGroq
import logging
import re
import aiohttp
from bs4 import BeautifulSoup
import json
import os
from Config import GROQ_API_KEY
from Google_sheets import get_relevant_entries, parse_and_add_to_sheet
from Prompts import load_prompts
from ai_models import AIModel

ai_model = AIModel()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/utils.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Путь к кэшу для результатов поиска
SEARCH_CACHE_DIR = "search_cache"
SEARCH_CACHE_FILE = os.path.join(SEARCH_CACHE_DIR, "search_results.json")

if not os.path.exists(SEARCH_CACHE_DIR):
    os.makedirs(SEARCH_CACHE_DIR)

def load_search_cache() -> dict:
    try:
        if os.path.exists(SEARCH_CACHE_FILE):
            with open(SEARCH_CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f"Ошибка загрузки кэша поиска: {e}")
        return {}

def save_search_cache(cache: dict):
    try:
        with open(SEARCH_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Ошибка сохранения кэша поиска: {e}")

def is_russian_text(text: str) -> bool:
    """
    Проверяет, что текст состоит преимущественно из русских символов.
    Допускает смайлики, латинские буквы в названиях (например, 'iPhone 15 Pro') и знаки препинания.
    """
    russian_chars = sum(1 for char in text if 'а' <= char.lower() <= 'я' or char.lower() == 'ё')
    total_chars = sum(1 for char in text if char.isalpha())
    if total_chars == 0:
        return True
    russian_ratio = russian_chars / total_chars
    return russian_ratio >= 0.5

def determine_response_template(query: str) -> str:
    """
    Определяет, какой шаблон использовать для ответа на основе запроса.
    Используется только для выбора смайлика.
    """
    query_lower = query.lower()
    
    if any(keyword in query_lower for keyword in ["как ", "шаги", "инструкция", "процесс", "оформить", "сделать", "настройка", "сборка"]):
        return "template_1"  # Инструкции
    elif any(keyword in query_lower for keyword in ["плюсы", "минусы", "характеристики", "особенности", "преимущества", "недостатки"]):
        return "template_2"  # Характеристики
    elif any(keyword in query_lower for keyword in ["закон", "право", "зозпп", "гк рф", "вернуть деньги", "возврат", "обмен", "гарантия", "гарантийный", "заменить", "требует замены", "проверка качества"]):
        return "template_legal"  # Юридическая информация
    elif any(keyword in query_lower for keyword in ["диагностика", "неисправность", "ремонт"]):
        return "template_diagnostic"  # Диагностика
    elif any(keyword in query_lower for keyword in ["сравни", "сравнение"]):
        return "template_comparison"  # Сравнение
    elif any(keyword in query_lower for keyword in ["dns", "товар"]):
        return "template_product"  # Информация о товаре
    else:
        return "template_3"  # Общий запрос

def clean_response(response: str, query: str) -> str:
    """
    Упрощённая очистка ответа: удаляет только явное дублирование запроса.
    Сохраняет все переносы строки.
    """
    query_lower = query.lower().strip()
    response_lines = response.split("\n")
    cleaned_lines = []
    
    for line in response_lines:
        line_lower = line.lower().strip()
        # Пропускаем строку, если она почти идентична запросу
        if line_lower == query_lower:
            continue
        cleaned_lines.append(line)
    
    return "\n".join(cleaned_lines).strip()

async def format_response(response: str, template: str, query: str) -> str:
    """
    Форматирует ответ, добавляя смайлик в начало и гарантируя наличие отступов.
    Модель должна формировать ответ в формате: <b>Заголовок</b>\n\nТекст\n\n<i>Примечание</i>
    Если отступы отсутствуют, добавляем их сами.
    """
    # Загружаем смайлики из Prompts.py
    prompts_data = load_prompts()
    emojis = prompts_data["emojis"]

    # Определяем смайлик в зависимости от шаблона
    emoji = emojis.get({
        "template_1": "instruction",
        "template_2": "characteristics",
        "template_legal": "legal",
        "template_diagnostic": "diagnostic",
        "template_comparison": "comparison",
        "template_product": "product",
        "template_3": "default"
    }.get(template, "default"))

    # Очищаем ответ от дублирования запроса
    cleaned_response = clean_response(response, query)
    if not cleaned_response:
        return f"{emojis['error']} <b>Ошибка обработки</b>\n\nНе удалось сформировать ответ.\n\n<i>Попробуй переформулировать запрос.</i>"

    # Разбиваем ответ на части
    lines = cleaned_response.split("\n")
    formatted_lines = []
    in_header = False
    in_note = False
    header = ""
    body = []
    note = ""

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("<b>"):
            in_header = True
            header = line
        elif line.startswith("<i>"):
            in_note = True
            note = line
        elif in_header and not in_note:
            body.append(line)
        elif in_note:
            note += "\n" + line

    # Формируем итоговый ответ с гарантированными отступами
    formatted_response = header
    if body:
        formatted_response += "\n\n" + "\n".join(body)
    if note:
        formatted_response += "\n\n" + note
    else:
        # Добавляем примечание, если его нет
        if template == "template_legal":
            formatted_response += "\n\n<i>Для точной информации обратитесь к юристу.</i>"
        elif template == "template_diagnostic":
            formatted_response += "\n\n<i>Если проблема не решена, уточните детали.</i>"
        elif template == "template_product":
            formatted_response += "\n\n<i>Для получения дополнительной информации уточните запрос.</i>"
        else:
            formatted_response += "\n\n<i>Если у вас есть вопросы, уточните детали.</i>"

    # Добавляем смайлик в начало
    final_response = f"{emoji} {formatted_response}"
    return final_response

async def search_on_site(query: str, site: str) -> str:
    """
    Выполняет поиск на указанном сайте и возвращает результаты.
    """
    search_cache = load_search_cache()
    cache_key = f"{site}:{query}"
    if cache_key in search_cache:
        logger.info(f"Результаты поиска для {cache_key} найдены в кэше")
        return search_cache[cache_key]

    try:
        if site == "consultant.ru":
            search_url = f"https://www.consultant.ru/search/?q={query}"
            async with aiohttp.ClientSession() as session:
                async with session.get(search_url) as response:
                    if response.status != 200:
                        logger.error(f"Ошибка при запросе к {site}: статус {response.status}")
                        return f"Не удалось выполнить поиск на сайте {site}."
                    html = await response.text()
            soup = BeautifulSoup(html, 'html.parser')
            results = soup.find_all('div', class_='search-result-item', limit=3)
            if not results:
                logger.info(f"Не найдено информации по запросу '{query}' на сайте {site}")
                return f"Не найдено информации по запросу '{query}' на сайте {site}."
            result_text = f"Результаты поиска на {site}:\n\n"
            for i, result in enumerate(results, 1):
                title = result.find('a', class_='search-result-item__title')
                description = result.find('div', class_='search-result-item__description')
                title_text = title.get_text(strip=True) if title else "Без заголовка"
                desc_text = description.get_text(strip=True) if description else "Без описания"
                result_text += f"{title_text}\n{desc_text}\n\n"
            search_cache[cache_key] = result_text
            save_search_cache(search_cache)
            logger.info(f"Сохранены результаты поиска для {cache_key}")
            return result_text

        elif site == "dns-shop.ru":
            search_url = f"https://www.google.com/search?q=site:dns-shop.ru+{query}"
            async with aiohttp.ClientSession() as session:
                async with session.get(search_url) as response:
                    if response.status != 200:
                        logger.error(f"Ошибка при запросе к Google для {site}: статус {response.status}")
                        return f"Не удалось выполнить поиск для {site}."
                    html = await response.text()
            soup = BeautifulSoup(html, 'html.parser')
            results = soup.find_all('div', class_='g', limit=3)
            if not results:
                logger.info(f"Не найдено информации по запросу '{query}' для {site}")
                return f"Не найдено информации по запросу '{query}' для {site}."
            result_text = f"Результаты поиска для {site}:\n\n"
            for i, result in enumerate(results, 1):
                title = result.find('h3')
                description = result.find('div', class_='VwiC3b')
                title_text = title.get_text(strip=True) if title else "Без заголовка"
                desc_text = description.get_text(strip=True) if description else "Без описания"
                result_text += f"{title_text}\n{desc_text}\n\n"
            search_cache[cache_key] = result_text
            save_search_cache(search_cache)
            logger.info(f"Сохранены результаты поиска для {cache_key}")
            return result_text

        else:
            logger.warning(f"Поиск на сайте {site} не поддерживается")
            return f"Поиск на сайте {site} не поддерживается."
    except Exception as e:
        logger.error(f"Ошибка при поиске на сайте {site}: {e}")
        return f"Произошла ошибка при поиске на сайте {site}."

async def process_message(user_input: str) -> str:
    """Обрабатывает сообщение пользователя и возвращает ответ."""
    prompts = load_prompts()
    dialogs = prompts.get("dialogs", {})
    user_input_lower = user_input.lower().strip()
    if user_input_lower in dialogs:
        return dialogs[user_input_lower]

    # Получаем релевантные записи из базы знаний
    knowledge_text = await get_relevant_entries(user_input)
    if knowledge_text and "Не нашёл" not in knowledge_text and "ошибка" not in knowledge_text:
        user_input = f"{user_input}\n\nРелевантные записи из базы знаний:\n{knowledge_text}"

    # Проверяем, нужно ли искать информацию на сайте
    search_instructions = prompts.get("search_instructions", [])
    for instruction in search_instructions:
        theme = instruction["theme"]
        site = instruction["site"]
        if theme in user_input_lower:
            site_response = await search_on_site(user_input, site)
            if site_response and "Не найдено" not in site_response and "ошибка" not in site_response:
                user_input = f"{user_input}\n\nИнформация с сайта {site}:\n{site_response}"
            break

    # Используем AI-модель
    response = await ai_model.generate_response(user_input)
    
    # Форматируем ответ
    template = determine_response_template(user_input)
    formatted_response = await format_response(response, template, user_input)
    return formatted_response

def split_message(message: str, max_length: int = 4096) -> list:
    """
    Разбивает длинное сообщение на части, чтобы уложиться в лимит Telegram.
    """
    if len(message) <= max_length:
        return [message]

    parts = []
    current_part = ""
    for line in message.split("\n"):
        if len(current_part) + len(line) + 1 <= max_length:
            current_part += line + "\n"
        else:
            if current_part:
                parts.append(current_part.strip())
            current_part = line + "\n"
    if current_part:
        parts.append(current_part.strip())
    return parts