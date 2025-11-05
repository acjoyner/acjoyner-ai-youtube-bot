# authenticate.py
import google.oauth2.credentials
import google_auth_oauthlib.flow
from googleapiclient.discovery import build

# This scope allows for uploading videos.
SCOPES = ['https://www.googleapis.com/auth/youtube.upload']
API_SERVICE_NAME = 'youtube'
API_VERSION = 'v3'
CLIENT_SECRETS_FILE = 'client_secrets.json'


def get_authenticated_service():
    """
    Authenticates the user and returns a service object.

    This function will open a web browser for the user to
    authorize the application. It stores credentials in 'token.json'.
    """
    flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, SCOPES)

    # This will open a browser window for you to log in
    credentials = flow.run_local_server(port=0)

    # Save the credentials for the next run
    with open('token.json', 'w') as token:
        token.write(credentials.to_json())

    return build(API_SERVICE_NAME, API_VERSION, credentials=credentials)


if __name__ == '__main__':
    print("Starting authentication process...")
    print("A browser window will open. Please log in and grant permissions.")

    service = get_authenticated_service()

    print("\nAuthentication successful!")
    print("Credentials saved to 'token.json'.")
    print("You can now run the main orchestrator script.")