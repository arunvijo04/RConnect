from flask import Flask, render_template, jsonify, request
import sqlite3
import os
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup

load_dotenv()

app = Flask(__name__)

# Connect to SQLite DB
conn = sqlite3.connect('notices.db', check_same_thread=False)
c = conn.cursor()

# Create tables if not exist
c.execute('''CREATE TABLE IF NOT EXISTS notices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                date TEXT,
                link TEXT UNIQUE
            )''')

c.execute('''CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                chat_id TEXT UNIQUE
            )''')
conn.commit()

# Telegram Bot Token from .env file
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['POST'])
def register():
    name = request.form.get('name')
    chat_id = request.form.get('chat_id')
    try:
        c.execute("INSERT INTO students (name, chat_id) VALUES (?, ?)", (name, chat_id))
        conn.commit()
        return jsonify({'status': 'registered'}), 201
    except sqlite3.IntegrityError:
        return jsonify({'status': 'already exists'}), 400

@app.route('/setWebhook', methods=['GET'])
def set_webhook():
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
    webhook_url = os.getenv("WEBHOOK_URL")
    payload = {'url': webhook_url}
    
    response = requests.post(url, data=payload)
    return jsonify(response.json())

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    if "message" in data:
        chat_id = data['message']['chat']['id']
        name = data['message']['chat'].get('first_name', 'Unknown')
        
        print(f"Received chat ID: {chat_id}")  # This will help you debug

        # Store chat_id in the database
        try:
            c.execute("INSERT INTO students (name, chat_id) VALUES (?, ?)", (name, chat_id))
            conn.commit()
        except sqlite3.IntegrityError:
            pass  # If student already exists, just ignore

        # Send a welcome message
        send_telegram(chat_id, "Welcome to the notice board bot! You are now registered.")

    return jsonify({'status': 'ok'}), 200



def fetch_notices():
    base_url = "https://www.rajagiritech.ac.in/home/notice/Notice.asp?page="
    new_notices = []

    for page in range(1, 11):
        url = base_url + str(page)
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"[Error] Could not load page {page}: {e}")
            continue

        soup = BeautifulSoup(response.text, 'html.parser')
        table_rows = soup.select('table tr')[1:]

        for row in table_rows:
            cols = row.find_all('td')
            if len(cols) < 3:
                continue

            date = cols[1].get_text(strip=True)
            title = cols[2].get_text(strip=True)
            link_tag = cols[2].find('a')
            link = "https://www.rajagiritech.ac.in/home/notice/" + link_tag['href'] if link_tag else ""

            if not link:
                continue

            c.execute("SELECT 1 FROM notices WHERE link = ?", (link,))
            if not c.fetchone():
                c.execute("INSERT INTO notices (title, date, link) VALUES (?, ?, ?)", (title, date, link))
                conn.commit()
                new_notices.append({'title': title, 'date': date, 'link': link})

    return new_notices

ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

def notify_admin(name, chat_id):
    send_telegram(ADMIN_CHAT_ID, f"👤 New student registered:\nName: {name}\nChat ID: `{chat_id}`")


def send_telegram(chat_id, text):
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        res = requests.post(url, data=payload)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"Error sending message to {chat_id}: {e}")

def notify_students(notices):
    c.execute("SELECT chat_id FROM students")
    students = c.fetchall()
    for notice in notices:
        msg = f"*New Notice*\n{notice['title']}\n*Date:* {notice['date']}\n[View Notice]({notice['link']})"
        for student in students:
            send_telegram(student[0], msg)

@app.route('/students', methods=['GET'])
def get_students():
    c.execute("SELECT id, name, chat_id FROM students ORDER BY id DESC")
    students = c.fetchall()
    return jsonify([{'id': s[0], 'name': s[1], 'chat_id': s[2]} for s in students])


@app.route('/scan', methods=['GET'])
def scan():
    notices = fetch_notices()
    if notices:
        notify_students(notices)

    return jsonify({'new_notices': notices})

@app.route('/latest-notices', methods=['GET'])
def latest_notices():
    c.execute("SELECT title, date, link FROM notices ORDER BY id DESC LIMIT 10")
    notices = c.fetchall()
    return jsonify([{'title': r[0], 'date': r[1], 'link': r[2]} for r in notices])

@app.route('/notices', methods=['GET'])
def get_notices():
    c.execute("SELECT title, date, link FROM notices ORDER BY id DESC")
    rows = c.fetchall()
    return jsonify([{'title': r[0], 'date': r[1], 'link': r[2]} for r in rows])


@app.route('/students-info', methods=['GET'])
def get_students_info():
    c.execute("SELECT id, name, chat_id FROM students ORDER BY id DESC")
    students = c.fetchall()
    return jsonify([{'id': s[0], 'name': s[1], 'chat_id': s[2]} for s in students])

@app.route('/add-student', methods=['POST'])
def add_student():
    name = request.json.get('name')
    chat_id = request.json.get('chat_id')
    try:
        c.execute("INSERT INTO students (name, chat_id) VALUES (?, ?)", (name, chat_id))
        conn.commit()
        return jsonify({'status': 'Student added successfully'}), 201
    except sqlite3.IntegrityError:
        return jsonify({'status': 'Student already exists'}), 400

@app.route('/delete-student/<int:student_id>', methods=['DELETE'])
def delete_student(student_id):
    c.execute("DELETE FROM students WHERE id = ?", (student_id,))
    conn.commit()
    return jsonify({'status': 'Student deleted successfully'}), 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
