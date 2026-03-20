# app.py
import os
import json
import sqlite3
import shortuuid
import threading
import logging
from flask import Flask, render_template, request, redirect, url_for, jsonify
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Logging — writes to console AND pipeline.log so you can tail -f it
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.StreamHandler(),                  # Flask terminal
        logging.FileHandler('pipeline.log'),      # tail -f pipeline.log
    ]
)
log = logging.getLogger('pipeline')

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


def migrate_db():
    """Add new columns to Videos table without dropping existing data."""
    conn = get_db()
    new_columns = [
        ('scene_data',       'TEXT'),
        ('auto_prod_status', 'TEXT'),
    ]
    for col, col_type in new_columns:
        try:
            conn.execute(f"ALTER TABLE Videos ADD COLUMN {col} {col_type}")
            conn.commit()
        except Exception:
            pass  # column already exists
    conn.close()


migrate_db()


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
    log.info(f"[{record_id[:8]}] START generate_script | niche={niche} url={source_url}")
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

        log.info(f"[{record_id[:8]}] Fetching transcript...")
        transcript = fetch_transcript(source_url)
        log.info(f"[{record_id[:8]}] Transcript fetched ({len(transcript)} chars). Rewriting...")
        script = rewrite_script(transcript, niche)
        log.info(f"[{record_id[:8]}] Script done ({len(script)} chars). Saving to DB.")

        conn = get_db()
        conn.execute(
            "UPDATE Videos SET Transcript = ?, Script = ?, Status = ? WHERE record_id = ?",
            (transcript, script, '3_Script_Review', record_id)
        )
        conn.commit()
        conn.close()
        log.info(f"[{record_id[:8]}] DONE generate_script → 3_Script_Review")

    except Exception as e:
        log.exception(f"[{record_id[:8]}] FAILED generate_script: {e}")
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
    log.info(f"[{record_id[:8]}] START generate_prompts | niche={niche}")
    try:
        from tools.generate_visual_prompts import generate_visual_prompts

        conn = get_db()
        conn.execute(
            "UPDATE Videos SET Status = ? WHERE record_id = ?",
            ('4_Prompts_Pending', record_id)
        )
        conn.commit()
        conn.close()

        log.info(f"[{record_id[:8]}] Calling generate_visual_prompts...")
        prompts = generate_visual_prompts(script, niche)
        log.info(f"[{record_id[:8]}] Prompts done ({len(prompts)} chars). Saving.")

        conn = get_db()
        conn.execute(
            "UPDATE Videos SET Visual_Prompts = ?, Status = ? WHERE record_id = ?",
            (prompts, '5_Prompts_Review', record_id)
        )
        conn.commit()
        conn.close()
        log.info(f"[{record_id[:8]}] DONE generate_prompts → 5_Prompts_Review")

    except Exception as e:
        log.exception(f"[{record_id[:8]}] FAILED generate_prompts: {e}")
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
# Voiceover generation
# ---------------------------------------------------------------------------

VOICE_OPTIONS = {
    "male_warm":          "en-US-GuyNeural",
    "male_casual":        "en-US-AndrewNeural",
    "male_authoritative": "en-US-ChristopherNeural",
    "female_friendly":    "en-US-JennyNeural",
    "female_expressive":  "en-US-AriaNeural",
}


def _run_generate_voiceover(record_id: str, script: str, voice: str):
    """Background thread: generate voiceover MP3 from script."""
    try:
        from tools.generate_voiceover import generate_voiceover

        os.makedirs('.tmp/audio', exist_ok=True)
        output_path = f".tmp/audio/{record_id}.mp3"

        generate_voiceover(script, output_path, voice)

        conn = get_db()
        conn.execute(
            "UPDATE Videos SET Audio_File_URL = ? WHERE record_id = ?",
            (output_path, record_id)
        )
        conn.commit()
        conn.close()

    except Exception as e:
        conn = get_db()
        conn.execute(
            "UPDATE Videos SET Status = ? WHERE record_id = ?",
            (f'Failed_Audio: {str(e)[:80]}', record_id)
        )
        conn.commit()
        conn.close()


