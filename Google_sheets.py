import logging
from typing import List, Dict, Any
import json
import os
import faiss
import numpy as np
import gspread
from google.oauth2.service_account import Credentials
from sentence_transformers import SentenceTransformer
from Config import GOOGLE_CREDENTIALS_PATH, SPREADSHEET_ID
import re
import requests
from bs4 import BeautifulSoup


# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/corrections.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Инициализация модели для векторизации текста
logger.info("Инициализация модели SentenceTransformer...")
model = SentenceTransformer('all-MiniLM-L6-v2')
logger.info("Модель SentenceTransformer успешно загружена")

# Глобальные переменные для хранения базы знаний
knowledge_base: List[Dict[str, Any]] = []
vector_index: faiss.IndexFlatL2 = None
questions: List[str] = []

# Путь к файлам кеша
CACHE_DIR = "cache"
KNOWLEDGE_BASE_CACHE = os.path.join(CACHE_DIR, "knowledge_base.json")
QUESTIONS_CACHE = os.path.join(CACHE_DIR, "questions.json")
INDEX_CACHE = os.path.join(CACHE_DIR, "vector_index.bin")
TIMESTAMP_CACHE = os.path.join(CACHE_DIR, "last_modified.txt")

if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

# Список стоп-слов (общие слова, которые не несут смысла для поиска)
STOP_WORDS = {'и', 'в', 'на', 'с', 'по', 'у', 'как', 'все', 'а', 'для', 'то', 'что', 'это', 'не', 'или', 'если'}

def init_google_sheets():
    """
    Инициализирует подключение к Google Sheets.
    Возвращает объект gspread.Spreadsheet или None в случае ошибки.
    """
    try:
        creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH")
        spreadsheet_id = os.getenv("SPREADSHEET_ID")
        if not creds_path or not spreadsheet_id:
            logger.error("GOOGLE_CREDENTIALS_PATH или SPREADSHEET_ID не указаны в .env")
            return None

        creds = Credentials.from_service_account_file(creds_path, scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ])
        client = gspread.authorize(creds)
        sheet = client.open_by_key(spreadsheet_id)
        logger.info("Успешное подключение к Google Sheets")
        return sheet
    except Exception as e:
        logger.error(f"Ошибка подключения к Google Sheets: {e}")
        return None

def save_cache(knowledge_base: List[Dict[str, Any]], questions: List[str], vector_index: faiss.IndexFlatL2, last_modified: str):
    try:
        with open(KNOWLEDGE_BASE_CACHE, 'w', encoding='utf-8') as f:
            json.dump(knowledge_base, f, ensure_ascii=False, indent=4)
        with open(QUESTIONS_CACHE, 'w', encoding='utf-8') as f:
            json.dump(questions, f, ensure_ascii=False, indent=4)
        faiss.write_index(vector_index, INDEX_CACHE)
        with open(TIMESTAMP_CACHE, 'w', encoding='utf-8') as f:
            f.write(last_modified)
        logger.info("Кеш успешно сохранён")
    except Exception as e:
        logger.error(f"Ошибка сохранения кеша: {e}")

def load_cache() -> tuple[List[Dict[str, Any]], faiss.IndexFlatL2, List[str], str]:
    try:
        if not all(os.path.exists(path) for path in [KNOWLEDGE_BASE_CACHE, QUESTIONS_CACHE, INDEX_CACHE, TIMESTAMP_CACHE]):
            logger.info("Файлы кеша отсутствуют")
            return [], None, [], ""
        with open(KNOWLEDGE_BASE_CACHE, 'r', encoding='utf-8') as f:
            knowledge_base = json.load(f)
        with open(QUESTIONS_CACHE, 'r', encoding='utf-8') as f:
            questions = json.load(f)
        vector_index = faiss.read_index(INDEX_CACHE)
        with open(TIMESTAMP_CACHE, 'r', encoding='utf-8') as f:
            last_modified = f.read().strip()
        logger.info("Кеш успешно загружен")
        return knowledge_base, vector_index, questions, last_modified
    except Exception as e:
        logger.error(f"Ошибка загрузки кеша: {e}")
        return [], None, [], ""

