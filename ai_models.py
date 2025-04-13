import logging
from groq import Groq
from Prompts import load_prompts

logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.FileHandler("logs/ai_models.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class AIModel:
    def __init__(self):
        self.load_settings()
        self.client = None
        if self.use_ai:
            self._initialize_client()

    def load_settings(self):
        """Загружает настройки из prompts.json."""
        self.prompts = load_prompts()
        self.use_ai = self.prompts["settings"].get("use_ai", True)
        self.current_model = self.prompts["settings"].get("model", "llama3-8b-8192")  # Модель по умолчанию
        self.model_config = self.prompts["settings"].get("model_config", {})

    def _initialize_client(self):
        """Инициализирует клиент для Groq."""
        api_key = self.model_config["grok"]["api_key"]
        if api_key:
            self.client = Groq(api_key=api_key)
        else:
            logger.warning("API-ключ для Groq не указан.")
            self.client = None

    async def generate_response(self, user_input: str) -> str:
        """Генерирует ответ от модели Groq."""
        self.load_settings()
        if not self.use_ai:
            return "AI отключено."
        if not self.client:
            return "API-ключ для Groq отсутствует. Пожалуйста, добавьте ключ через админ-панель."

        # Список поддерживаемых моделей Groq
        supported_models = [
            "gemma-2-9b-it",
            "llama-3-70b-versatile",
            "llama-3-1-8b-instant",
            "llama-guard-3-8b",
            "llama3-70b-8192",
            "llama3-8b-8192"
        ]

        if self.current_model not in supported_models:
            logger.error(f"Модель {self.current_model} не поддерживается Groq. Используется модель по умолчанию: llama3-8b-8192")
            self.current_model = "llama3-8b-8192"

        try:
            system_prompt = (
                f"Ты {self.prompts['settings']['name']}, {self.prompts['settings']['role']}. "
                f"Твоя цель: {self.prompts['settings']['goal']}. "
                "Поведение:\n" + "\n".join([f"- {rule}" for rule in self.prompts['settings']['behavior']]) + "\n"
                "Ограничения:\n" + "\n".join([f"- {rule}" for rule in self.prompts['settings']['restrictions']]) + "\n"
                "Дополнительные инструкции:\n"
                "- Всегда отвечай только на русском языке.\n"
                "- Используй кодировку UTF-8.\n"
                "- Исключай любую информацию о погоде.\n"
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
                "- Примечание должно быть кратким (1-2 предложения) и содержать дополнительную информацию или совет.\n"
            )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ]

            response = self.client.chat.completions.create(
                model=self.current_model,
                messages=messages,
                max_tokens=1000,
                temperature=0.7
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Ошибка генерации ответа от {self.current_model}: {e}")
            return "Произошла ошибка при обращении к модели Groq. Проверьте API-ключ или повторите позже."