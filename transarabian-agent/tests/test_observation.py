#!/usr/bin/env python3
"""
observation.py - the SAME tracking engine for appointment mails and for
"file was decided upon" mails.

Run:  python tests/test_observation.py
"""
import os
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ["DB_PATH"] = os.path.join(ROOT, "tests", "test_observation.db")
os.environ["RISK_MODEL_PATH"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "risk_test_observation.db.npz")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.chdir(ROOT)

import database as DB                      # noqa: E402
import email_parsers as P                  # noqa: E402
import observation as OBS                  # noqa: E402
import loop_engine as L                    # noqa: E402

ok = fail = 0


def check(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {label} {extra}")
    else:
        fail += 1
        print(f"  FAIL  {label} {extra}")


DB.init_db()
OBS.init_observation()

E = "E24275493641672"

print("\n=== 1. every file is watched from the start ===")
check("a new file starts as 'watching'", OBS.watch(E, "DILUSHIMA SHESHANI") == "watching")
check("watching twice does not duplicate",
      len(DB.query("SELECT * FROM file_watch WHERE e_number=?", (E,))) == 1)
check("counts report it", OBS.counts()["watching"] == 1, str(OBS.counts()))

print("\n=== 2. APPOINTMENT confirmation goes through the observer ===")
appt_subj = "Appointment confirmation for application file E24275493641672."
appt_body = ("Your appointment is confirmed for visa application file identified by "
             "code E24275493641672 at Colombo, for 15.10.2026,10:00")
parsed = P.parse_email(appt_subj, appt_body)
check("mail is classified as an appointment", parsed["kind"] == "appointment", parsed["kind"])
check("date and time are captured",
      parsed["appointment_date"] == "15.10.2026" and parsed["appointment_time"] == "10:00",
      f"{parsed['appointment_date']} {parsed['appointment_time']}")

r1 = L.process_email({"uid": "u1", "subject": appt_subj, "body": appt_body,
                      "sender": "MAE@evisa.ro", "received_at": datetime.now()})
check("the observation is recorded", (r1.get("observation") or {}).get("changed") is True,
      str(r1.get("observation"))[:120])
check("the file moved to 'appointment_seen'", OBS.stage_after(E) == "appointment_seen",
      OBS.stage_after(E))
check("the appointment date is stored on the file",
      OBS.get(E)["appointment_date"] == "15.10.2026")
check("it filed into a batch", (r1.get("status") == "batched"), str(r1.get("status")))

print("\n=== 3. the same mail arriving again is a duplicate, not a second job ===")
r2 = OBS.observe("appointment", parsed, 1, datetime.now())
check("duplicate is detected", r2["duplicate"] is True, str(r2))
check("stage did not change", OBS.stage_after(E) == "appointment_seen")
check("both observations are kept in the history", len(OBS.timeline(E)) == 2,
      str([o["kind"] for o in OBS.timeline(E)]))

print("\n=== 4. after WhatsApp delivery the file moves on ===")
OBS.mark_notified(E, "appointment")
check("stage is now 'appointment_sent'", OBS.stage_after(E) == "appointment_sent")

print("\n=== 5. DECISION mail goes through the SAME observer ===")
dec_subj = "Your E24275493641672 file was decided upon"
dec_body = ("You can now present yourself at the Colombo, in order to pick up your "
            "passport and the affixed visa sticker, if the decision on your "
            "application is positive.")
dparsed = P.parse_email(dec_subj, dec_body)
check("mail is classified as a decision", dparsed["kind"] == "decision")
r3 = L.process_email({"uid": "u2", "subject": dec_subj, "body": dec_body,
                      "sender": "MAE@evisa.ro", "received_at": datetime.now()})
check("the decision is observed", (r3.get("observation") or {}).get("to_stage") == "decided_seen",
      str(r3.get("observation"))[:140])
check("collection date derived (a Sunday)",
      datetime.strptime(OBS.get(E)["collection_date"], "%d/%m/%Y").strftime("%A") == "Sunday",
      OBS.get(E)["collection_date"])
OBS.mark_notified(E, "collection")
check("stage is now 'collection_sent'", OBS.stage_after(E) == "collection_sent")
OBS.close(E)
check("the file closes", OBS.stage_after(E) == "closed")
check("closing removes it from the attention list",
      all(a["e_number"] != E for a in OBS.attention()))

print("\n=== 6. chasing: a decision that never arrives is raised, not forgotten ===")
E2 = "E24099301631352"
OBS.watch(E2, "KAVINDI MADUSHANI")
OBS.observe("appointment", {"e_number": E2, "appointment_date": "01.01.2026",
                            "appointment_time": "09:30"}, 9, datetime.now())
OBS.mark_notified(E2, "appointment")
DB.execute("UPDATE file_watch SET appointment_sent_at=? WHERE e_number=?",
           ((datetime.now() - timedelta(days=60)).isoformat(), E2))
issues = OBS.scan_expectations(create_tasks=True)
hit = [i for i in issues if i["e_number"] == E2 and i["alert"] == "decision_overdue"]
check("an overdue decision is raised for a human", bool(hit), str([i["alert"] for i in issues]))
check("a task is created for it",
      bool(DB.query("SELECT * FROM tasks WHERE type='watch_decision_overdue'")))
check("the alert is not repeated while it is fresh",
      OBS._alert(E2, "decision_overdue", "again") is False)

print("\n=== 7. silent files are surfaced too ===")
E3 = "E24000000000001"
OBS.watch(E3, "SILENT FILE")
DB.execute("UPDATE file_watch SET watched_since=? WHERE e_number=?",
           ((datetime.now() - timedelta(days=90)).isoformat(), E3))
issues = OBS.scan_expectations(create_tasks=False)
check("a file with no mail for months is raised",
      any(i["e_number"] == E3 and i["alert"] == "silent_file" for i in issues),
      str([i["alert"] for i in issues]))

print("\n=== 8. the console board ===")
board = OBS.board()
check("board returns counts, attention and recent files",
      {"counts", "attention", "alerts", "recent"} <= set(board))
check("every stage has a plain-English label",
      all(s in OBS.STAGE_LABELS for s in OBS.STAGES))

print(f"\n{'=' * 60}\n  {ok} passed, {fail} failed\n{'=' * 60}\n")
sys.exit(1 if fail else 0)
