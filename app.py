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
    # เพิ่ม timeout เพื่อป้องกันปัญหา Database Locked
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # ตารางสินค้า (Metadata สำหรับ Stylist และระบบจัดการสินค้า)
    cursor.execute('''CREATE TABLE IF NOT EXISTS products 
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                     name TEXT, price REAL, description TEXT, 
                     category TEXT, image_url TEXT,
                     size TEXT, stock_quantity INTEGER DEFAULT 0,
                     style_tags TEXT, occasion TEXT, fit_type TEXT, color_tone TEXT)''')
    
    # ตาราง Tickets (ระบบแชทลูกค้าและพนักงาน)
    cursor.execute('''CREATE TABLE IF NOT EXISTS tickets 
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                     message TEXT, ai_category TEXT, 
                     chat_history TEXT, status TEXT DEFAULT 'OPEN',
                     user_profile TEXT,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # --- Database Migration ---
    cursor.execute("PRAGMA table_info(products)")
    columns = [column[1] for column in cursor.fetchall()]
    for col in ['style_tags', 'occasion', 'fit_type', 'color_tone', 'size', 'stock_quantity']:
        if col not in columns:
            cursor.execute(f"ALTER TABLE products ADD COLUMN {col} TEXT")
            
    cursor.execute("PRAGMA table_info(tickets)")
    t_columns = [column[1] for column in cursor.fetchall()]
    if 'user_profile' not in t_columns:
        cursor.execute("ALTER TABLE tickets ADD COLUMN user_profile TEXT")
    if 'chat_history' not in t_columns:
        cursor.execute("ALTER TABLE tickets ADD COLUMN chat_history TEXT")
    if 'status' not in t_columns:
        cursor.execute("ALTER TABLE tickets ADD COLUMN status TEXT DEFAULT 'OPEN'")

    conn.commit()
    conn.close()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- AI Stylist Logic ---
def call_stylist_ai(prompt, context_products, chat_history, user_profile):
    system_instruction = f"""
    You are 'SmartStyle AI Personal Stylist'. Your goal is to help users find the perfect outfit.
    
    STYLIST PROTOCOL:
    1. If the user asks for styling advice, ask ONE short question about their Style, Occasion, or Fit.
    2. If you have enough info, summarize their profile and recommend 2-3 specific products from the context.
    3. Explain WHY these products suit them.
    4. Keep responses trendy and professional.
    
    USER PROFILE: {user_profile}
    AVAILABLE PRODUCTS: {context_products}
    """
    
    try:
        payload = {
            "model": MODEL_NAME,
            "prompt": f"System: {system_instruction}\nHistory: {chat_history}\nUser: {prompt}\nStylist:",
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 400}
        }
        response = requests.post(OLLAMA_URL, json=payload, timeout=90)
        return response.json().get('response', '').strip()
    except Exception as e:
        return "ขออภัยครับ ระบบ Stylist ขัดข้องชั่วคราว"

# --- Routes ---

@app.route('/')
def home():
    return send_from_directory('.', 'index.html')

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ฟังก์ชันจัดการสินค้า (เพิ่มสินค้า)
@app.route('/api/products', methods=['GET', 'POST'])
def handle_products():
    conn = get_db_connection()
    if request.method == 'POST':
        try:
            data = request.form
            image_url = ""
            if 'image' in request.files:
                file = request.files['image']
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    image_url = f"/uploads/{filename}"
            
            conn.execute("""INSERT INTO products 
                (name, price, description, category, image_url, size, stock_quantity, style_tags, occasion) 
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (data.get('name'), data.get('price'), data.get('description'), data.get('category'), 
                 image_url, data.get('size'), data.get('stock_quantity'), 
                 data.get('style_tags'), data.get('occasion')))
            conn.commit()
            return jsonify({"status": "success"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
        finally:
            conn.close()
    
    prods = conn.execute("SELECT * FROM products").fetchall()
    conn.close()
    return jsonify([dict(p) for p in prods])

# ฟังก์ชันจัดการสินค้า (แก้ไขสินค้า)
@app.route('/api/products/<int:id>/edit', methods=['POST'])
def edit_product(id):
    try:
        data = request.form
        conn = get_db_connection()
        update_fields = ["name=?", "price=?", "description=?", "category=?", "size=?", "stock_quantity=?", "style_tags=?", "occasion=?"]
        params = [data.get('name'), data.get('price'), data.get('description'), data.get('category'), data.get('size'), data.get('stock_quantity'), data.get('style_tags'), data.get('occasion')]
        
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                filename = f"edit_{id}_{secure_filename(file.filename)}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                update_fields.append("image_url=?")
                params.append(f"/uploads/{filename}")
                
        params.append(id)
        conn.execute(f"UPDATE products SET {', '.join(update_fields)} WHERE id=?", params)
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ฟังก์ชันจัดการสินค้า (ลบสินค้า)
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

# ระบบแชท (AI Stylist + Human Interaction)
@app.route('/api/chat', methods=['POST'])
def chat_stylist():
    data = request.json
    user_msg = data.get('message')
    ticket_id = data.get('ticket_id')
    
    conn = get_db_connection()
    
    # 1. ตรวจสอบโหมดพนักงานก่อน
    if ticket_id:
        row = conn.execute("SELECT ai_category, chat_history, user_profile FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row and row['ai_category'] == 'HUMAN_REQUIRED':
            # บันทึกข้อความลูกค้าลง History แต่ไม่ต้องเรียก AI
            history = json.loads(row['chat_history'] or "[]")
            history.append({"role": "user", "content": user_msg})
            conn.execute("UPDATE tickets SET chat_history = ? WHERE id = ?", (json.dumps(history), ticket_id))
            conn.commit()
            conn.close()
            return jsonify({"status": "sent_to_human"})

    # 2. โหมด AI (ดึง Context สินค้า)
    prods = conn.execute("SELECT name, price, category, style_tags, occasion FROM products WHERE stock_quantity > 0").fetchall()
    context_products = json.dumps([dict(p) for p in prods])
    
    history_str = "[]"
    profile_str = "{}"
    if ticket_id:
        row = conn.execute("SELECT chat_history, user_profile FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row:
            history_str = row['chat_history'] or "[]"
            profile_str = row['user_profile'] or "{}"

    # เรียก AI
    ai_answer = call_stylist_ai(user_msg, context_products, history_str, profile_str)
    
    # บันทึกประวัติ
    if ticket_id:
        current_history = json.loads(history_str)
        current_history.append({"role": "user", "content": user_msg})
        current_history.append({"role": "ai", "content": ai_answer})
        conn.execute("UPDATE tickets SET chat_history = ? WHERE id = ?", (json.dumps(current_history), ticket_id))
        conn.commit()
    
    conn.close()
    return jsonify({"answer": ai_answer})

# สร้าง Session/Ticket
@app.route('/api/support', methods=['POST'])
def create_session():
    data = request.json
    msg = data.get('message', 'User started session')
    # กำหนดหมวดหมู่เป็น HUMAN_REQUIRED หากต้องการติดต่อพนักงานทันที
    category = "HUMAN_REQUIRED" if "พนักงาน" in msg or "staff" in msg.lower() else "STYLIST_SESSION"
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO tickets (message, ai_category, chat_history, status, user_profile) VALUES (?, ?, ?, ?, ?)",
                 (msg, category, "[]", "OPEN", "{}"))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "ticket_id": new_id})

# ดึงรายการ Ticket ทั้งหมด
@app.route('/api/tickets', methods=['GET'])
def get_tickets():
    conn = get_db_connection()
    tickets = conn.execute("SELECT * FROM tickets ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(t) for t in tickets])

# ดึงรายละเอียด Ticket และปิดเคส
@app.route('/api/tickets/<int:id>', methods=['GET', 'DELETE'])
def handle_ticket(id):
    conn = get_db_connection()
    if request.method == 'DELETE':
        conn.execute("DELETE FROM tickets WHERE id = ?", (id,))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    
    ticket = conn.execute("SELECT * FROM tickets WHERE id = ?", (id,)).fetchone()
    conn.close()
    return jsonify(dict(ticket)) if ticket else (jsonify({"error": "not found"}), 404)

@app.route('/api/tickets/<int:id>/close', methods=['POST'])
def close_ticket(id):
    conn = get_db_connection()
    conn.execute("UPDATE tickets SET status = 'CLOSED', ai_category = 'RESOLVED' WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

# ฟังก์ชัน Admin ตอบกลับ
@app.route('/api/admin/reply', methods=['POST'])
def admin_reply():
    data = request.json
    conn = get_db_connection()
    row = conn.execute("SELECT chat_history FROM tickets WHERE id = ?", (data.get('ticket_id'),)).fetchone()
    if row:
        history = json.loads(row['chat_history'] or "[]")
        history.append({"role": "admin", "content": data.get('message')})
        conn.execute("UPDATE tickets SET chat_history = ? WHERE id = ?", (json.dumps(history), data.get('ticket_id')))
        conn.commit()
    conn.close()
    return jsonify({"status": "success"})

# ฟังก์ชัน AI ร่างโพสต์ขายของ (Draft Post)
@app.route('/api/ai/generate-post', methods=['POST'])
def ai_generate_post():
    data = request.json
    # นำ Tags และ Occasion มาประกอบร่างโพสต์ให้ดูพรีเมียมขึ้น
    prompt = f"""
    Write a high-end, hype streetwear social media post in Thai with emojis.
    Product: {data['name']}
    Price: {data['price']} THB
    Style: {data.get('style_tags', 'Streetwear')}
    Best for: {data.get('occasion', 'Everyday look')}
    Include hashtags.
    """
    try:
        payload = {"model": MODEL_NAME, "prompt": prompt, "stream": False, "options": {"temperature": 0.8}}
        res = requests.post(OLLAMA_URL, json=payload, timeout=90)
        return jsonify({"content": res.json().get('response', '')})
    except:
        return jsonify({"content": "ระบบร่างโพสต์ขัดข้อง กรุณาลองใหม่"})

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000, threaded=True)