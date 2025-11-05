# youtube_uploader.py
import google.oauth2.credentials
import google_auth_oauthlib.flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
import os
import httplib2

# Define the scopes and API details
SCOPES = ['https://www.googleapis.com/auth/youtube.upload']
API_SERVICE_NAME = 'youtube'
API_VERSION = 'v3'
TOKEN_FILE = 'token.json'
CLIENT_SECRETS_FILE = 'client_secrets.json'  # Needed if token is invalid


def get_authenticated_service():
    """
    Loads existing credentials or refreshes them.
    Returns an authenticated service object.
    """
    credentials = None

    # --- 1. Load credentials from 'token.json' ---
    if os.path.exists(TOKEN_FILE):
        try:
            credentials = google.oauth2.credentials.Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception as e:
            print(f"Error loading {TOKEN_FILE}: {e}")
            credentials = None  # Force re-auth or refresh

    # --- 2. If no valid credentials, refresh or re-run auth ---
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            # If token is expired, refresh it
            print("Refreshing access token...")
            try:
                credentials.refresh(Request())
            except Exception as e:
                print(f"Error refreshing token: {e}")
                print("Could not refresh token. You may need to run authenticate.py again.")
                return None
        else:
            # This is a fallback, but authenticate.py should be run first.
            print(f"Cannot find valid credentials. Run 'authenticate.py' first.")
            return None

        # --- 3. Save the new (refreshed) credentials ---
        with open(TOKEN_FILE, 'w') as token:
            token.write(credentials.to_json())

    # --- 4. Build and return the service object ---
    # Disable httplib2 caching
    httplib2.Http(cache=None)
    return build(API_SERVICE_NAME, API_VERSION, credentials=credentials)


def upload_video(file_path, title, description, tags, privacy_status="private"):
    """
    Uploads a video to YouTube.

    Args:
        file_path (str): The local path to the video file.
        title (str): The video title.
        description (str): The video description.
        tags (list): A list of string tags.
        privacy_status (str): "public", "private", or "unlisted".
    """
    try:
        service = get_authenticated_service()
        if service is None:
            raise Exception("Failed to get authenticated YouTube service.")

        body = {
            'snippet': {
                'title': title,
                'description': description,
                'tags': tags,
                'categoryId': '22'  # '22' is "People & Blogs". Change if needed.
            },
            'status': {
                'privacyStatus': privacy_status
            }
        }

        print(f"Uploading video '{title}' from {file_path}...")

        # Create the media file upload object
        media = MediaFileUpload(file_path,
                                chunksize=-1,  # -1 = upload in a single request
                                resumable=True)  # Allows for resumable uploads

        # Make the API request
        request = service.videos().insert(
            part=','.join(body.keys()),
            body=body,
            media_body=media
        )

        # Execute the upload (with a loop for resumable status)
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"Uploaded {int(status.progress() * 100)}%")

        print(f"Upload successful! Video ID: {response['id']}")
        return response['id']

    except Exception as e:
        print(f"An error occurred during upload: {e}")
        return None