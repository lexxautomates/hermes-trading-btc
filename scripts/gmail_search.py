"""Read-only Gmail search. Prints matching messages; sends/modifies nothing."""
import base64
import json
import sys
from datetime import datetime, timedelta, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

TOKEN = r"C:\Users\alexa\AppData\Local\hermes\google_token.json"

creds = Credentials.from_authorized_user_file(TOKEN)
if not creds.valid and creds.refresh_token:
    creds.refresh(Request())
    with open(TOKEN, "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())

svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
prof = svc.users().getProfile(userId="me").execute()
print(f"# mailbox: {prof['emailAddress']}\n")

query = sys.argv[1] if len(sys.argv) > 1 else "newer_than:2d"
res = svc.users().messages().list(userId="me", q=query, maxResults=15).execute()
msgs = res.get("messages", [])
print(f"# query: {query!r} -> {len(msgs)} message(s)\n")


def body_text(payload) -> str:
    if payload.get("body", {}).get("data"):
        raw = payload["body"]["data"]
        return base64.urlsafe_b64decode(raw).decode("utf-8", "replace")
    for part in payload.get("parts", []) or []:
        if part.get("mimeType") == "text/plain":
            t = body_text(part)
            if t.strip():
                return t
    for part in payload.get("parts", []) or []:
        t = body_text(part)
        if t.strip():
            return t
    return ""


for m in msgs:
    full = svc.users().messages().get(userId="me", id=m["id"], format="full").execute()
    hdrs = {h["name"].lower(): h["value"] for h in full["payload"].get("headers", [])}
    print("=" * 72)
    print(f"FROM:    {hdrs.get('from','?')}")
    print(f"SUBJECT: {hdrs.get('subject','?')}")
    print(f"DATE:    {hdrs.get('date','?')}")
    text = body_text(full["payload"]).strip()
    text = "\n".join(ln for ln in text.splitlines() if ln.strip())
    print("-" * 72)
    print(text[:1800])
    print()
