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
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # ตารางสินค้า (โครงสร้างหลักสำหรับ AI Stylist)
    cursor.execute('''CREATE TABLE IF NOT EXISTS products 
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                     name TEXT, price REAL, description TEXT, 
                     category TEXT, image_url TEXT,
                     size TEXT, stock_quantity INTEGER DEFAULT 0,
                     style_tags TEXT, occasion TEXT, fit_type TEXT, color_tone TEXT)''')
    
    # ตาราง Tickets (โครงสร้างหลักสำหรับระบบแชทและ Session)
    cursor.execute('''CREATE TABLE IF NOT EXISTS tickets 
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                     message TEXT, ai_category TEXT, 
                     chat_history TEXT, status TEXT DEFAULT 'OPEN',
                     user_profile TEXT,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    conn.commit()
    conn.close()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- AI Stylist Logic ---
def call_stylist_ai(prompt, context_products, chat_history_list, user_profile):
    system_instruction = f"""
    คุณคือ 'SmartStyle AI Personal Stylist & Assistant'
    หน้าที่ของคุณคือช่วยลูกค้าเลือกซื้อสินค้า หรือตอบคำถามทั่วไปของร้าน (ราคา, สต็อก)
    
    โปรโตคอลการทำงาน:
    1. ตอบคำถามทั่วไป: หากลูกค้าถามราคา, ไซส์, หรือสินค้าที่มี ให้ตอบทันทีจาก 'ข้อมูลสินค้า'
    2. การเป็น Stylist: หากลูกค้าขอคำแนะนำสไตล์ ให้ถามคำถามสั้นๆ 1 ข้อเพื่อเก็บข้อมูลก่อนแนะนำสินค้า 2-3 ชิ้น
    3. ภาษา: ใช้ภาษาไทยแนว Streetwear ที่สุภาพ เป็นกันเอง และดูทันสมัย
    
    ข้อมูลสินค้าที่มีในร้าน: {context_products}
    สไตล์ลูกค้าปัจจุบัน: {user_profile}
    """
    
    history_text = ""
    for msg in chat_history_list[-6:]:
        role = "User" if msg['role'] == 'user' else "Stylist"
        history_text += f"{role}: {msg['content']}\n"
    
    try:
        payload = {
            "model": MODEL_NAME,
            "prompt": f"System: {system_instruction}\n\n{history_text}User: {prompt}\nStylist:",
            "stream": False,
            "options": {"temperature": 0.7}
        }
        response = requests.post(OLLAMA_URL, json=payload, timeout=60)
        if response.status_code == 200:
            return response.json().get('response', '').strip()
        return "ขออภัยครับ AI กำลังพักผ่อน กรุณาลองใหม่อีกครั้ง"
    except Exception as e:
        return f"ขออภัยครับ ระบบขัดข้อง: {str(e)}"

# --- API Routes ---

@app.route('/')
def home():
    return send_from_directory('.', 'index.html')

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# --- Product Management (Edit / Delete / Add) ---

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

# --- Chat & Ticket Management (Switch AI/Human) ---

@app.route('/api/chat', methods=['POST'])
def chat_stylist():
    data = request.json
    user_msg = data.get('message')
    ticket_id = data.get('ticket_id')
    
    if not ticket_id:
        return jsonify({"error": "No session active"}), 400

    conn = get_db_connection()
    row = conn.execute("SELECT ai_category, chat_history, user_profile FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    
    if not row:
        conn.close()
        return jsonify({"error": "Session not found"}), 404

    # 1. บันทึกข้อความลูกค้าลงฐานข้อมูลทันที เพื่อให้แอดมินเห็นใน Inbox แบบเรียลไทม์
    history = json.loads(row['chat_history'] or "[]")
    history.append({"role": "user", "content": user_msg})
    conn.execute("UPDATE tickets SET chat_history = ?, message = ? WHERE id = ?", 
                (json.dumps(history), user_msg, ticket_id))
    conn.commit()

    # 2. หากอยู่ในโหมดพนักงาน (HUMAN_REQUIRED) AI จะไม่ตอบ
    if row['ai_category'] == 'HUMAN_REQUIRED':
        conn.close()
        return jsonify({"status": "sent_to_human", "answer": None})

    # 3. โหมด AI Stylist & Assistant
    try:
        # ดึงข้อมูลสินค้าทั้งหมดเป็น Context ให้ AI
        prods = conn.execute("SELECT name, price, category, style_tags, occasion, description, size FROM products WHERE stock_quantity > 0").fetchall()
        context_products = json.dumps([dict(p) for p in prods])
        
        ai_answer = call_stylist_ai(user_msg, context_products, history, row['user_profile'] or "{}")
        
        # บันทึกคำตอบ AI และอัปเดต Snippet สำหรับหน้าแอดมิน
        history.append({"role": "ai", "content": ai_answer})
        conn.execute("UPDATE tickets SET chat_history = ?, message = ? WHERE id = ?", 
                    (json.dumps(history), f"AI: {ai_answer[:30]}...", ticket_id))
        conn.commit()
        
        conn.close()
        return jsonify({"answer": ai_answer})
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500

@app.route('/api/support', methods=['POST'])
def create_session():
    data = request.json
    mode = data.get('mode', 'ai')
    initial_msg = data.get('message', 'เริ่มเซสชันใหม่')
    category = "HUMAN_REQUIRED" if mode == 'human' else "STYLIST_SESSION"
    
    conn = get_db_connection()
    cursor = conn.cursor()
    history = json.dumps([
        {"role": "system", "content": f"Protocol initialized in {mode.upper()} mode"},
        {"role": "user", "content": initial_msg}
    ])
    cursor.execute("INSERT INTO tickets (message, ai_category, chat_history, status, user_profile) VALUES (?, ?, ?, ?, ?)",
                 (initial_msg, category, history, "OPEN", "{}"))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "ticket_id": new_id, "category": category})

# ฟังก์ชันหลักสำหรับการสลับโหมดแชท (AI <-> Human) ภายใน Ticket เดิม
@app.route('/api/tickets/<int:id>/switch-mode', methods=['POST'])
def switch_ticket_mode(id):
    data = request.json
    mode = data.get('mode') # คาดหวัง 'ai' หรือ 'human'
    category = "HUMAN_REQUIRED" if mode == 'human' else "STYLIST_SESSION"
    
    conn = get_db_connection()
    row = conn.execute("SELECT chat_history FROM tickets WHERE id = ?", (id,)).fetchone()
    if row:
        history = json.loads(row['chat_history'] or "[]")
        status_text = "สลับไปคุยกับพนักงาน" if mode == 'human' else "สลับกลับมาคุยกับ AI Stylist"
        history.append({"role": "system", "content": status_text})
        
        # อัปเดตหมวดหมู่ Ticket และประวัติแชท
        conn.execute("UPDATE tickets SET ai_category = ?, chat_history = ?, message = ? WHERE id = ?", 
                    (category, json.dumps(history), f"System: {status_text}", id))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "category": category})
    
    conn.close()
    return jsonify({"error": "Ticket session not found"}), 404

@app.route('/api/tickets', methods=['GET'])
def get_tickets():
    conn = get_db_connection()
    # เรียงลำดับ Ticket: เคสพนักงาน (Human) มาก่อน และตามด้วยเวลาล่าสุด
    tickets = conn.execute("""SELECT * FROM tickets 
                           ORDER BY CASE WHEN ai_category = 'HUMAN_REQUIRED' THEN 0 ELSE 1 END, 
                           created_at DESC""").fetchall()
    conn.close()
    return jsonify([dict(t) for t in tickets])

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

@app.route('/api/admin/reply', methods=['POST'])
def admin_reply():
    data = request.json
    ticket_id = data.get('ticket_id')
    message = data.get('message')
    
    conn = get_db_connection()
    row = conn.execute("SELECT chat_history FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if row:
        history = json.loads(row['chat_history'] or "[]")
        history.append({"role": "admin", "content": message})
        # อัปเดต snippet ใน Inbox เพื่อให้เห็นข้อความล่าสุดของแอดมิน
        conn.execute("UPDATE tickets SET chat_history = ?, message = ? WHERE id = ?", 
                    (json.dumps(history), f"Staff: {message}", ticket_id))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    
    conn.close()
    return jsonify({"status": "error", "message": "Ticket not found"}), 404

# --- AI Utilities (Draft Post) ---

@app.route('/api/ai/generate-post', methods=['POST'])
def ai_generate_post():
    try:
        data = request.json
        prompt = f"""
        จงเขียนโพสต์ขายของแนว Streetwear สำหรับสินค้า: {data.get('name', 'สินค้าใหม่')}
        ราคา: {data.get('price', 'N/A')} บาท | สไตล์: {data.get('style_tags', 'Streetwear')} 
        ใช้ภาษาไทยที่ดูเท่ ทันสมัย ใส่ Emoji และ Hashtag
        """
        payload = {"model": MODEL_NAME, "prompt": prompt, "stream": False, "options": {"temperature": 0.8}}
        res = requests.post(OLLAMA_URL, json=payload, timeout=90)
        return jsonify({"content": res.json().get('response', '').strip()})
    except Exception as e:
        return jsonify({"content": f"AI Draft ขัดข้อง: {str(e)}"})

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000, threaded=True)