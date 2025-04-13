import asyncio
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required
import sqlite3
import json
import os
from google.oauth2.service_account import Credentials
from gspread_asyncio import AsyncioGspreadClientManager
import logging
from Google_sheets import add_to_knowledge_base, load_knowledge_base, init_google_sheets
from Prompts import load_prompts
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = "your_secret_key"
login_manager = LoginManager(app)
login_manager.login_view = "login"

logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.FileHandler("logs/admin_panel.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

PROMPTS_FILE = "prompts.json"
CONFIG_FILE = ".env"
DB_FILE = "admin.db"

# Инициализация SQLite
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE,
            password TEXT,
            is_admin BOOLEAN,
            is_blocked BOOLEAN DEFAULT 0
        )''')
        hashed_password = generate_password_hash("admin123")
        c.execute("INSERT OR IGNORE INTO users (username, password, is_admin, is_blocked) VALUES (?, ?, ?, ?)",
                  ("admin", hashed_password, True, False))
        conn.commit()

init_db()

class User(UserMixin):
    def __init__(self, id, username, is_admin):
        self.id = id
        self.username = username
        self.is_admin = is_admin

@login_manager.user_loader
def load_user(user_id):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("SELECT id, username, is_admin FROM users WHERE id = ?", (user_id,))
        user = c.fetchone()
        if user:
            return User(user[0], user[1], user[2])
        return None

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute("SELECT id, username, password, is_admin FROM users WHERE username = ?",
                      (username,))
            user = c.fetchone()
            if user and check_password_hash(user[2], password):
                user_obj = User(user[0], user[1], user[3])
                login_user(user_obj)
                return redirect(url_for("dashboard"))
            flash("Неверный логин или пароль")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def dashboard():
    return render_template("dashboard.html")

@app.route("/api-keys", methods=["GET", "POST"])
@login_required
def api_keys():
    if request.method == "POST":
        telegram_token = request.form.get("telegram_token")
        groq_api_key = request.form.get("groq_api_key")
        google_creds = request.form.get("google_creds")
        spreadsheet_id = request.form.get("spreadsheet_id")  # Добавляем поле для SPREADSHEET_ID
        try:
            with open(CONFIG_FILE, "w", encoding='utf-8') as f:
                f.write(f"TELEGRAM_TOKEN={telegram_token}\n")
                f.write(f"GROQ_API_KEY={groq_api_key}\n")
                f.write(f"GOOGLE_CREDENTIALS_PATH={google_creds}\n")
                f.write(f"SPREADSHEET_ID={spreadsheet_id}\n")
            flash("API-ключи обновлены. Перезапустите бота.")
        except Exception as e:
            flash(f"Ошибка сохранения ключей: {str(e)}")
    
    config = {}
    try:
        with open(CONFIG_FILE, encoding='utf-8') as f:
            config = {line.split("=")[0]: line.split("=")[1].strip() for line in f if "=" in line}
    except FileNotFoundError:
        flash("Файл .env не найден. Создайте его или обновите ключи.")
    except Exception as e:
        flash(f"Ошибка чтения .env: {str(e)}")
    
    return render_template("api_keys.html", config=config)

@app.route("/knowledge-base", methods=["GET", "POST"])
@login_required
def knowledge_base():  # Убираем async
    try:
        if request.method == "POST":
            action = request.form.get("action")
            sheet_id = request.form.get("sheet_id")
            if action == "add_sheet":
                with open(CONFIG_FILE, "a", encoding='utf-8') as f:
                    f.write(f"SPREADSHEET_ID={sheet_id}\n")
                flash("Новая база знаний добавлена.")
            elif action == "edit":
                question = request.form.get("question")
                keywords = request.form.get("keywords")
                answer = request.form.get("answer")
                add_to_knowledge_base(question, keywords, answer)  # Убираем await
                flash("Запись добавлена в базу знаний.")
        
        knowledge = load_knowledge_base()  # Убираем await
        logger.info(f"Данные из load_knowledge_base: {knowledge[0]}")
        sheets = [os.getenv("SPREADSHEET_ID")]
        # Проверяем, что knowledge[0] не пуст
        if not knowledge[0]:
            flash("База знаний пуста. Добавьте записи.")
        return render_template("knowledge_base.html", sheets=sheets, knowledge=knowledge[0])
    except Exception as e:
        logger.error(f"Ошибка в маршруте /knowledge-base: {str(e)}")
        flash(f"Произошла ошибка: {str(e)}")
        return redirect(url_for("dashboard"))

@app.route("/delete-knowledge/<int:index>", methods=["POST"])
@login_required
def delete_knowledge(index):  # Убираем async
    try:
        knowledge = load_knowledge_base()  # Убираем await
        if 0 <= index < len(knowledge[0]):
            sheet = init_google_sheets()
            sheet.sheet1.delete_rows(index + 2)  # +2 учитывает заголовок
            flash("Запись удалена.")
        return redirect(url_for("knowledge_base"))
    except Exception as e:
        flash(f"Произошла ошибка: {str(e)}")
        return redirect(url_for("dashboard"))

@app.route("/ai_model", methods=["GET", "POST"])
@login_required
def ai_model():
    prompts = load_prompts()
    settings = prompts["settings"]
    model_config = settings["model_config"]
    current_model = settings.get("model", "llama3-8b-8192")
    use_ai = settings.get("use_ai", True)

    # Список поддерживаемых моделей Groq
    available_models = [
        "gemma-2-9b-it",
        "llama-3-70b-versatile",
        "llama-3-1-8b-instant",
        "llama-guard-3-8b",
        "llama3-70b-8192",
        "llama3-8b-8192"
    ]

    if request.method == "POST":
        action = request.form.get("action")

        if action == "update_model":
            new_model = request.form.get("model")
            if new_model in available_models:
                settings["model"] = new_model
                prompts["settings"] = settings
                save_prompts(prompts)
                flash("Модель обновлена. Перезапустите бота.")
            else:
                flash("Выбранная модель не поддерживается.", "error")

        elif action == "toggle_ai":
            settings["use_ai"] = not use_ai
            prompts["settings"] = settings
            save_prompts(prompts)
            flash("Настройка AI обновлена. Перезапустите бота.")

        elif action == "update_grok_api_key":
            model_config["grok"]["api_key"] = request.form.get("grok_api_key")
            settings["model_config"] = model_config
            prompts["settings"] = settings
            save_prompts(prompts)
            flash("API-ключ для Groq обновлён. Перезапустите бота.")

    return render_template("ai_model.html", model_config=model_config, current_model=current_model, use_ai=use_ai, available_models=available_models)

@app.route("/users", methods=["GET", "POST"])
@login_required
def users():
    if request.method == "POST":
        user_id = request.form.get("user_id")
        action = request.form.get("action")
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            if action == "block":
                c.execute("UPDATE users SET is_blocked = 1 WHERE id = ?", (user_id,))
            elif action == "unblock":
                c.execute("UPDATE users SET is_blocked = 0 WHERE id = ?", (user_id,))
            conn.commit()
            flash(f"Пользователь {user_id} {'заблокирован' if action == 'block' else 'разблокирован'}.")
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("SELECT id, username FROM users WHERE is_blocked = 1")
        blocked_users = c.fetchall()
    return render_template("users.html", blocked_users=blocked_users)

@app.route("/commands", methods=["GET", "POST"])
@login_required
def commands():
    prompts = load_prompts()
    commands = prompts["settings"].get("commands", [])

    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "add":
            name = request.form.get("name")
            response_type = request.form.get("type")
            response = request.form.get("response")
            access = request.form.get("access")

            inline_buttons = []
            if response_type == "inline_buttons":
                for i in range(10):  # До 10 кнопок
                    btn_text = request.form.get(f"btn_text_{i}")
                    btn_url = request.form.get(f"btn_url_{i}")
                    if btn_text and btn_url:
                        inline_buttons.append({"text": btn_text, "url": btn_url})

            new_command = {
                "name": name,
                "type": response_type,
                "response": response,
                "access": access,
                "inline_buttons": inline_buttons
            }
            commands.append(new_command)
            prompts["settings"]["commands"] = commands
            save_prompts(prompts)
            flash("Команда добавлена. Перезапустите бота.")

        elif action == "edit":
            index = int(request.form.get("index"))
            name = request.form.get("name")
            response_type = request.form.get("type")
            response = request.form.get("response")
            access = request.form.get("access")

            inline_buttons = []
            if response_type == "inline_buttons":
                for i in range(10):
                    btn_text = request.form.get(f"btn_text_{i}")
                    btn_url = request.form.get(f"btn_url_{i}")
                    if btn_text and btn_url:
                        inline_buttons.append({"text": btn_text, "url": btn_url})

            commands[index] = {
                "name": name,
                "type": response_type,
                "response": response,
                "access": access,
                "inline_buttons": inline_buttons
            }
            prompts["settings"]["commands"] = commands
            save_prompts(prompts)
            flash("Команда обновлена. Перезапустите бота.")

        elif action == "delete":
            index = int(request.form.get("index"))
            commands.pop(index)
            prompts["settings"]["commands"] = commands
            save_prompts(prompts)
            flash("Команда удалена. Перезапустите бота.")

    return render_template("commands.html", commands=commands)

@app.route("/buttons", methods=["GET", "POST"])
@login_required
def buttons():
    prompts = load_prompts()
    buttons = prompts["settings"].get("buttons", [])
    buttons_per_row = prompts["settings"].get("buttons_per_row", 2)

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            text = request.form.get("text")
            response = request.form.get("response")
            position = len(buttons)  # Новая кнопка добавляется в конец
            buttons.append({"text": text, "response": response, "position": position})
            prompts["settings"]["buttons"] = buttons
            save_prompts(prompts)
            flash("Кнопка добавлена. Перезапустите бота.")

        elif action == "edit":
            index = int(request.form.get("index"))
            text = request.form.get("text")
            response = request.form.get("response")
            position = int(request.form.get("position"))
            buttons[index] = {"text": text, "response": response, "position": position}
            buttons.sort(key=lambda x: x["position"])  # Сортируем по позиции
            prompts["settings"]["buttons"] = buttons
            save_prompts(prompts)
            flash("Кнопка обновлена. Перезапустите бота.")

        elif action == "delete":
            index = int(request.form.get("index"))
            buttons.pop(index)
            # Пересчитываем позиции
            for i, btn in enumerate(buttons):
                btn["position"] = i
            prompts["settings"]["buttons"] = buttons
            save_prompts(prompts)
            flash("Кнопка удалена. Перезапустите бота.")

        elif action == "update_layout":
            buttons_per_row = int(request.form.get("buttons_per_row"))
            prompts["settings"]["buttons_per_row"] = buttons_per_row
            save_prompts(prompts)
            flash("Настройки клавиатуры обновлены. Перезапустите бота.")

    return render_template("buttons.html", buttons=buttons, buttons_per_row=buttons_per_row)

@app.route("/scenarios", methods=["GET", "POST"])
@login_required
def scenarios():
    prompts = load_prompts()
    scenarios = prompts["settings"].get("scenarios", [])

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add_scenario":
            scenario_id = request.form.get("scenario_id")
            scenarios.append({"id": scenario_id, "steps": []})
            prompts["settings"]["scenarios"] = scenarios
            save_prompts(prompts)
            flash("Сценарий добавлен. Перезапустите бота.")

        elif action == "add_step":
            scenario_index = int(request.form.get("scenario_index"))
            step_id = request.form.get("step_id")
            text = request.form.get("text")
            buttons = []
            for i in range(5):  # До 5 кнопок на шаг
                btn_text = request.form.get(f"btn_text_{i}")
                next_step = request.form.get(f"next_step_{i}")
                if btn_text and next_step:
                    buttons.append({"text": btn_text, "next_step": next_step})
            scenarios[scenario_index]["steps"].append({
                "step_id": step_id,
                "text": text,
                "buttons": buttons
            })
            prompts["settings"]["scenarios"] = scenarios
            save_prompts(prompts)
            flash("Шаг добавлен. Перезапустите бота.")

        elif action == "delete_scenario":
            scenario_index = int(request.form.get("scenario_index"))
            scenarios.pop(scenario_index)
            prompts["settings"]["scenarios"] = scenarios
            save_prompts(prompts)
            flash("Сценарий удалён. Перезапустите бота.")

        elif action == "delete_step":
            scenario_index = int(request.form.get("scenario_index"))
            step_index = int(request.form.get("step_index"))
            scenarios[scenario_index]["steps"].pop(step_index)
            prompts["settings"]["scenarios"] = scenarios
            save_prompts(prompts)
            flash("Шаг удалён. Перезапустите бота.")

    return render_template("scenarios.html", scenarios=scenarios)   

@app.route("/prompts", methods=["GET", "POST"])
@login_required
def prompts():
    prompts_data = load_prompts()
    settings = prompts_data["settings"]

    if request.method == "POST":
        action = request.form.get("action")

        if action == "update_settings":
            settings["name"] = request.form.get("name")
            settings["greeting"] = request.form.get("greeting")
            settings["role"] = request.form.get("role")
            settings["goal"] = request.form.get("goal")
            prompts_data["settings"] = settings
            save_prompts(prompts_data)
            flash("Основные настройки обновлены. Перезапустите бота.")

        elif action == "add_behavior":
            new_behavior = request.form.get("new_behavior")
            if new_behavior:
                settings["behavior"].append(new_behavior)
                prompts_data["settings"] = settings
                save_prompts(prompts_data)
                flash("Правило поведения добавлено. Перезапустите бота.")

        elif action == "edit_behavior":
            index = int(request.form.get("index"))
            updated_behavior = request.form.get("behavior")
            settings["behavior"][index] = updated_behavior
            prompts_data["settings"] = settings
            save_prompts(prompts_data)
            flash("Правило поведения обновлено. Перезапустите бота.")

        elif action == "delete_behavior":
            index = int(request.form.get("index"))
            settings["behavior"].pop(index)
            prompts_data["settings"] = settings
            save_prompts(prompts_data)
            flash("Правило поведения удалено. Перезапустите бота.")

        elif action == "add_restriction":
            new_restriction = request.form.get("new_restriction")
            if new_restriction:
                settings["restrictions"].append(new_restriction)
                prompts_data["settings"] = settings
                save_prompts(prompts_data)
                flash("Ограничение добавлено. Перезапустите бота.")

        elif action == "edit_restriction":
            index = int(request.form.get("index"))
            updated_restriction = request.form.get("restriction")
            settings["restrictions"][index] = updated_restriction
            prompts_data["settings"] = settings
            save_prompts(prompts_data)
            flash("Ограничение обновлено. Перезапустите бота.")

        elif action == "delete_restriction":
            index = int(request.form.get("index"))
            settings["restrictions"].pop(index)
            prompts_data["settings"] = settings
            save_prompts(prompts_data)
            flash("Ограничение удалено. Перезапустите бота.")

    return render_template("prompts.html", settings=settings)

if __name__ == "__main__":
    app.run(debug=True)