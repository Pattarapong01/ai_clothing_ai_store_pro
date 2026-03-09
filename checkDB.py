import sqlite3

DB_PATH = 'clothing_store.db'

def check_data():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("--- รายการสินค้า (Products) ---")
    try:
        cursor.execute("SELECT * FROM products")
        products = cursor.fetchall()
        for p in products:
            print(f"ID: {p[0]} | ชื่อ: {p[1]} | ราคา: {p[2]} | หมวดหมู่: {p[4]}")
    except Exception as e:
        print("ยังไม่มีตารางสินค้า หรือเกิดข้อผิดพลาด:", e)

    print("\n--- รายการคำถามจาก AI (Tickets) ---")
    try:
        cursor.execute("SELECT * FROM tickets")
        tickets = cursor.fetchall()
        for t in tickets:
            print(f"ID: {t[0]} | ข้อความ: {t[1]} | AI จัดหมวดหมู่เป็น: {t[2]}")
    except Exception as e:
        print("ยังไม่มีตารางคำถาม หรือเกิดข้อผิดพลาด:", e)

    conn.close()

if __name__ == '__main__':
    check_data()