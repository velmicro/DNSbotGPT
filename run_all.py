import subprocess
import sys
import os
import time
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/run_all.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Убедимся, что мы используем виртуальную среду
venv_python = os.path.join("venv", "Scripts", "python.exe")

# Функция для проверки изменений в prompts.json
last_modified_time = 0

def check_prompts_changed():
    global last_modified_time
    try:
        current_modified_time = os.path.getmtime("prompts.json")
        if current_modified_time != last_modified_time:
            last_modified_time = current_modified_time
            return True
        return False
    except Exception as e:
        logger.error(f"Ошибка проверки prompts.json: {e}")
        return False

# Запускаем admin_panel.py
admin_process = subprocess.Popen(
    [venv_python, "admin_panel.py"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)

# Запускаем bot.py
bot_process = None

def start_bot():
    global bot_process
    bot_process = subprocess.Popen(
        [venv_python, "bot.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    logger.info("Bot запущен")

# Запускаем бота в первый раз
start_bot()

# Выводим логи и проверяем изменения
print("Запущены admin_panel.py и bot.py. Логи:")
while True:
    # Читаем и выводим логи admin_panel.py
    admin_line = admin_process.stdout.readline()
    if admin_line:
        print(f"[Admin Panel] {admin_line.strip()}")

    # Читаем и выводим логи bot.py
    bot_line = bot_process.stdout.readline()
    if bot_line:
        print(f"[Bot] {bot_line.strip()}")

    # Проверяем изменения в prompts.json
    if check_prompts_changed():
        logger.info("Обнаружены изменения в prompts.json. Перезапускаем bot.py...")
        bot_process.terminate()  # Завершаем текущий процесс бота
        time.sleep(1)  # Даём время на завершение
        start_bot()  # Перезапускаем бота

    time.sleep(0.1)  # Небольшая задержка, чтобы не нагружать систему