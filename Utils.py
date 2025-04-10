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

async def get_groq_response(query: str, context: list = None, is_group: bool = False) -> str:
    """
    Получает ответ от Groq API с учётом контекста диалога.
    Модель формирует ответ в формате: <b>Заголовок</b>\n\nТекст\n\n<i>Примечание</i>
    """
    if context is None:
        context = []

    # Загружаем системные настройки
    prompts_data = load_prompts()
    system_settings = prompts_data["settings"]
    search_instructions = prompts_data["search_instructions"]
    emojis = prompts_data["emojis"]

    # Формируем системный промпт
    system_prompt = (
        f"Ты {system_settings['name']}, {system_settings['role']}. "
        f"Твоя цель: {system_settings['goal']}. "
        "Поведение:\n" + "\n".join([f"- {rule}" for rule in system_settings["behavior"]]) + "\n"
        "Ограничения:\n" + "\n".join([f"- {rule}" for rule in system_settings["restrictions"]]) + "\n"
        "Дополнительные инструкции:\n"
        "- Всегда отвечай только на русском языке.\n"
        "- Используй кодировку UTF-8.\n"
        "- Исключай любую информацию о погоде.\n"
        "- Если запрос связан с юридической информацией, используй данные из предоставленной информации с consultant.ru.\n"
        "- Если запрос связан с товарами DNS, используй данные из предоставленной информации с dns-shop.ru.\n"
        "- Если запрос связан с диагностикой техники или выполнением услуг, предоставляй пошаговые инструкции.\n"
        "- Если информация отсутствует в базе знаний или на сайтах, используй свои знания для ответа.\n"
        "- Не используй смайлики в ответе, они будут добавлены позже.\n"
        "- Формируй ответ в следующем формате:\n"
        "  <b>Заголовок</b>\n\n"
        "  Основной текст ответа\n\n"
        "  <i>Примечание</i>\n"
        "- Заголовок должен быть кратким (до 5 слов) и отражать суть запроса.\n"
        "- Между заголовком и основным текстом, а также между основным текстом и примечанием должно быть ровно два переноса строки (\\n\\n).\n"
        "- Основной текст ответа должен быть в одном из следующих форматов, в зависимости от типа запроса:\n"
        "  - Для инструкций или диагностики: пошаговый список (1. Текст, 2. Текст, ...).\n"
        "  - Для характеристик: маркированный список (- Текст, - Текст, ...).\n"
        "  - Для юридической информации, сравнений, информации о товаре или общих запросов: простой текст.\n"
        "- Примечание должно быть кратким (1-2 предложения) и содержать дополнительную информацию или совет, основанный на базе знаний, данных с сайтов или твоих знаниях.\n"
        "- Если предоставлены данные из базы знаний или с сайтов, обязательно используй их для формирования ответа.\n"
    )

    # Получаем релевантные записи из базы знаний
    knowledge_text = await get_relevant_entries(query)
    logger.info(f"Данные из Google Sheets: {knowledge_text}")
    if knowledge_text and "Не нашёл" not in knowledge_text and "ошибка" not in knowledge_text:
        system_prompt += f"\n\nРелевантные записи из базы знаний:\n{knowledge_text}"
    elif "ошибка" in knowledge_text.lower():
        logger.error(f"Ошибка при получении данных из Google Sheets: {knowledge_text}")
        return f"{emojis['error']} <b>Ошибка базы знаний</b>\n\n{knowledge_text}\n\n<i>Попробуй позже или уточни запрос.</i>"

    # Проверяем, нужно ли искать информацию на сайте
    site_response = None
    logger.info(f"Инструкции для поиска: {search_instructions}")
    for instruction in search_instructions:
        theme = instruction["theme"]
        site = instruction["site"]
        if theme in query.lower():
            logger.info(f"Найдена тема '{theme}' для сайта {site}, выполняем поиск...")
            site_response = await search_on_site(query, site)
            logger.info(f"Результат поиска на сайте {site}: {site_response}")
            if site_response and "Не найдено" not in site_response and "ошибка" not in site_response:
                system_prompt += f"\n\nИнформация с сайта {site}:\n{site_response}"
            break

    # Формируем сообщения для Groq
    messages = [
        {"role": "system", "content": system_prompt},
    ] + context + [
        {"role": "user", "content": query}
    ]

    try:
        logger.info("Отправка запроса к Groq API...")
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": messages,
                    "max_tokens": 1000,
                    "temperature": 0.7
                }
            ) as response:
                logger.info(f"Статус ответа от Groq API: {response.status}")
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Ошибка Groq API: статус {response.status}, ответ: {error_text}")
                    return f"{emojis['error']} <b>Ошибка API</b>\n\nПроизошла ошибка при получении ответа.\n\n<i>Попробуй уточнить запрос!</i>"

                data = await response.json()
                logger.info(f"Ответ от Groq API: {data}")
                if "choices" not in data or not data["choices"]:
                    logger.error(f"Ответ Groq API не содержит 'choices': {data}")
                    return f"{emojis['error']} <b>Ошибка ответа</b>\n\nНе удалось получить ответ от Groq.\n\n<i>Попробуй позже!</i>"

                response_text = data["choices"][0]["message"]["content"].strip()

                # Проверяем, что ответ на русском языке
                if not is_russian_text(response_text):
                    logger.warning(f"Ответ содержит не русские символы: {response_text}")
                    return f"{emojis['error']} <b>Ошибка языка</b>\n\nОтвет содержит символы не на русском языке.\n\n<i>Попробуй переформулировать запрос!</i>"

                # Форматируем ответ
                template = determine_response_template(query)
                formatted_response = await format_response(response_text, template, query)
                return formatted_response
    except Exception as e:
        logger.error(f"Ошибка при запросе к Groq API: {e}")
        return f"{emojis['error']} <b>Ошибка обработки</b>\n\nНе смог найти точный ответ.\n\n<i>Попробуй уточнить запрос или переформулировать вопрос.</i>"

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