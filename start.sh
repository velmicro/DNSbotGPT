#!/bin/bash

# Перейти в папку проекта
cd /home/velmicro/DNSbotGPT

# Активировать виртуальное окружение
source venv/bin/activate

# Загрузить переменные окружения из .env, если есть
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Запустить бота
python bot.py