from flask import Flask, request, jsonify, send_from_directory
import sqlite3
import requests
import os
import json
from werkzeug.utils import secure_filename

app = Flask(__name__)

# --- Configuration ---
DB_PATH = 'clothing_store.db'
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "llama3"
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def get_db_connection():
    # เพิ่ม timeout เพื่อป้องกันปัญหา Database Locked ในโหมด Threaded
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # สร้างตาราง products ถ้ายังไม่มี
    cursor.execute('''CREATE TABLE IF NOT EXISTS products 
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                     name TEXT, price REAL, description TEXT, 
                     category TEXT, image_url TEXT)''')
    
    # สร้างตาราง tickets เบื้องต้นถ้ายังไม่มี
    cursor.execute('''CREATE TABLE IF NOT EXISTS tickets 
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                     message TEXT, ai_category TEXT, 
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # --- Database Migration ---
    cursor.execute("PRAGMA table_info(tickets)")
    columns = [column[1] for column in cursor.fetchall()]
    
    if 'chat_history' not in columns:
        print("Migrating: Adding 'chat_history' column...")
        cursor.execute("ALTER TABLE tickets ADD COLUMN chat_history TEXT")
    
    if 'status' not in columns:
        print("Migrating: Adding 'status' column...")
        cursor.execute("ALTER TABLE tickets ADD COLUMN status TEXT DEFAULT 'OPEN'")
        
    conn.commit()
    conn.close()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- AI Helper Function ---
def call_llama(prompt, context=""):
    try:
        full_prompt = f"System: You are a helpful assistant for 'AI STORE'.\nContext: {context}\n\nUser: {prompt}\nAssistant:"
        payload = {
            "model": MODEL_NAME, "prompt": full_prompt, "stream": False,
            "options": {"num_predict": 300, "temperature": 0.4}
        }
        response = requests.post(OLLAMA_URL, json=payload, timeout=90)
        return response.json().get('response', '').strip() if response.status_code == 200 else "ขออภัยครับ ระบบขัดข้อง"
    except Exception as e:
        return f"ขออภัยครับ เกิดข้อผิดพลาด: {str(e)}"

# --- API Routes ---

@app.route('/')
def home():
    return send_from_directory('.', 'index.html')

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/api/products', methods=['GET', 'POST'])
def handle_products():
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            price = request.form.get('price')
            category = request.form.get('category')
            description = request.form.get('description')
            image_url = ""
            if 'image' in request.files:
                file = request.files['image']
                if file and allowed_file(file.filename):
                    filename = f"{int(os.path.getmtime(DB_PATH))}_{secure_filename(file.filename)}" if os.path.exists(DB_PATH) else secure_filename(file.filename)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    image_url = f"/uploads/{filename}"
            
            conn = get_db_connection()
            conn.execute("INSERT INTO products (name, price, description, category, image_url) VALUES (?,?,?,?,?)",
                         (name, price, description, category, image_url))
            conn.commit()
            conn.close()
            return jsonify({"status": "success"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
    
    conn = get_db_connection()
    prods = conn.execute("SELECT * FROM products").fetchall()
    conn.close()
    return jsonify([dict(p) for p in prods])

@app.route('/api/products/<int:id>', methods=['DELETE'])
def delete_product(id):
    try:
        conn = get_db_connection()
        conn.execute("DELETE FROM products WHERE id = ?", (id,))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- Chat & RAG Endpoint ---
@app.route('/api/chat', methods=['POST'])
def chat_bot():
    data = request.json
    user_message = data.get('message')
    ticket_id = data.get('ticket_id')

    if ticket_id:
        try:
            conn = get_db_connection()
            ticket = conn.execute("SELECT chat_history FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
            if ticket:
                history = json.loads(ticket[0] if ticket[0] else "[]")
                history.append({"role": "user", "content": user_message})
                conn.execute("UPDATE tickets SET chat_history = ? WHERE id = ?", (json.dumps(history), ticket_id))
                conn.commit()
                conn.close()
                return jsonify({"status": "sent_to_human"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    conn = get_db_connection()
    prods = conn.execute("SELECT name, price, description FROM products").fetchall()
    conn.close()
    knowledge = "สินค้าในร้าน:\n" + "\n".join([f"- {p[0]} ราคา {p[1]} ({p[2]})" for p in prods])
    ai_answer = call_llama(user_message, context=knowledge)
    return jsonify({"answer": ai_answer})

# --- Support & Admin Chat API ---
@app.route('/api/support', methods=['POST'])
def request_support():
    try:
        data = request.json
        first_msg = data.get('message', 'ลูกค้าต้องการคุยกับพนักงาน')
        initial_history = json.dumps([{"role": "system", "content": "เริ่มการสนทนากับพนักงาน"}, {"role": "user", "content": first_msg}])
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO tickets (message, ai_category, chat_history, status) VALUES (?, ?, ?, ?)",
                     (first_msg, "HUMAN_REQUIRED", initial_history, "OPEN"))
        new_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "ticket_id": new_id})
    except Exception as e:
        print(f"Error in request_support: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/admin/reply', methods=['POST'])
def admin_reply():
    try:
        data = request.json
        ticket_id = data.get('ticket_id')
        reply_msg = data.get('message')
        
        conn = get_db_connection()
        ticket = conn.execute("SELECT chat_history FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if ticket:
            history = json.loads(ticket[0] if ticket[0] else "[]")
            history.append({"role": "admin", "content": reply_msg})
            conn.execute("UPDATE tickets SET chat_history = ? WHERE id = ?", (json.dumps(history), ticket_id))
            conn.commit()
            conn.close()
            return jsonify({"status": "success"})
        return jsonify({"status": "error", "message": "Ticket not found"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/tickets', methods=['GET'])
def get_tickets():
    try:
        conn = get_db_connection()
        tickets = conn.execute("SELECT * FROM tickets ORDER BY id DESC").fetchall()
        conn.close()
        return jsonify([dict(t) for t in tickets])
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/tickets/<int:id>', methods=['GET'])
def get_ticket_detail(id):
    try:
        conn = get_db_connection()
        ticket = conn.execute("SELECT * FROM tickets WHERE id = ?", (id,)).fetchone()
        conn.close()
        return jsonify(dict(ticket)) if ticket else (jsonify({"error": "Not found"}), 404)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/tickets/<int:id>', methods=['DELETE'])
def delete_ticket(id):
    try:
        conn = get_db_connection()
        conn.execute("DELETE FROM tickets WHERE id = ?", (id,))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"Delete Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- เพิ่ม Route สำหรับการปิดแชทโดยลูกค้า ---
@app.route('/api/tickets/<int:id>/close', methods=['POST'])
def close_ticket(id):
    try:
        conn = get_db_connection()
        ticket = conn.execute("SELECT chat_history FROM tickets WHERE id = ?", (id,)).fetchone()
        if ticket:
            history = json.loads(ticket[0] if ticket[0] else "[]")
            history.append({"role": "system", "content": "ลูกค้าออกจากแชทแล้ว"})
            conn.execute("UPDATE tickets SET chat_history = ?, status = 'CLOSED', ai_category = 'RESOLVED' WHERE id = ?", (json.dumps(history), id))
            conn.commit()
            conn.close()
            return jsonify({"status": "success"})
        return jsonify({"status": "error"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# Route สำหรับตรวจสอบข้อมูลดิบ (Debug Only)
@app.route('/api/debug/db-check')
def debug_db_check():
    conn = get_db_connection()
    tickets = conn.execute("SELECT id, message, ai_category, status FROM tickets").fetchall()
    conn.close()
    return jsonify([dict(t) for t in tickets])

@app.route('/api/ai/generate-post', methods=['POST'])
def ai_generate_post():
    data = request.json
    prompt = f"เขียนโพสต์ขายของสั้นๆ สำหรับ: {data['name']} ราคา {data['price']} หมวดหมู่: {data['category']} ใส่ emoji"
    return jsonify({"content": call_llama(prompt)})

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000, threaded=True)