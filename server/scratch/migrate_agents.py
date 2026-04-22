import sqlite3

db_path = r"E:\Web Projects\bookyai\db.sqlite3"

def migrate():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    columns_to_add = [
        ("greeting_message", "TEXT"),
        ("temperature", "FLOAT DEFAULT 0.8"),
        ("silence_duration_ms", "INTEGER DEFAULT 1000"),
        ("vad_threshold", "FLOAT DEFAULT 0.5")
    ]
    
    for col_name, col_type in columns_to_add:
        try:
            print(f"Adding column {col_name} to voice_agents...")
            cursor.execute(f"ALTER TABLE voice_agents ADD COLUMN {col_name} {col_type}")
            print(f"Column {col_name} added successfully.")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print(f"Column {col_name} already exists.")
            else:
                print(f"Error adding {col_name}: {e}")
    
    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate()