def load_knowledge_base() -> tuple[List[Dict[str, Any]], faiss.IndexFlatL2, List[str]]:
    """
    Загружает базу знаний из Google Sheets.
    """
    global knowledge_base, vector_index, questions

    sheet = init_google_sheets()
    if not sheet:
        logger.error("Не удалось загрузить базу знаний")
        return [], None, []

    try:
        logger.info("Загрузка данных из Google Sheets...")
        data = sheet.sheet1.get_all_records()
        logger.info(f"Загружено записей: {len(data)}")
        if not data:
            logger.warning("Google Sheets пуст")
            return [], None, []

        # Преобразуем Keywords в строки при загрузке
        for entry in data:
            if "Keywords" in entry:
                entry["Keywords"] = str(entry["Keywords"])  # Принудительно преобразуем в строку

        knowledge_base = data
        questions = [row["Question"] for row in data if "Question" in row and row["Question"]]
        logger.info(f"Количество вопросов для векторизации: {len(questions)}")
        if not questions:
            logger.warning("Вопросы в базе знаний отсутствуют")
            return knowledge_base, None, []

        # Векторизация вопросов
        logger.info("Векторизация вопросов...")
        question_embeddings = model.encode(questions, show_progress_bar=True)
        dimension = question_embeddings.shape[1]
        vector_index = faiss.IndexFlatL2(dimension)
        vector_index.add(np.array(question_embeddings, dtype=np.float32))
        logger.info("Векторизация завершена")

        # Сохранение кеша
        sheet_metadata = sheet.fetch_sheet_metadata()
        last_modified = sheet_metadata.get('properties', {}).get('modifiedTime', '')
        save_cache(knowledge_base, questions, vector_index, last_modified)
        return knowledge_base, vector_index, questions
    except Exception as e:
        logger.error(f"Ошибка загрузки базы знаний: {e}")
        raise

async def initialize_knowledge_base():
    """
    Асинхронно инициализирует базу знаний.
    """
    logger.info("Инициализация базы знаний...")
    global knowledge_base, vector_index, questions
    knowledge_base, vector_index, questions = load_knowledge_base()
    logger.info(f"База знаний инициализирована: {len(knowledge_base)} записей, {len(questions)} вопросов")

