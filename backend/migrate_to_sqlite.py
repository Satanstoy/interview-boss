# migrate_to_sqlite.py
import sqlite3
import csv
import os

DATA_DIR = "/root/sj/multimodal-parser/backend/data"
DB_PATH = os.path.join(DATA_DIR, "multimodal.db")

# CSV 文件路径
JD_CSV = os.path.join(DATA_DIR, "jd.csv")
INTERVIEW_CSV = os.path.join(DATA_DIR, "interview.csv")
TAGGED_CSV = os.path.join(DATA_DIR, "interview_questions.csv")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. 创建 JD 表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jd (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            company TEXT,
            job_title TEXT,
            salary TEXT,
            tech_stack TEXT,
            bonus TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 2. 创建面经原文表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS interview (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            company TEXT,
            round TEXT,
            focus TEXT,
            questions_list TEXT,
            difficulty TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 3. 创建题目明细表 (原 interview_questions.csv)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS questions_detail (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            company TEXT,
            round TEXT,
            question TEXT,
            cat1 TEXT,
            cat2 TEXT,
            tags TEXT,
            diff_tag TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 4. 创建未来的高频精炼题库表 (预留)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS master_question_bank (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT UNIQUE,
            cat1 TEXT,
            cat2 TEXT,
            tags TEXT,
            difficulty TEXT,
            frequency INTEGER DEFAULT 1,
            ai_answer TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    return conn

def migrate_csv_to_table(conn, csv_path, table_name, expected_columns):
    if not os.path.exists(csv_path):
        print(f"⚠️ 找不到文件 {csv_path}，跳过迁移。")
        return

    cursor = conn.cursor()
    with open(csv_path, mode='r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        headers = next(reader, None) # 跳过表头
        
        count = 0
        for row in reader:
            if not row: continue
            # 补齐长度
            padded_row = row + [""] * max(0, expected_columns - len(row))
            padded_row = padded_row[:expected_columns]
            
            placeholders = ",".join(["?"] * expected_columns)
            query = f"INSERT INTO {table_name} ({','.join(['col'+str(i) for i in range(expected_columns)])}) VALUES ({placeholders})"
            
            # 动态替换列名
            if table_name == 'jd':
                query = f"INSERT INTO jd (url, company, job_title, salary, tech_stack, bonus) VALUES (?,?,?,?,?,?)"
            elif table_name == 'interview':
                query = f"INSERT INTO interview (url, company, round, focus, questions_list, difficulty) VALUES (?,?,?,?,?,?)"
            elif table_name == 'questions_detail':
                query = f"INSERT INTO questions_detail (url, company, round, question, cat1, cat2, tags, diff_tag) VALUES (?,?,?,?,?,?,?,?)"

            cursor.execute(query, padded_row)
            count += 1
            
    conn.commit()
    print(f"✅ 成功将 {count} 条数据从 {os.path.basename(csv_path)} 迁移至 {table_name} 表。")

if __name__ == "__main__":
    print("开始迁移数据到 SQLite...")
    conn = init_db()
    migrate_csv_to_table(conn, JD_CSV, 'jd', 6)
    migrate_csv_to_table(conn, INTERVIEW_CSV, 'interview', 6)
    migrate_csv_to_table(conn, TAGGED_CSV, 'questions_detail', 8)
    conn.close()
    print(f"🎉 迁移完成！数据库文件已生成: {DB_PATH}")