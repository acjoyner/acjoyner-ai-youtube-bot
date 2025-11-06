import os
import time
import requests
import openai
import boto3
from dotenv import load_dotenv
from pyairtable import Table, Api
from elevenlabs import save
from elevenlabs.client import ElevenLabs
import ffmpeg  #
from google.cloud import texttospeech
import youtube_uploader
import sqlite3

# --- 1. INITIAL SETUP & LOAD ENV ---
# ---------------------------------
load_dotenv()

# Load all API keys from .env
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
HEYGEN_API_KEY = os.getenv("HEYGEN_API_KEY")
AIRTABLE_PAT = os.getenv("AIRTABLE_PAT")  # <-- Updated variable name
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
AIRTABLE_TABLE_NAME = os.getenv("AIRTABLE_TABLE_NAME")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_S3_BUCKET_NAME = os.getenv("AWS_S3_BUCKET_NAME")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_APPLICATION_CREDENTIALS
# --- 2. CONFIGURE CLIENTS ---
# ----------------------------
print("Initializing all clients...")

# Airtable (using modern Personal Access Token)
# Airtable (modern setup)
api = Api(AIRTABLE_PAT)
table = api.table(AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME)
# OpenAI
openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
# Google Cloud TTS
tts_client = texttospeech.TextToSpeechClient()
# ElevenLabs
elevenlabs_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

# AWS S3
# s3_client = boto3.client(
#     's3',
#     aws_access_key_id=AWS_ACCESS_KEY_ID,
#     aws_secret_access_key=AWS_SECRET_ACCESS_KEY
# )

# HeyGen (using simple requests)
# HEYGEN_API_URL = "https://api.heygen.com/v2"
# HEYGEN_HEADERS = {
#     "accept": "application/json",
#     "content-type": "application/json",
#     "x-api-key": HEYGEN_API_KEY
# }

print("Clients initialized.")


# --- 3. HELPER FUNCTIONS (File Handling) ---
# -----------------------------------------
# def upload_to_s3(file_path, s3_key):
#     """Uploads a local file to S3 and returns the URL."""
#     try:
#         s3_client.upload_file(file_path, AWS_S3_BUCKET_NAME, s3_key)
#         url = s3_client.generate_presigned_url(
#             'get_object',
#             Params={'Bucket': AWS_S3_BUCKET_NAME, 'Key': s3_key},
#             ExpiresIn=604800  # 7 days
#         )
#         print(f"Successfully uploaded {file_path} to S3.")
#         return url
#     except Exception as e:
#         print(f"Error uploading to S3: {e}")
#         return None

#
# def download_from_s3(s3_key, local_path):
#     """Downloads a file from S3 to a local path."""
#     try:
#         s3_client.download_file(AWS_S3_BUCKET_NAME, s3_key, local_path)
#         print(f"Successfully downloaded {s3_key} from S3 to {local_path}.")
#         return local_path
#     except Exception as e:
#         print(f"Error downloading from S3: {e}")
#         return None


# --- 4. WORKFLOW STEP FUNCTIONS ---
# --------------------------------
def process_step_1_scripting(record):
    """Generates a script and moves record to review."""
    record_id = record[1]  # Get the record_id
    idea = record[2]  # Get the Idea
    print(f"Processing STEP 1 for: {idea}")

    try:
        completion = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system",
                 "content": "You are a helpful assistant that writes engaging YouTube video scripts."},
                {"role": "user", "content": f"Write a 3-minute video script based on this idea: {idea}"}
            ]
        )
        script = completion.choices[0].message.content

        # --- NEW SQL UPDATE ---
        conn = sqlite3.connect('youtube.db')
        conn.execute("UPDATE Videos SET Script = ?, Status = '2_Script_Review' WHERE record_id = ?",
                     (script, record_id))
        conn.commit()
        conn.close()
        # --- END OF UPDATE ---

        print(f"Script generated for {idea}. Moved to '2_Script_Review'.")

    except Exception as e:
        print(f"Error in scripting step: {e}")
        # --- NEW SQL UPDATE ---
        conn = sqlite3.connect('youtube.db')
        conn.execute("UPDATE Videos SET Status = 'Failed - Asset Gen' WHERE record_id = ?", (record_id,))
        conn.commit()
        conn.close()
        # --- END OF UPDATE ---