async def get_relevant_entries(query: str) -> str:
    """
    Возвращает наиболее релевантные записи из базы знаний на основе ключевых слов, вопросов и ответов.
    """
    global knowledge_base, vector_index, questions

    logger.info(f"Проверка состояния базы знаний перед поиском: knowledge_base={len(knowledge_base)} записей, questions={len(questions)} вопросов, vector_index={'загружен' if vector_index is not None else 'не загружен'}")

    if not knowledge_base or vector_index is None or not questions:
        logger.warning("База знаний не загружена, выполняется загрузка...")
        loaded_knowledge_base, loaded_vector_index, loaded_questions = load_knowledge_base()
        if not loaded_knowledge_base or loaded_vector_index is None or not loaded_questions:
            logger.error("Не удалось загрузить базу знаний")
            return "База знаний недоступна. Попробуй позже! 😔"
        knowledge_base, vector_index, questions = loaded_knowledge_base, loaded_vector_index, loaded_questions
        logger.info(f"База знаний загружена: {len(knowledge_base)} записей, {len(questions)} вопросов")

    try:
        # Предобработка запроса
        query_lower = re.sub(r'[^\w\s]', '', query.lower()).strip()
        query_words = set(query_lower.split()) - STOP_WORDS  # Удаляем стоп-слова
        logger.info(f"Предобработанный запрос: {query_lower}, слова: {query_words}")

        # Поиск по ключевым словам, вопросам и ответам
        relevant_entries = []
        for idx, entry in enumerate(knowledge_base):
            question = entry.get("Question", "Вопрос отсутствует")
            answer = entry.get("Answer", "Ответ отсутствует")

            # Обрабатываем Keywords
            keywords_raw = entry.get("Keywords", "")
            if not isinstance(keywords_raw, str):
                logger.warning(f"Некорректный тип данных для Keywords в записи {idx}: {keywords_raw} (тип: {type(keywords_raw)}). Преобразуем в строку.")
                keywords_raw = str(keywords_raw)
            keywords = keywords_raw.lower().split(",")
            keywords = [kw.strip() for kw in keywords if kw.strip()]
            keywords_set = set(keywords) - STOP_WORDS

            # Обрабатываем Question
            question_lower = re.sub(r'[^\w\s]', '', question.lower()).strip()
            question_words = set(question_lower.split()) - STOP_WORDS

            # Обрабатываем Answer
            answer_lower = re.sub(r'[^\w\s]', '', answer.lower()).strip()
            answer_words = set(answer_lower.split()) - STOP_WORDS

            # Проверяем совпадения
            matched_keywords = [kw for kw in keywords_set if kw in query_words]
            matched_question_words = [word for word in question_words if word in query_words]
            matched_answer_words = [word for word in answer_words if word in query_words]

            # Рассчитываем релевантность
            # Даём разный вес совпадениям: Keywords - 1.0, Question - 0.8, Answer - 0.6
            keyword_score = len(matched_keywords) / (len(keywords_set) if keywords_set else 1) * 1.0
            question_score = len(matched_question_words) / (len(question_words) if question_words else 1) * 0.8
            answer_score = len(matched_answer_words) / (len(answer_words) if answer_words else 1) * 0.6
            total_score = keyword_score + question_score + answer_score

            # Устанавливаем порог релевантности
            RELEVANCE_THRESHOLD = 0.5
            if total_score < RELEVANCE_THRESHOLD:
                continue

            # Если есть совпадения, добавляем запись
            if matched_keywords or matched_question_words or matched_answer_words:
                # Обрезаем ответ до 1000 символов
                if len(answer) > 1000:
                    answer = answer[:1000] + "..."
                relevant_entries.append({
                    "question": question,
                    "answer": answer,
                    "matched_keywords": matched_keywords,
                    "matched_question_words": matched_question_words,
                    "matched_answer_words": matched_answer_words,
                    "score": total_score
                })
                logger.info(
                    f"Найдена запись: Вопрос: {question}, "
                    f"Совпавшие ключевые слова: {matched_keywords}, "
                    f"Совпавшие слова в вопросе: {matched_question_words}, "
                    f"Совпавшие слова в ответе: {matched_answer_words}, "
                    f"Общая оценка: {total_score:.2f}"
                )

        # Сортируем записи по релевантности
        relevant_entries = sorted(relevant_entries, key=lambda x: x["score"], reverse=True)

        # Если ничего не найдено, используем векторизацию
        if not relevant_entries:
            logger.info("Совпадений по словам не найдено, переходим к векторизации")
            query_embedding = model.encode([query])[0]
            query_embedding = np.array([query_embedding], dtype=np.float32)

            # Поиск ближайших записей (топ-3)
            distances, indices = vector_index.search(query_embedding, 3)

            VECTOR_RELEVANCE_THRESHOLD = 0.1  # Снижаем порог для векторизации
            for idx, distance in zip(indices[0], distances[0]):
                if idx >= len(knowledge_base):
                    logger.warning(f"Индекс {idx} вне диапазона knowledge_base (длина: {len(knowledge_base)})")
                    continue
                entry = knowledge_base[idx]
                question = entry.get("Question", "Вопрос отсутствует")
                answer = entry.get("Answer", "Ответ отсутствует")
                keywords_raw = entry.get("Keywords", "")
                if not isinstance(keywords_raw, str):
                    logger.warning(f"Некорректный тип данных для Keywords в записи {idx} (векторизация): {keywords_raw} (тип: {type(keywords_raw)}). Преобразуем в строку.")
                    keywords_raw = str(keywords_raw)
                keywords = keywords_raw.lower()

                # Проверяем релевантность по расстоянию
                if distance > VECTOR_RELEVANCE_THRESHOLD:
                    logger.info(f"Запись отклонена (векторизация): Вопрос: {question}, Расстояние: {distance}")
                    continue

                # Обрезаем ответ до 1000 символов
                if len(answer) > 1000:
                    answer = answer[:1000] + "..."
                
                relevant_entries.append({
                    "question": question,
                    "answer": answer,
                    "matched_keywords": [],
                    "matched_question_words": [],
                    "matched_answer_words": [],
                    "score": 1 - distance  # Оценка релевантности на основе расстояния
                })
                logger.info(f"Найдена запись по векторизации: Вопрос: {question}, Ответ: {answer}, Расстояние: {distance}")

        # Формируем результат
        if not relevant_entries:
            logger.warning("Релевантные записи не найдены")
            return "Не нашёл подходящих записей в базе знаний. Попробуй переформулировать вопрос! 😅"

        # Берём топ-3 записи (или меньше, если найдено меньше)
        result = ""
        for i, entry in enumerate(relevant_entries[:3]):
            result += f"Запись {i+1}:\nВопрос: {entry['question']}\nОтвет: {entry['answer']}\n\n"
        logger.info(f"Передаём в Groq следующие данные из базы знаний:\n{result}")
        return result
    except Exception as e:
        logger.error(f"Ошибка при поиске релевантных записей: {e}")
        return "Произошла ошибка при поиске в базе знаний. Попробуй позже! 😔"

