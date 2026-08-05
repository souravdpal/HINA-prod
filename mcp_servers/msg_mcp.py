import os
import sys
import base64
from email.mime.text import MIMEText
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
core_dir = os.path.join(parent_dir, "core")
if core_dir not in sys.path:
    sys.path.insert(0, core_dir)

from core import hina_sdk
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Gmail MCP")

SCOPES = ["https://www.googleapis.com/auth/gmail.send",
          "https://www.googleapis.com/auth/gmail.readonly"]

def build_gmail_service():
    creds_data = os.environ.get("GMAIL_CREDENTIALS_JSON")
    if not creds_data:
        raise RuntimeError("GMAIL_CREDENTIALS_JSON missing")
    creds = Credentials.from_authorized_user_info(
        info=json.loads(creds_data), scopes=SCOPES
    )
    return build("gmail", "v1", credentials=creds)

def make_message(to, subject, body):
    msg = MIMEText(body)
    msg["to"] = to
    msg["subject"] = subject
    msg["from"] = "me"
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return {"raw": raw}

@mcp.tool()
def send_email(to: str, subject: str, body: str) -> str:
    service = build_gmail_service()
    message = make_message(to, subject, body)
    sent = service.users().messages().send(userId="me", body=message).execute()

    hina_sdk.send_state(
        agent_name="Gmail",
        state="sys_confirmed",
        msg=f"Email sent to {to}",
        text=f"Sent message with id {sent.get('id')}",
        icon="fa-solid fa-envelope",
        color="success",
        done=True,
    )
    return f"Sent email to {to}"

@mcp.tool()
def list_inbox(query: str = "is:unread", max_results: int = 5) -> dict:
    service = build_gmail_service()
    resp = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    ids = [m["id"] for m in resp.get("messages", [])]

    results = []
    for msg in service.users().messages().get(userId="me", id=msg_id, format="metadata", metadataHeaders=["Subject","From","Date"]).execute():
        headers = {h["name"]: h["value"] for h in results["payload"]["headers"]}
        results.append({
            "id": msg_id,
            "subject": headers.get("Subject"),
            "from": headers.get("From"),
            "date": headers.get("Date"),
        })

    hina_sdk.send_ui_json(
        data={"kind": "email_list", "emails": results},
        ui_type="email",
        agent_name="Gmail",
        state="sys_action",
        msg=f"Found {len(results)} messages",
        icon="fa-solid fa-envelope",
        color="tool",
        done=True,
    )

    return {"count": len(results), "messages": results}

if __name__ == "__main__":
    mcp.run()