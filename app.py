"""
سرور گزارش سرپرستان حراست
Flask + SQLite + Google Sheets
"""
import os
import json
import sqlite3
import requests
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS

app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)

# ============================================================
# تنظیمات
# ============================================================
DB_PATH = 'reports.db'
GOOGLE_SHEET_URL = os.environ.get(
    'GOOGLE_SHEET_URL',
    'https://script.google.com/macros/s/AKfycbwaI0Ff6lK-suk0hSSwYBVkU91yIY1eGm77s-Y_PWV5Bl3GN2QNbpKWmzTB4bNfowAZ/exec'
)

# ============================================================
# دیتابیس
# ============================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # جدول گزارش‌های نهایی
    c.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_number TEXT UNIQUE,
            site TEXT,
            date TEXT,
            supervisor TEXT,
            data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # جدول Draft (ذخیره موقت)
    c.execute('''
        CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_key TEXT UNIQUE,
            site TEXT,
            data TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()

init_db()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ============================================================
# شماره گزارش
# ============================================================
START_NUMBER = 14050001

def get_next_report_number():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT MAX(CAST(report_number AS INTEGER)) as max_num FROM reports")
    row = c.fetchone()
    conn.close()

    if row['max_num'] is None:
        return str(START_NUMBER)
    return str(int(row['max_num']) + 1)

# ============================================================
# Routes
# ============================================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/logo.png')
def logo():
    return send_from_directory('static', 'logo.png')

@app.route('/api/next-report-number')
def next_report_number():
    return jsonify({
        'status': 'ok',
        'nextNumber': get_next_report_number()
    })

@app.route('/api/save-draft', methods=['POST'])
def save_draft():
    try:
        data = request.json
        user_key = data.get('user_key', 'default')
        site = data.get('site', '')

        conn = get_db()
        c = conn.cursor()
        c.execute('''
            INSERT INTO drafts (user_key, site, data, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_key) DO UPDATE SET
                site = excluded.site,
                data = excluded.data,
                updated_at = CURRENT_TIMESTAMP
        ''', (user_key, site, json.dumps(data, ensure_ascii=False)))
        conn.commit()
        conn.close()

        return jsonify({'status': 'ok', 'message': 'ذخیره موقت انجام شد'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/load-draft/<user_key>')
def load_draft(user_key):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT data FROM drafts WHERE user_key = ?", (user_key,))
        row = c.fetchone()
        conn.close()

        if row:
            return jsonify({'status': 'ok', 'data': json.loads(row['data'])})
        return jsonify({'status': 'ok', 'data': None})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/submit', methods=['POST'])
def submit():
    try:
        data = request.json
        site = data.get('site', '')
        report_number = get_next_report_number()
        data['reportNumber'] = report_number

        # ۱. ذخیره در دیتابیس محلی
        conn = get_db()
        c = conn.cursor()
        c.execute('''
            INSERT INTO reports (report_number, site, date, supervisor, data)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            report_number,
            site,
            data.get('fromDate', ''),
            data.get('supervisor', ''),
            json.dumps(data, ensure_ascii=False)
        ))
        conn.commit()
        conn.close()

        # ۲. ارسال به گوگل شیت
        google_status = 'ok'
        google_message = ''
        try:
            response = requests.post(
                GOOGLE_SHEET_URL,
                json=data,
                timeout=15,
                allow_redirects=True
            )
            google_message = response.text[:200]
        except Exception as g_err:
            google_status = 'error'
            google_message = str(g_err)

        # ۳. پاک کردن Draft
        user_key = data.get('user_key', 'default')
        conn = get_db()
        c = conn.cursor()
        c.execute("DELETE FROM drafts WHERE user_key = ?", (user_key,))
        conn.commit()
        conn.close()

        return jsonify({
            'status': 'ok',
            'reportNumber': report_number,
            'google': {
                'status': google_status,
                'message': google_message
            }
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/reports')
def list_reports():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id, report_number, site, date, supervisor, created_at FROM reports ORDER BY id DESC LIMIT 100")
        rows = c.fetchall()
        conn.close()
        return jsonify({'status': 'ok', 'reports': [dict(row) for row in rows]})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ============================================================
# اجرا
# ============================================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)