def add_to_knowledge_base(question: str, keywords: str, answer: str):
    """
    Добавляет новую запись в базу знаний в Google Sheets.
    """
    try:
        sheet = init_google_sheets()
        if not sheet:
            logger.error("Не удалось подключиться к Google Sheets для добавления записи")
            return
        
        sheet.sheet1.append_row([question, keywords, answer])
        logger.info(f"Добавлена новая запись: Вопрос: {question}, Ключевые слова: {keywords}")
    except Exception as e:
        logger.error(f"Ошибка добавления записи в базу знаний: {e}")
        raise

    try:
        # Добавляем запись в Google Sheets
        sheet.sheet1.append_row([question, keywords, answer])
        logger.info(f"Новая запись добавлена в Google Sheets: {question}")

        # Обновляем локальную базу знаний и кеш
        global knowledge_base, vector_index, questions
        knowledge_base.append({"Question": question, "Keywords": keywords, "Answer": answer})
        questions.append(question)

        # Обновляем векторный индекс
        new_embedding = model.encode([question])[0]
        vector_index.add(np.array([new_embedding], dtype=np.float32))

        # Сохраняем обновлённый кеш
        sheet_metadata = sheet.fetch_sheet_metadata()
        last_modified = sheet_metadata.get('properties', {}).get('modifiedTime', '')
        save_cache(knowledge_base, questions, vector_index, last_modified)

        logger.info(f"База знаний обновлена: добавлена запись '{question}'")
        return True
    except Exception as e:
        logger.error(f"Ошибка при добавлении записи в базу знаний: {e}")
        return False

async def parse_and_add_to_sheet(url: str) -> bool:
    """
    Парсит указанный сайт, извлекает вопросы, ключевые слова и ответы, и добавляет их в Google Sheets.
    """
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # Ищем заголовки (вопросы) и текст (ответы)
        entries = []
        for header in soup.find_all(['h1', 'h2', 'h3']):
            question = header.get_text(strip=True)
            if not question.endswith('?'):
                question += '?'
            answer = ""
            next_element = header.find_next_sibling()
            while next_element and next_element.name not in ['h1', 'h2', 'h3']:
                if next_element.name == 'p':
                    answer += next_element.get_text(strip=True) + "\n"
                next_element = next_element.find_next_sibling()
            answer = answer.strip()
            if not answer:
                continue
            # Извлекаем ключевые слова из вопроса
            keywords = ",".join(set(re.sub(r'[^\w\s]', '', question.lower()).split()) - STOP_WORDS)[:3]
            entries.append({"question": question, "keywords": keywords, "answer": answer})

        # Добавляем записи в Google Sheets
        for entry in entries:
            success = add_to_knowledge_base(entry["question"], entry["keywords"], entry["answer"])
            if not success:
                logger.error(f"Не удалось добавить запись: {entry['question']}")
                return False

        logger.info(f"Успешно добавлено {len(entries)} записей из сайта {url}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при парсинге сайта {url}: {e}")
        return False