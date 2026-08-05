import json
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly"
]

flow = InstalledAppFlow.from_client_secrets_file("../goggle.json", SCOPES)
creds = flow.run_local_server(port=0)

with open("gmail_user_credentials.json", "w") as f:
    f.write(creds.to_json())

print("Saved gmail_user_credentials.json")