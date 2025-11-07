# app.py
import sqlite3
import shortuuid
from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)
DB_FILE = 'youtube.db'


# --- This is your main dashboard page ---
@app.route('/')
def index():
    # Fetch all videos from the database to display
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row  # This lets us access columns by name
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Videos ORDER BY id DESC")
    videos = cursor.fetchall()
    conn.close()

    # Render an HTML template and pass the video data to it
    return render_template('index.html', videos=videos)


# --- This route handles adding a new idea ---
@app.route('/add', methods=['POST'])
def add_idea():
    idea = request.form.get('idea')
    if idea:
        conn = sqlite3.connect(DB_FILE)
        new_record_id = shortuuid.uuid()
        conn.execute(
            "INSERT INTO Videos (record_id, Idea, Status) VALUES (?, ?, ?)",
            (new_record_id, idea, '1_Script_Pending')
        )
        conn.commit()
        conn.close()
    return redirect(url_for('index'))


# --- This route handles all your "approval" buttons ---
@app.route('/update_status/<record_id>/<new_status>')
def update_status(record_id, new_status):
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        "UPDATE Videos SET Status = ? WHERE record_id = ?",
        (new_status, record_id)
    )
    conn.commit()
    conn.close()
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True, port=5000)