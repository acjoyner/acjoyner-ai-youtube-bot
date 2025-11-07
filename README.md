# AI-Powered YouTube Automation Pipeline (SQLite Edition)

This project is a "Human-in-the-Loop" (HITL) automation pipeline for creating and uploading YouTube videos. It uses a local **SQLite database** as a job queue and **Python** as the orchestrator.

- **Database:** A local SQLite file (`youtube.db`) manages the video queue.
- **AI Scripting:** Uses **OpenAI** (GPT-4o) to generate scripts from an "Idea".
- **AI Voiceover:** Uses **Google Cloud Text-to-Speech** for high-quality, realistic audio.
- **Video Generation:** Uses **FFmpeg** to create a 1080p video file by merging the AI audio with a blank, black screen.
- **Uploading:** Automatically uploads the final, human-approved video to YouTube via the **YouTube Data API**.

## Workflow

1.  **One-Time Setup:** Run `python setup_database.py` to create your `youtube.db` file.
2.  **Add an Idea:** Run `python add_idea.py` to add a new video idea to the queue. The `Status` is automatically set to `1_Script_Pending`.
3.  **Run the Orchestrator:** In your terminal, run the main script: `python main.py`.
4.  **Script Runs (Step 1):** The script finds the new job, uses OpenAI to generate a script, and updates the `Status` to `2_Script_Review`.
5.  **Your Review (Human):** You open the `youtube.db` file (using a tool like **DB Browser for SQLite**) and review the script. If you approve, you manually change the `Status` to **`3_Asset_Gen_Pending`** and save.
6.  **Script Runs (Step 3):** The script finds the approved job, generates the audio with Google Cloud TTS, creates a blank MP4, merges them, and saves the final video to the `final_videos/` folder. It sets the `Status` to **`5_Final_Review`**.
7.  **Your Review (Human):** You go to the `final_videos/` folder and watch the `REAL_VIDEO_...mp4` file.
8.  **Trigger Upload:** If you approve the video, go back to your database browser, set the `Status` to **`6_Upload_Pending`**, and save.
9.  **Script Runs (Step 6):** The script finds the approved video, uploads it to YouTube, saves the new `YouTube_ID` to the database, and sets the `Status` to **`7_Uploaded`**.

## 🧰 Setup & Prerequisites

You must complete these steps before the script will work.

### 1. Install FFmpeg
The script depends on the FFmpeg command-line tool.
* **macOS (Homebrew):** `brew install ffmpeg`
* **Windows (Chocolatey):** `choco install ffmpeg`
* **Linux (apt):** `sudo apt install ffmpeg`

### 2. Install a Database Browser (Recommended)
You need a free tool to see and edit your `youtube.db` file.
* **Download:** **[DB Browser for SQLite](https://sqlitebrowser.org/dl/)**

### 3. Install Python Libraries
Create a virtual environment (`venv`) and install all required packages.

```bash
pip install openai google-cloud-texttospeech ffmpeg-python requests python-dotenv google-api-python-client google-auth-oauthlib shortuuid