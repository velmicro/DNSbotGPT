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

@app.route("/ai-model", methods=["GET", "POST"])
@login_required
def ai_model():
    models = ["llama-3.3-70b-versatile", "mixtral-8x7b"]
    prompts = load_prompts()
    current_model = prompts["settings"].get("model", "llama-3.3-70b-versatile")
    if request.method == "POST":
        new_model = request.form.get("model")
        if new_model in models:
            prompts["settings"]["model"] = new_model
            with open(PROMPTS_FILE, "w", encoding='utf-8') as f:
                json.dump(prompts, f, ensure_ascii=False, indent=4)
            flash("Модель обновлена. Перезапустите бота.")
        else:
            flash("Выбрана недопустимая модель.")
    return render_template("ai_model.html", models=models, current_model=current_model)

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
    commands = ["/start", "/add_qa", "/inf1", "/inf2"]
    prompts = load_prompts()
    active_commands = prompts["settings"].get("active_commands", commands)
    if request.method == "POST":
        selected_commands = request.form.getlist("commands")
        prompts["settings"]["active_commands"] = selected_commands
        with open(PROMPTS_FILE, "w", encoding='utf-8') as f:
            json.dump(prompts, f, ensure_ascii=False, indent=4)
        flash("Команды обновлены. Перезапустите бота.")
    return render_template("commands.html", commands=commands, active_commands=active_commands)

@app.route("/buttons", methods=["GET", "POST"])
@login_required
def buttons():
    prompts = load_prompts()
    buttons = prompts["settings"].get("buttons", ["Новый диалог", "О боте", "Помощь"])
    if request.method == "POST":
        new_buttons = request.form.get("buttons").split(",")
        prompts["settings"]["buttons"] = [b.strip() for b in new_buttons if b.strip()]
        with open(PROMPTS_FILE, "w", encoding='utf-8') as f:
            json.dump(prompts, f, ensure_ascii=False, indent=4)
        flash("Кнопки обновлены. Перезапустите бота.")
    return render_template("buttons.html", buttons=buttons)

@app.route("/dialogs", methods=["GET", "POST"])
@login_required
def dialogs():
    prompts = load_prompts()
    dialogs = prompts["dialogs"]
    if request.method == "POST":
        action = request.form.get("action")
        key = request.form.get("key")
        value = request.form.get("value")
        if action == "add":
            dialogs[key] = value
        elif action == "edit":
            if key in dialogs:
                dialogs[key] = value
        elif action == "delete":
            dialogs.pop(key, None)
        with open(PROMPTS_FILE, "w", encoding='utf-8') as f:
            json.dump(prompts, f, ensure_ascii=False, indent=4)
        flash(f"Диалог {action} успешно.")
    return render_template("dialogs.html", dialogs=dialogs)

if __name__ == "__main__":
    app.run(debug=True)