@app.route('/generate_voiceover/<record_id>', methods=['POST'])
def generate_voiceover_route(record_id):
    voice = request.form.get('voice', 'en-US-GuyNeural')
    conn = get_db()
    video = conn.execute(
        "SELECT * FROM Videos WHERE record_id = ?", (record_id,)
    ).fetchone()
    conn.close()

    if not video or not video['Script']:
        return jsonify({'error': 'No script found'}), 400

    thread = threading.Thread(
        target=_run_generate_voiceover,
        args=(record_id, video['Script'], voice)
    )
    thread.daemon = True
    thread.start()

    return redirect(url_for('index'))


@app.route('/download_audio/<record_id>')
def download_audio(record_id):
    from flask import send_file
    conn = get_db()
    video = conn.execute(
        "SELECT * FROM Videos WHERE record_id = ?", (record_id,)
    ).fetchone()
    conn.close()

    if not video or not video['Audio_File_URL']:
        return "No audio file found", 404

    return send_file(
        video['Audio_File_URL'],
        as_attachment=True,
        download_name=f"{video['Idea']}_voiceover.mp3"
    )


# ---------------------------------------------------------------------------
# Auto-produce: DALL-E 3 images + fal.ai Kling clips + sync assembly
# ---------------------------------------------------------------------------

def _run_auto_produce(record_id: str, script: str):
    """
    Background thread: full zero-manual Finance video pipeline.

    Phases tracked in auto_prod_status:
      pending       → generating DALL-E 3 images
      images_done   → generating ElevenLabs audio
      audio_done    → generating Kling animated clips (i2v)
      clips_done    → applying Kling lipsync
      lipsync_done  → assembling final video
      assembling    → rendering MP4
      done          → complete (→ 7_Final_Review)
      failed        → error (see Status column for detail)
    """
    try:
        from tools.automated_asset_generator import generate_assets
        from tools.sync_assembler import assemble_finance_video
        import json

        # Kick off — status already set by the route
        scenes = generate_assets(record_id, script)

        # Assemble
        conn = get_db()
        conn.execute(
            "UPDATE Videos SET auto_prod_status = ? WHERE record_id = ?",
            ('assembling', record_id)
        )
        conn.commit()
        conn.close()

        os.makedirs('.tmp', exist_ok=True)
        output_path = f".tmp/finance_{record_id}.mp4"
        assemble_finance_video(
            scenes,
            output_path,
            tmp_dir=f".tmp/finance_assembly_{record_id}",
        )

        conn = get_db()
        conn.execute(
            "UPDATE Videos SET Video_File_URL = ?, Status = ?, auto_prod_status = ? WHERE record_id = ?",
            (output_path, '7_Final_Review', 'done', record_id)
        )
        conn.commit()
        conn.close()

    except Exception as e:
        conn = get_db()
        conn.execute(
            "UPDATE Videos SET Status = ?, auto_prod_status = ? WHERE record_id = ?",
            (f'Failed_AutoProd: {str(e)[:80]}', 'failed', record_id)
        )
        conn.commit()
        conn.close()
        raise


@app.route('/auto_produce/<record_id>')
def auto_produce(record_id):
    conn = get_db()
    video = conn.execute(
        "SELECT * FROM Videos WHERE record_id = ?", (record_id,)
    ).fetchone()
    conn.close()

    if not video or not video['Script']:
        return jsonify({'error': 'No approved script found'}), 400

    # Set initial status immediately so the dashboard reacts
    conn = get_db()
    conn.execute(
        "UPDATE Videos SET Status = ?, auto_prod_status = ? WHERE record_id = ?",
        ('4_Prompts_Pending', 'pending', record_id)
    )
    conn.commit()
    conn.close()

    thread = threading.Thread(
        target=_run_auto_produce,
        args=(record_id, video['Script'])
    )
    thread.daemon = True
    thread.start()

    return redirect(url_for('index'))


