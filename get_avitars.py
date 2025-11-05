import os
import requests
from dotenv import load_dotenv

# Load your API key
load_dotenv()
HEYGEN_API_KEY = os.getenv("HEYGEN_API_KEY")

# Set up the API endpoint and headers
url = "https://api.heygen.com/v2/avatars"
headers = {
    "accept": "application/json",
    "x-api-key": HEYGEN_API_KEY
}

print("Fetching your avatar list from HeyGen...")

try:
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        data = response.json()
        avatars = data['data']['avatars']

        print(f"\nSuccessfully found {len(avatars)} avatars:\n")

        for avatar in avatars:
            print("-----------------------------------")
            print(f"Name:    {avatar['avatar_name']}")
            print(f"Gender:  {avatar.get('gender', 'N/A')}")
            print(f"ID:      {avatar['avatar_id']}")
            print("-----------------------------------")

        print("\nCopy the 'ID' of the avatar you want to use and paste it into your main.py script.")

    else:
        print(f"Error: {response.status_code}")
        print(response.text)

except Exception as e:
    print(f"An error occurred: {e}")