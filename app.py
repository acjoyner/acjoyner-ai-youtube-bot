# app.py
import os
import sqlite3
import shortuuid
import threading
from flask import Flask, render_template, request, redirect, url_for, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
DB_FILE = os.getenv('DB_FILE', 'youtube.db')

# Pipeline statuses in order
STATUSES = [
    '1_Idea_Review',
    '2_Script_Pending',
    '3_Script_Review',
    '4_Prompts_Pending',
    '5_Prompts_Review',
    '6_In_Production',
    '7_Final_Review',
    '8_Published',
]


def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    conn = get_db()
    videos = conn.execute("SELECT * FROM Videos ORDER BY id DESC").fetchall()
    conn.close()
    return render_template('index.html', videos=videos)


# ---------------------------------------------------------------------------
# Add new idea
# ---------------------------------------------------------------------------

@app.route('/add', methods=['POST'])
def add_idea():
    idea = request.form.get('idea', '').strip()
    source_url = request.form.get('source_url', '').strip()
    niche = request.form.get('niche', 'finance').strip()
    channel = niche  # channel matches niche for now

    if idea:
        conn = get_db()
        record_id = shortuuid.uuid()
        conn.execute(
            """INSERT INTO Videos (record_id, Idea, Status, Source_URL, Niche, Channel)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (record_id, idea, '1_Idea_Review', source_url, niche, channel)
        )
        conn.commit()
        conn.close()
    return redirect(url_for('index'))


# ---------------------------------------------------------------------------
# Manual status update (approval buttons)
# ---------------------------------------------------------------------------

@app.route('/update_status/<record_id>/<new_status>')
def update_status(record_id, new_status):
    conn = get_db()
    conn.execute(
        "UPDATE Videos SET Status = ? WHERE record_id = ?",
        (new_status, record_id)
    )
    conn.commit()
    conn.close()
    return redirect(url_for('index'))


# ---------------------------------------------------------------------------
# Step 1: Generate script from source URL (runs in background)
# ---------------------------------------------------------------------------

def _run_generate_script(record_id: str, source_url: str, niche: str):
    """Background thread: fetch transcript → rewrite script → update DB."""
    try:
        from tools.fetch_transcript import fetch_transcript
        from tools.rewrite_script import rewrite_script

        conn = get_db()
        conn.execute(
            "UPDATE Videos SET Status = ? WHERE record_id = ?",
            ('2_Script_Pending', record_id)
        )
        conn.commit()
        conn.close()

        transcript = fetch_transcript(source_url)
        script = rewrite_script(transcript, niche)

        conn = get_db()
        conn.execute(
            "UPDATE Videos SET Transcript = ?, Script = ?, Status = ? WHERE record_id = ?",
            (transcript, script, '3_Script_Review', record_id)
        )
        conn.commit()
        conn.close()

    except Exception as e:
        conn = get_db()
        conn.execute(
            "UPDATE Videos SET Status = ? WHERE record_id = ?",
            (f'Failed_Script: {str(e)[:80]}', record_id)
        )
        conn.commit()
        conn.close()


@app.route('/generate_script/<record_id>')
def generate_script(record_id):
    conn = get_db()
    video = conn.execute(
        "SELECT * FROM Videos WHERE record_id = ?", (record_id,)
    ).fetchone()
    conn.close()

    if not video or not video['Source_URL']:
        return jsonify({'error': 'No source URL found for this video'}), 400

    thread = threading.Thread(
        target=_run_generate_script,
        args=(record_id, video['Source_URL'], video['Niche'] or 'finance')
    )
    thread.daemon = True
    thread.start()

    return redirect(url_for('index'))


# ---------------------------------------------------------------------------
# Step 2: Generate visual prompts from approved script (runs in background)
# ---------------------------------------------------------------------------

def _run_generate_prompts(record_id: str, script: str, niche: str):
    """Background thread: script → production packet → update DB."""
    try:
        from tools.generate_visual_prompts import generate_visual_prompts

        conn = get_db()
        conn.execute(
            "UPDATE Videos SET Status = ? WHERE record_id = ?",
            ('4_Prompts_Pending', record_id)
        )
        conn.commit()
        conn.close()

        prompts = generate_visual_prompts(script, niche)

        conn = get_db()
        conn.execute(
            "UPDATE Videos SET Visual_Prompts = ?, Status = ? WHERE record_id = ?",
            (prompts, '5_Prompts_Review', record_id)
        )
        conn.commit()
        conn.close()

    except Exception as e:
        conn = get_db()
        conn.execute(
            "UPDATE Videos SET Status = ? WHERE record_id = ?",
            (f'Failed_Prompts: {str(e)[:80]}', record_id)
        )
        conn.commit()
        conn.close()


@app.route('/generate_prompts/<record_id>')
def generate_prompts(record_id):
    conn = get_db()
    video = conn.execute(
        "SELECT * FROM Videos WHERE record_id = ?", (record_id,)
    ).fetchone()
    conn.close()

    if not video or not video['Script']:
        return jsonify({'error': 'No approved script found'}), 400

    thread = threading.Thread(
        target=_run_generate_prompts,
        args=(record_id, video['Script'], video['Niche'] or 'finance')
    )
    thread.daemon = True
    thread.start()

    return redirect(url_for('index'))


# ---------------------------------------------------------------------------
# View full script / production packet
# ---------------------------------------------------------------------------

@app.route('/view/<record_id>/<field>')
def view_field(record_id, field):
    allowed = {'Script', 'Visual_Prompts', 'Transcript'}
    if field not in allowed:
        return "Not allowed", 403

    conn = get_db()
    video = conn.execute(
        "SELECT * FROM Videos WHERE record_id = ?", (record_id,)
    ).fetchone()
    conn.close()

    content = video[field] if video else ''
    return render_template('view.html', title=field.replace('_', ' '), content=content, record_id=record_id, field=field)


# ---------------------------------------------------------------------------
# Workout video pipeline
# ---------------------------------------------------------------------------

@app.route('/add_workout', methods=['POST'])
def add_workout():
    title = request.form.get('title', '').strip()
    upper = request.form.get('upper_body', '').strip()
    lower = request.form.get('lower_body', '').strip()
    work_dur = int(request.form.get('work_duration', 40))
    rest_dur = int(request.form.get('rest_duration', 20))
    section_rest = int(request.form.get('section_rest', 60))

    if not title:
        return redirect(url_for('index'))

    sections = []
    if upper:
        exercises = [e.strip() for e in upper.split(',') if e.strip()]
        if exercises:
            sections.append({"name": "Upper Body", "exercises": exercises})
    if lower:
        exercises = [e.strip() for e in lower.split(',') if e.strip()]
        if exercises:
            sections.append({"name": "Lower Body", "exercises": exercises})

    import json
    plan = {
        "title": title,
        "sections": sections,
        "work_duration": work_dur,
        "rest_duration": rest_dur,
        "section_rest": section_rest
    }

    conn = get_db()
    record_id = shortuuid.uuid()
    conn.execute(
        """INSERT INTO Videos (record_id, Idea, Status, Niche, Channel, Video_Type, Workout_Plan)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (record_id, title, '1_Idea_Review', 'fitness', 'fitness', 'workout', json.dumps(plan))
    )
    conn.commit()
    conn.close()
    return redirect(url_for('index'))