def upload_local_asset_to_heygen(local_file_path, content_type="audio/mpeg"):
    """Uploads a local file directly to HeyGen and returns the asset_id."""
    print(f"Uploading {local_file_path} directly to HeyGen...")
    url = "https://upload.heygen.com/v1/asset"

    headers = {"x-api-key": HEYGEN_API_KEY, "Content-Type": content_type}

    with open(local_file_path, 'rb') as f:
        data = f.read()

    response = requests.post(url, headers=headers, data=data)
    if response.status_code == 200:
        asset_id = response.json()['data']['id']
        print(f"HeyGen asset created successfully. Asset ID: {asset_id}")
        return asset_id
    else:
        print(f"Error uploading asset to HeyGen: {response.text}")
        return None


def process_step_3_and_4_video_gen(record):
    """Generates a real video with a blank screen and AI audio."""
    record_id = record[1]
    idea = record[2]
    script = record[5]  # Get the script from the database
    print(f"Processing REAL Video Step for: {idea}")

    # Define our temporary and final file paths
    local_audio_path = f"temp_audio_{record_id}.mp3"
    temp_video_path = f"temp_video_{record_id}.mp4"

    if not os.path.exists('final_videos'):
        os.makedirs('final_videos')
    final_video_path = f"final_videos/REAL_VIDEO_{record_id}.mp4"

    try:
        # Check if the script is empty. If so, fail early.
        if not script:
            raise Exception("Script field is empty, cannot generate audio.")

        # --- Step 1: Generate real audio (Using Google Cloud TTS) ---
        print("Generating real audio file using Google Cloud TTS...")
        synthesis_input = texttospeech.SynthesisInput(text=script)
        voice = texttospeech.VoiceSelectionParams(
            language_code="en-US", name="en-US-WaveNet-D"
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3
        )
        response = tts_client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )
        with open(local_audio_path, "wb") as out:
            out.write(response.audio_content)
        print(f"Generated real audio file: {local_audio_path}")

        # --- Step 2: Get audio duration ---
        duration = get_audio_duration(local_audio_path)
        if duration is None:
            raise Exception("Could not get audio duration.")

        # --- Step 3: Create blank video of same duration ---
        if not create_blank_video(duration, temp_video_path):
            raise Exception("Could not create blank video.")

        # --- Step 4: Merge audio and video ---
        if not merge_audio_and_video(temp_video_path, local_audio_path, final_video_path):
            raise Exception("Could not merge audio and video.")
        print(f"Created final video file: {final_video_path}")

        # --- Step 5: Update Database (ONLY ON SUCCESS) ---
        conn = sqlite3.connect('youtube.db')
        conn.execute(
            "UPDATE Videos SET Audio_File_URL = ?, Video_File_URL = ?, Status = '5_Final_Review' WHERE record_id = ?",
            (local_audio_path, final_video_path, record_id)
        )
        conn.commit()
        conn.close()
        print(f"Real video generation complete. Moved to '5_Final_Review'.")

    except Exception as e:
        print(f"Error in video gen step: {e}")
        # --- (FIXED) Set status to FAILED ---
        conn = sqlite3.connect('youtube.db')
        conn.execute("UPDATE Videos SET Status = 'Failed - Asset Gen' WHERE record_id = ?", (record_id,))
        conn.commit()
        conn.close()

    finally:
        # --- Step 6: Clean up temp files ---
        if os.path.exists(local_audio_path):
            os.remove(local_audio_path)
        if os.path.exists(temp_video_path):
            os.remove(temp_video_path)
        print("Temporary files cleaned up.")


# --- REPLACE your old process_step_6_upload function with this ---

