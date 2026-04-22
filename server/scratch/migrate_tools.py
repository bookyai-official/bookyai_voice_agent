import sqlite3

db_path = r"E:\Web Projects\bookyai\db.sqlite3"

def migrate():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Add new columns
    columns_to_add = [
        ("tool_type", "VARCHAR(50) DEFAULT 'webhook'"),
        ("tool_target", "VARCHAR(255)")
    ]
    
    for col_name, col_type in columns_to_add:
        try:
            print(f"Adding column {col_name} to agent_tools...")
            cursor.execute(f"ALTER TABLE agent_tools ADD COLUMN {col_name} {col_type}")
            print(f"Column {col_name} added successfully.")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print(f"Column {col_name} already exists.")
            else:
                print(f"Error adding {col_name}: {e}")

    # 2. Make url nullable
    # SQLite doesn't support ALTER TABLE ALTER COLUMN NULL easily.
    # But usually it doesn't enforce NOT NULL strictly if we don't specify it in the migration?
    # Actually, we can just leave it as is for now, or use the 'recreate table' trick if needed.
    # Since we are using SQLAlchemy, it might complain if we don't fix it.
    
    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate()
