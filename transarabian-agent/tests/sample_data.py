"""
sample_data.py - real-world shaped fixtures for rehearsing the pipeline.

Samples 1-2 are the two e-mail families taken from the screenshots you supplied
(they are NOT in the pending-persons sheet, so they exercise the "ask a human"
path). Samples 3-9 use E-numbers that DO exist in the sheet, so the whole
formatting path (interview list per day + collection list + Sinhala notice)
can be checked end to end without sending anything.
"""
import os
from datetime import datetime

SAMPLES = [
    # ---------------------------------------------------------------- real #1
    {
        "uid": "appt-001",
        "message_id": "<sample-appt-001@mae.evisa.ro>",
        "sender": "MAE@evisa.ro",
        "subject": "Appointment confirmation for application file E24275493641672.",
        "body": (
            "Your appointment is confirmed for visa application file identified by code "
            "E24275493641672 at Colombo, for 15.10.2026,10:00\n"
            "You can consult the coordinates of your visa application file at any time, by "
            "accessing the following link: E24275493641672\n"
            "Please arrive on time for your chosen appointment with your printed visa "
            "application file including the documents required through your application form, "
            "organized as uploaded. It is recommended that you do not arrive at our "
            "Embassy/Consular Section too early given that it is possible you are attended to "
            "only around the time of your scheduled appointment."
        ),
        "received_at": "2026-09-28T11:19:00",
    },
    # ---------------------------------------------------------------- real #2
    {
        "uid": "dec-001",
        "message_id": "<sample-dec-001@mae.evisa.ro>",
        "sender": "MAE@evisa.ro",
        "subject": "Your E24099301631352 file was decided upon",
        "body": (
            "You can consult the coordinates of your visa application file at any time, by "
            "accessing the following link E24099301631352\n"
            "You can now present yourself at the Colombo, in order to pick up your passport "
            "and the affixed visa sticker, if the decision on your application is positive.\n"
            "Your personal data is processed in accordance with the provisions of Regulation "
            "(EU) 2016/679 (GDPR).\n"
            "This is an informative eMail automatically sent via the eViza portal, please do "
            "not answer."
        ),
        "received_at": "2026-09-28T11:31:00",
    },
    # ------------------------------------------------- known applicants ----
    {
        "uid": "appt-002",
        "message_id": "<sample-appt-002@mae.evisa.ro>",
        "sender": "MAE@evisa.ro",
        "subject": "Appointment confirmation for application file E24712502281412.",
        "body": ("Your appointment is confirmed for visa application file identified by code "
                 "E24712502281412 at Colombo, for 14.10.2026,10:25"),
        "received_at": "2026-09-28T09:12:00",
    },
    {
        "uid": "appt-003",
        "message_id": "<sample-appt-003@mae.evisa.ro>",
        "sender": "MAE@evisa.ro",
        "subject": "Appointment confirmation for application file E24605764875104.",
        "body": ("Your appointment is confirmed for visa application file identified by code "
                 "E24605764875104 at Colombo, for 14.10.2026,10:30"),
        "received_at": "2026-09-28T09:14:00",
    },
    {
        "uid": "appt-004",
        "message_id": "<sample-appt-004@mae.evisa.ro>",
        "sender": "MAE@evisa.ro",
        "subject": "Appointment confirmation for application file E24739315562840.",
        "body": ("Your appointment is confirmed for visa application file identified by code "
                 "E24739315562840 at Colombo, for 14.10.2026,11:00"),
        "received_at": "2026-09-28T09:15:00",
    },
    {
        "uid": "appt-005",
        "message_id": "<sample-appt-005@mae.evisa.ro>",
        "sender": "MAE@evisa.ro",
        "subject": "Appointment confirmation for application file E24604944240255.",
        "body": ("Your appointment is confirmed for visa application file identified by code "
                 "E24604944240255 at Colombo, for 15.10.2026,09:30"),
        "received_at": "2026-09-28T09:21:00",
    },
    {
        "uid": "dec-002",
        "message_id": "<sample-dec-002@mae.evisa.ro>",
        "sender": "MAE@evisa.ro",
        "subject": "Your E24777109988545 file was decided upon",
        "body": ("You can now present yourself at the Colombo, in order to pick up your "
                 "passport and the affixed visa sticker, if the decision on your application "
                 "is positive. File E24777109988545"),
        "received_at": "2026-09-28T11:33:00",
    },
    {
        "uid": "dec-003",
        "message_id": "<sample-dec-003@mae.evisa.ro>",
        "sender": "MAE@evisa.ro",
        "subject": "Your E24605292236483 file was decided upon",
        "body": ("You can now present yourself at the Colombo, in order to pick up your "
                 "passport and the affixed visa sticker. File E24605292236483"),
        "received_at": "2026-09-28T11:35:00",
    },
    {
        "uid": "dec-004",
        "message_id": "<sample-dec-004@mae.evisa.ro>",
        "sender": "MAE@evisa.ro",
        "subject": "Your E24968094763486 file was decided upon",
        "body": ("You can now present yourself at the Colombo, in order to pick up your "
                 "passport and the affixed visa sticker. File E24968094763486"),
        "received_at": "2026-09-28T11:36:00",
    },
]


def as_records():
    out = []
    for s in SAMPLES:
        r = dict(s)
        r["received_at"] = datetime.fromisoformat(r["received_at"])
        out.append(r)
    return out


def write_eml_files(folder: str = None):
    """Dump the samples as .eml files so email_monitor can rehearse IMAP parsing."""
    folder = folder or os.path.join(os.path.dirname(__file__), "sample_emails")
    os.makedirs(folder, exist_ok=True)
    for s in SAMPLES:
        dt = datetime.fromisoformat(s["received_at"])
        path = os.path.join(folder, f"{s['uid']}.eml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(
                f"From: {s['sender']}\r\n"
                f"To: transarabianofficial@gmail.com\r\n"
                f"Subject: {s['subject']}\r\n"
                f"Date: {dt.strftime('%a, %d %b %Y %H:%M:%S +0530')}\r\n"
                f"Message-ID: {s['message_id']}\r\n"
                f"Content-Type: text/plain; charset=utf-8\r\n\r\n"
                f"{s['body']}\r\n")
    return folder


if __name__ == "__main__":
    print("written to", write_eml_files())
