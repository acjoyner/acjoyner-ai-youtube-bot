import sqlite3
import shortuuid # You may need to run: pip install shortuuid

conn = sqlite3.connect('youtube.db')
new_record_id = shortuuid.uuid()
new_idea = "Easiest way to learn how to invest"

conn.execute("INSERT INTO Videos (record_id, Idea, Status) VALUES (?, ?, ?)", (new_record_id, new_idea, '1_Script_Pending'))
conn.commit()
conn.close()
print(f"Added new idea: {new_idea}")