def _run_build_workout(record_id: str, plan: dict):
    """Background thread: assemble workout video → update DB."""
    try:
        import json
        from tools.build_workout_video import build_workout_video

        os.makedirs('.tmp', exist_ok=True)
        output_path = f".tmp/workout_{record_id}.mp4"

        conn = get_db()
        conn.execute(
            "UPDATE Videos SET Status = ? WHERE record_id = ?",
            ('4_Prompts_Pending', record_id)
        )
        conn.commit()
        conn.close()

        build_workout_video(plan, output_path)

        conn = get_db()
        conn.execute(
            "UPDATE Videos SET Video_File_URL = ?, Status = ? WHERE record_id = ?",
            (output_path, '7_Final_Review', record_id)
        )
        conn.commit()
        conn.close()

    except Exception as e:
        conn = get_db()
        conn.execute(
            "UPDATE Videos SET Status = ? WHERE record_id = ?",
            (f'Failed_Build: {str(e)[:80]}', record_id)
        )
        conn.commit()
        conn.close()


@app.route('/build_workout/<record_id>')
def build_workout(record_id):
    import json
    conn = get_db()
    video = conn.execute(
        "SELECT * FROM Videos WHERE record_id = ?", (record_id,)
    ).fetchone()
    conn.close()

    if not video or not video['Workout_Plan']:
        return jsonify({'error': 'No workout plan found'}), 400

    plan = json.loads(video['Workout_Plan'])
    thread = threading.Thread(target=_run_build_workout, args=(record_id, plan))
    thread.daemon = True
    thread.start()

    return redirect(url_for('index'))


@app.route('/download/<record_id>')
def download_video(record_id):
    from flask import send_file
    conn = get_db()
    video = conn.execute(
        "SELECT * FROM Videos WHERE record_id = ?", (record_id,)
    ).fetchone()
    conn.close()

    if not video or not video['Video_File_URL']:
        return "No video file found", 404

    return send_file(video['Video_File_URL'], as_attachment=True,
                     download_name=f"{video['Idea']}.mp4")


if __name__ == '__main__':
    app.run(debug=True, port=5000)
