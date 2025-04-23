from flask import Flask, render_template, jsonify, request
import os
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
from google.cloud import firestore
import hashlib
import urllib.parse

load_dotenv()

app = Flask(__name__)

# Initialize Firestore
db = firestore.Client()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/students')
def students():
    return render_template('students.html')

@app.route('/register', methods=['POST'])
def register():
    name = request.form.get('name')
    chat_id = request.form.get('chat_id')
    if student_exists(chat_id):
        return jsonify({'status': 'already exists'}), 400
    register_student(name, chat_id)
    return jsonify({'status': 'registered'}), 201

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
        chat_id = str(data['message']['chat']['id'])
        name = data['message']['chat'].get('first_name', 'Unknown')
        text = data['message'].get('text', '').strip().lower()

        print(f"Received chat ID: {chat_id}, Message: {text}")

        if text == '/notices':
            notices = get_latest_notices()
            if notices:
                for n in notices:
                    msg = f"*{n['title']}*\n\U0001F4C5 {n['date']}\n[View Notice]({n['link']})"
                    send_telegram(chat_id, msg)
            else:
                send_telegram(chat_id, "No notices found.")
            return jsonify({'status': 'notices sent'}), 200

        if text == '/start':
            if student_exists(chat_id):
                send_telegram(chat_id, "You are already registered.")
            else:
                register_student(name, chat_id)
                notify_admin(name, chat_id)
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

            if not notice_exists(link):
                store_notice(title, date, link)
                new_notices.append({'title': title, 'date': date, 'link': link})

    return new_notices


def extract_notice_id(link):
    parsed = urllib.parse.urlparse(link)
    query_params = urllib.parse.parse_qs(parsed.query)
    return query_params.get("NID", [None])[0]


def send_telegram(chat_id, text):
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
    except Exception as e:
        print(f"Error sending message to {chat_id}: {e}")


def notify_admin(name, chat_id):
    send_telegram(ADMIN_CHAT_ID, f"\U0001F464 New student registered:\nName: {name}\nChat ID: `{chat_id}`")


def student_exists(chat_id):
    return db.collection('students').document(chat_id).get().exists


def register_student(name, chat_id):
    db.collection('students').document(chat_id).set({
        'name': name,
        'chat_id': chat_id
    })


def get_all_students():
    return [doc.to_dict() for doc in db.collection('students').stream()]


def notify_students(notices):
    for student in get_all_students():
        for notice in notices:
            msg = f"*New Notice*\n{notice['title']}\n*Date:* {notice['date']}\n[View Notice]({notice['link']})"
            send_telegram(student['chat_id'], msg)


def store_notice(title, date, link):
    notice_id = extract_notice_id(link)
    if not notice_id:
        notice_id = hashlib.sha256(link.encode()).hexdigest()
    else:
        notice_id = str(notice_id)

    db.collection('notices').document(notice_id).set({
        'nid': int(notice_id) if notice_id.isdigit() else 0,
        'title': title,
        'date': date,
        'link': link
    })




def notice_exists(link):
    notice_id = extract_notice_id(link)
    if not notice_id:
        notice_id = hashlib.sha256(link.encode()).hexdigest()
    
    return db.collection('notices').document(notice_id).get().exists



def get_latest_notices(limit=10):
    docs = db.collection('notices').order_by('nid', direction=firestore.Query.DESCENDING).limit(limit).stream()
    return [doc.to_dict() for doc in docs]



@app.route('/scan', methods=['GET'])
def scan():
    notices = fetch_notices()
    if notices:
        notify_students(notices)
    return jsonify({'new_notices': notices})


@app.route('/latest-notices', methods=['GET'])
def latest_notices():
    return jsonify(get_latest_notices())


@app.route('/notices', methods=['GET'])
def get_notices():
    docs = db.collection('notices').order_by('date', direction=firestore.Query.ASCENDING).stream()
    return jsonify([doc.to_dict() for doc in docs])


@app.route('/students-info', methods=['GET'])
def get_students_info():
    return jsonify(get_all_students())


@app.route('/add-student', methods=['POST'])
def add_student():
    data = request.json
    chat_id = data.get('chat_id')
    name = data.get('name')
    if student_exists(chat_id):
        return jsonify({'status': 'Student already exists'}), 400
    register_student(name, chat_id)
    return jsonify({'status': 'Student added successfully'}), 201


@app.route('/delete-student/<chat_id>', methods=['DELETE'])
def delete_student(chat_id):
    db.collection('students').document(chat_id).delete()
    return jsonify({'status': 'Student deleted successfully'}), 200


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