@app.route('/api/auto_prod_status/<record_id>')
def api_auto_prod_status(record_id):
    conn = get_db()
    row = conn.execute(
        "SELECT Status, auto_prod_status FROM Videos WHERE record_id = ?",
        (record_id,)
    ).fetchone()
    conn.close()
    if not row:
        return jsonify({'status': 'unknown', 'auto_prod_status': None})
    return jsonify({
        'status':           row['Status'],
        'auto_prod_status': row['auto_prod_status'],
    })


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
    rounds = int(request.form.get('rounds', 1))
    round_rest = int(request.form.get('round_rest', 30))
    is_short = request.form.get('is_short') == '1'

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
        "section_rest": section_rest,
        "rounds": rounds,
        "round_rest": round_rest,
        "is_short": is_short
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
    exercises = [e for s in plan.get('sections', []) for e in s.get('exercises', [])]
    log.info(f"[{record_id[:8]}] START build_workout | {len(exercises)} exercises, is_short={plan.get('is_short')}")
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

        log.info(f"[{record_id[:8]}] Calling build_workout_video → {output_path}")
        build_workout_video(plan, output_path, record_id=record_id, is_short=plan.get('is_short', False))
        log.info(f"[{record_id[:8]}] build_workout_video complete.")

        conn = get_db()
        conn.execute(
            "UPDATE Videos SET Video_File_URL = ?, Status = ? WHERE record_id = ?",
            (output_path, '7_Final_Review', record_id)
        )
        conn.commit()
        conn.close()
        log.info(f"[{record_id[:8]}] DONE build_workout → 7_Final_Review")

    except Exception as e:
        log.exception(f"[{record_id[:8]}] FAILED build_workout: {e}")
        conn = get_db()
        conn.execute(
            "UPDATE Videos SET Status = ? WHERE record_id = ?",
            (f'Failed_Build: {str(e)[:80]}', record_id)
        )
        conn.commit()
        conn.close()


@app.route('/exercise_prompts/<record_id>')
def exercise_prompts(record_id):
    conn = get_db()
    video = conn.execute(
        "SELECT * FROM Videos WHERE record_id = ?", (record_id,)
    ).fetchone()
    conn.close()

    if not video or not video['Workout_Plan']:
        return "No workout plan found", 400

    plan = json.loads(video['Workout_Plan'])
    exercises = []
    for section in plan.get('sections', []):
        exercises.extend(section.get('exercises', []))

    from tools.generate_exercise_prompts import generate_exercise_prompts
    prompts = generate_exercise_prompts(exercises)
    return render_template('view.html', title='Exercise Image Prompts', content=prompts,
                           record_id=record_id, field='exercise_prompts')


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


@app.route('/api/status/<record_id>')
def api_status(record_id):
    conn = get_db()
    row = conn.execute(
        "SELECT Status FROM Videos WHERE record_id = ?", (record_id,)
    ).fetchone()
    conn.close()
    return jsonify({"status": row["Status"] if row else "unknown"})


@app.route('/api/progress/<record_id>')
def render_progress(record_id):
    import glob
    path = f".tmp/workout_{record_id}/progress.json"
    matches = glob.glob(path)
    if matches:
        try:
            with open(matches[0]) as f:
                data = json.load(f)
            log.info(f"[{record_id[:8]}] /api/progress → pct={data.get('pct')} index={data.get('index')}/{data.get('total')}")
            return jsonify(data)
        except Exception as e:
            log.warning(f"[{record_id[:8]}] /api/progress failed to read {path}: {e}")
    else:
        log.info(f"[{record_id[:8]}] /api/progress → no progress.json yet at {path}")
    return jsonify({"pct": 0})


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
