#!/usr/bin/env python3
"""
Gmail OAuth2 / API reading, tested without touching the real account.

Google's answers are replayed from canned responses, so this proves the parsing
is right (headers, base64url body, date, the shape the rest of the agent
expects) without needing live credentials.

Run:  python tests/test_gmail_oauth.py
"""
import base64
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# keep this test away from any real token or mailbox
os.environ["DB_PATH"] = os.path.join(HERE, "gmail_test.db")
os.environ["RISK_MODEL_PATH"] = os.path.join(HERE, "risk_gmail.npz")
os.environ["GMAIL_CLIENT_ID"] = "test.apps.googleusercontent.com"
os.environ["GMAIL_CLIENT_SECRET"] = "test-secret"

import gmail_oauth as G                                  # noqa: E402

ok = fail = 0


def check(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {label} {extra}")
    else:
        fail += 1
        print(f"  FAIL  {label} {extra}")


def b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


BODY = ("Your appointment is confirmed for visa application file identified by "
        "code E24712502281412 at Colombo, for 20.10.2026,2.30PM You can consult "
        "the coordinates of your visa application file at any time.")

LISTING = {"messages": [{"id": "msg-1", "threadId": "t1"},
                        {"id": "msg-2", "threadId": "t2"}]}


def make_message(mid, subject, body, sender="MAE@evisa.ro"):
    return {
        "id": mid,
        "internalDate": "1760750400000",            # 2025-10-18 ish
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
                {"name": "Message-ID", "value": f"<{mid}@evisa.ro>"},
            ],
            "mimeType": "text/plain",
            "body": {"data": b64(body)},
        },
    }


print("\n=== 1. it knows when it is not connected ===")
check("no token means not configured", G.is_configured() is False)
check("status runs without a token", G._status() is False)

print("\n=== 2. the consent URL is built correctly ===")
url = G.auth_url()
check("it goes to Google", url.startswith("https://accounts.google.com/"), url[:40])
for want in ("response_type=code", "access_type=offline", "prompt=consent",
             "redirect_uri="):
    check(f"URL has {want}", want in url)

print("\n=== 3. reading the mailbox (Google's answers replayed) ===")
calls = []


def fake_get(path, token):
    calls.append(path)
    if path.startswith("/messages?"):
        return LISTING
    if path.startswith("/messages/msg-1?"):
        return make_message("msg-1",
                            "Appointment confirmation for application file "
                            "E24712502281412.", BODY)
    if path.startswith("/messages/msg-2?"):
        return make_message("msg-2", "Your E24712502281412 file was decided upon",
                            "The file was decided upon. Please collect it.")
    return {}


G._api_get = fake_get
G.access_token = lambda: "fake-token"

msgs = G.fetch_new_emails(limit=5, since_days=30, mark_seen=False)

check("both messages came back", len(msgs) == 2, str(len(msgs)))
check("the shape matches what email_monitor returns",
      all({"uid", "message_id", "subject", "body", "sender", "received_at"} <= set(m)
          for m in msgs))
m0 = msgs[0]
check("subject read", "E24712502281412" in m0["subject"], m0["subject"][:50])
check("sender read", m0["sender"] == "MAE@evisa.ro", m0["sender"])
check("body decoded", "20.10.2026" in m0["body"], m0["body"][:50])
check("the PM time survived - the thing that went wrong before",
      "2.30PM" in m0["body"], [t for t in ("2.30PM",) if t in m0["body"]])
check("received_at is a datetime", hasattr(m0["received_at"], "year"),
      str(m0["received_at"]))
check("the sender filter was passed to Google",
      any("from:MAE" in c or "from%3AMAE" in c for c in calls), calls[0][:70])

print("\n=== 4. it can also read HTML mail ===")
HTML_MSG = {
    "id": "h", "internalDate": "1760750400000",
    "payload": {"headers": [{"name": "Subject", "value": "html"}],
                "mimeType": "text/html",
                "body": {"data": b64("<p>Appointment at <b>2.30PM</b></p>")}}}


def fake_html(path, token):
    # the first call lists messages, the second fetches one
    return {"messages": [{"id": "h"}]} if path.startswith("/messages?") else HTML_MSG


G._api_get = fake_html
h = G.fetch_new_emails(limit=1, since_days=7, mark_seen=False)
check("html is turned into text", h and "2.30PM" in h[0]["body"],
      (h[0]["body"][:40] if h else "nothing"))

print("\n=== 5. the parsed result feeds the real pipeline ===")
try:
    from email_parsers import parse_email
    r = parse_email(msgs[0]["subject"], msgs[0]["body"], sender=msgs[0]["sender"])
    check("the appointment parses", r.get("kind") == "appointment", str(r.get("kind")))
    check("the E-number is right", r.get("e_number") == "E24712502281412",
          str(r.get("e_number")))
    check("2.30PM was stored as 14:30, not 02:30",
          r.get("appointment_time") == "14:30", str(r.get("appointment_time")))
except Exception as e:
    check("the appointment parses", False, f"{type(e).__name__}: {e}")

print(f"\n{'=' * 62}\n  {ok} passed, {fail} failed\n{'=' * 62}\n")
sys.exit(1 if fail else 0)