def process_step_6_upload(record):
    """Uploads video to YouTube from a local file."""

    # --- Get data from the database record ---
    # record[1] = record_id
    # record[2] = Idea
    # record[4] = Title
    # record[6] = Description
    # record[8] = Video_File_URL

    record_id = record[1]
    idea = record[2]
    local_path = record[8]
    # Use the 'Title' field if it's filled, otherwise use the 'Idea' as a fallback
    title = record[4] if record[4] else idea
    # Use the 'Description' field if it's filled, otherwise use a default
    description = record[6] if record[6] else "Video created with AI."

    print(f"Processing STEP 6 (Upload) for: {idea}")

    try:
        if not local_path or not os.path.exists(local_path):
            raise Exception(f"Video file not found at local path: {local_path}")

        # --- THIS IS THE FIXED CALL ---
        youtube_id = youtube_uploader.upload_video(
            file_path=local_path,
            title=title,
            description=description,
            tags=["ai", "automation", "python", "tech"],  # You can customize tags here
            privacy_status="private"
        )
        # --- END OF FIX ---

        if youtube_id:
            conn = sqlite3.connect('youtube.db')
            conn.execute("UPDATE Videos SET YouTube_ID = ?, Status = '7_Uploaded' WHERE record_id = ?",
                         (youtube_id, record_id))
            conn.commit()
            conn.close()
            print(f"Uploaded to YouTube (ID: {youtube_id}). Moved to '7_Uploaded'.")
        else:
            raise Exception("YouTube upload returned None.")

    except Exception as e:
        print(f"Error in Step 6: {e}")
        conn = sqlite3.connect('youtube.db')
        conn.execute("UPDATE Videos SET Status = 'Failed - YouTube Upload' WHERE record_id = ?", (record_id,))
        conn.commit()
        conn.close()


# --- 5. MAIN ORCHESTRATOR LOOP ---
# --------------------------------
# --- 5. MAIN ORCHESTRATOR LOOP ---
# --------------------------------
def main_loop():
    print("\n--- Orchestrator starting main loop ---")

    conn = sqlite3.connect('youtube.db')
    cursor = conn.cursor()

    try:
        # Step 1: Scripting
        cursor.execute("SELECT * FROM Videos WHERE Status = '1_Script_Pending'")
        records_to_script = cursor.fetchall()
        for record in records_to_script:
            process_step_1_scripting(record)

        # Step 3 & 4: REAL video generation
        cursor.execute("SELECT * FROM Videos WHERE Status = '3_Asset_Gen_Pending'")
        records_to_gen = cursor.fetchall()
        for record in records_to_gen:
            process_step_3_and_4_video_gen(record)

        # Step 6: Upload to YouTube
        cursor.execute("SELECT * FROM Videos WHERE Status = '6_Upload_Pending'")
        records_to_upload = cursor.fetchall()
        for record in records_to_upload:
            process_step_6_upload(record)

    except Exception as e:
        print(f"An error occurred in the main loop: {e}")
    finally:
        conn.close()  # Close the database connection

    print("--- Loop complete. Waiting... ---")


# ... (rest of your script) ...

# Helper functions
# --- REPLACE your old function with this one ---
def get_audio_duration(file_path):
    """Gets the duration of an audio file in seconds using ffmpeg.probe."""
    try:
        print(f"Probing audio duration for: {file_path}")
        probe = ffmpeg.probe(file_path)
        duration = float(probe['format']['duration'])
        print(f"Audio duration: {duration} seconds")
        return duration
    except Exception as e:
        print(f"Error getting audio duration: {e}")
        return None
# --- End of replacement ---

def create_blank_video(duration, output_path):
    """Creates a silent, black-screen video of a specific duration."""
    print(f"Creating blank video ({duration}s) at {output_path}...")
    try:
        (
            ffmpeg
            .input('color=c=black:s=1920x1080:d=' + str(duration), format='lavfi')
            .output(output_path, vcodec='libx264', pix_fmt='yuv420p', an=None) # an=None means no audio
            .run(overwrite_output=True, capture_stdout=True, capture_stderr=True)
        )
        print("Blank video created.")
        return True
    except ffmpeg.Error as e:
        print("Error creating blank video:")
        print(e.stderr.decode())
        return False

def merge_audio_and_video(video_path, audio_path, output_path):
    """Merges an audio file and video file into one."""
    print(f"Merging {audio_path} and {video_path} into {output_path}...")
    try:
        input_video = ffmpeg.input(video_path)
        input_audio = ffmpeg.input(audio_path)

        # This is the corrected command.
        # We take the video stream from the video file and the audio stream from the audio file
        # and output them to a new file.
        (
            ffmpeg
            .output(
                input_video.video,  # Take video from the first input
                input_audio.audio,  # Take audio from the second input
                output_path,        # The final file path
                vcodec='copy',      # We can copy the video (it's already encoded)
                acodec='aac'        # We need to re-encode the audio from MP3 to AAC
            )
            .run(overwrite_output=True, capture_stdout=True, capture_stderr=True)
        )
        print("Merge complete.")
        return True
    except ffmpeg.Error as e:
        print("Error merging files:")
        print(e.stderr.decode())
        return False
if __name__ == "__main__":
    while True:
        main_loop()
        time.sleep(60)
