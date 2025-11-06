# setup_database.py
import sqlite3

# This creates or connects to a file named 'youtube.db'
conn = sqlite3.connect('youtube.db')
cursor = conn.cursor()

# This is the SQL command to create your table
# Note: We use underscores for column names in SQL (it's standard)
create_table_sql = """
CREATE TABLE IF NOT EXISTS Videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL UNIQUE,
    Idea TEXT,
    Status TEXT DEFAULT '1_Script_Pending',
    Title TEXT,
    Script TEXT,
    Description TEXT,
    Audio_File_URL TEXT,
    Video_File_URL TEXT,
    Video_Job_ID TEXT,
    YouTube_ID TEXT
);
"""

cursor.execute(create_table_sql)
print("Database 'youtube.db' and table 'Videos' created successfully.")

conn.commit()
conn.close()