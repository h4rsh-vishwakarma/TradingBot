import sqlite3

DB_PATH = "db.sqlite3"

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Add the column if it does not exist
try:
    cursor.execute("ALTER TABLE metrics ADD COLUMN last_updated TIMESTAMP")
    print("✅ Column 'last_updated' added successfully!")
except sqlite3.OperationalError as e:
    print("⚠️", e)

conn.commit()
conn.close()