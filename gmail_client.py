import os
import base64
import json
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
TOKEN_FILE = "token.json"
CREDENTIALS_FILE = "credentials.json"


def get_gmail_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def search_emails(service, query, max_results=500):
    """Search Gmail and return list of message dicts with id and threadId."""
    messages = []
    page_token = None
    while True:
        kwargs = {"userId": "me", "q": query, "maxResults": min(max_results - len(messages), 100)}
        if page_token:
            kwargs["pageToken"] = page_token
        result = service.users().messages().list(**kwargs).execute()
        batch = result.get("messages", [])
        messages.extend(batch)
        page_token = result.get("nextPageToken")
        if not page_token or len(messages) >= max_results:
            break
    return messages


def get_email_body(service, msg_id):
    """Return (subject, date_header, html_body, plain_body) for a message."""
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
    subject = headers.get("Subject", "")
    date_header = headers.get("Date", "")

    html_body = ""
    plain_body = ""

    def extract_parts(payload):
        nonlocal html_body, plain_body
        mime = payload.get("mimeType", "")
        body_data = payload.get("body", {}).get("data", "")
        if body_data:
            decoded = base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="replace")
            if mime == "text/html":
                html_body = decoded
            elif mime == "text/plain":
                plain_body = decoded
        for part in payload.get("parts", []):
            extract_parts(part)

    extract_parts(msg["payload"])
    return subject, date_header, html_body, plain_body
