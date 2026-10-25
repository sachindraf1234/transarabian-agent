#!/usr/bin/env python3
"""
Edge cases that were real bugs. Every check here failed at some point.

Found 2026-10-12 while hunting bugs (see bug_hunt.py):
  * "2.30PM" was stored as 02:30, so a customer was told to arrive at 02.30AM
  * a mail from anyone, not just the embassy, could create an appointment
  * an unreadable date produced the literal word "None" in the Sinhala notice
  * an empty batch announced itself as successfully sent
  * ISO dates (2026-06-05) were not understood

Run:  python tests/test_edge_cases.py
"""
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ["DB_PATH"] = os.path.join(HERE, "test_edge.db")
os.environ["RISK_MODEL_PATH"] = os.path.join(HERE, "risk_edge.npz")
for f in (os.environ["DB_PATH"], os.environ["RISK_MODEL_PATH"]):
    if os.path.exists(f):
        os.remove(f)
os.chdir(ROOT)

import database as DB                # noqa: E402
import email_parsers as EP           # noqa: E402
import formatter as F                # noqa: E402
import loop_engine as L              # noqa: E402
import reputation as REP             # noqa: E402

DB.init_db()
REP.init_reputation()

ok = fail = 0


def check(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {label} {extra}")
    else:
        fail += 1
        print(f"  FAIL  {label} {extra}")


def appt(time_s="10:25"):
    return "... code E11111111111111 at Colombo, for 14.10.2026," + time_s


def parsed(time_s):
    return EP.parse_email(
        "Appointment confirmation for application file E11111111111111.", appt(time_s))


print("\n=== 1. times: a PM appointment must never become an AM one ===")
check("2.30PM is stored as 14:30", parsed("2.30PM")["appointment_time"] == "14:30",
      parsed("2.30PM")["appointment_time"])
check("...and read back as 02.30PM, not 02.30AM",
      F.to_ampm(parsed("2.30PM")["appointment_time"]) == "02.30PM",
      F.to_ampm(parsed("2.30PM")["appointment_time"]))
check("11.45PM is stored as 23:45", parsed("11.45PM")["appointment_time"] == "23:45")
check("12.00AM (midnight) is stored as 00:00", parsed("12.00AM")["appointment_time"] == "00:00")
check("12.00PM (noon) is stored as 12:00", parsed("12.00PM")["appointment_time"] == "12:00")
check("9.05AM stays 09:05", parsed("9.05AM")["appointment_time"] == "09:05")
check("a plain 24-hour time is untouched", parsed("10:25")["appointment_time"] == "10:25")

print("\n=== 2. dates ===")
check("dot format", EP.parse_dot_date("14.10.2026") is not None)
check("slash format", EP.parse_dot_date("14/10/2026") is not None)
check("iso format", EP.parse_dot_date("2026-06-05") is not None,
      str(EP.parse_dot_date("2026-06-05")))
check("dot and slash mean the same day",
      EP.parse_dot_date("05.06.2026") == EP.parse_dot_date("05/06/2026"))
check("an impossible date is rejected, not guessed",
      EP.parse_dot_date("32.13.2026") is None)

print("\n=== 3. nothing says 'None' to a customer ===")
check("no date -> empty message, not the word None",
      F.collection_client_message_si(None) == "")
check("empty date -> empty message", F.collection_client_message_si("") == "")
check("a real date still works",
      "04/10/2026" in F.collection_client_message_si("2026-10-04"))
check("half an interview message is not sent",
      F.interview_client_message("SE1", "14.10.2026", "") == "")
check("the word None never reaches a customer",
      "None" not in F.collection_client_message_si("2026-10-04"))

print("\n=== 4. only the embassy may move a customer's file ===")
prank = L.ingest_sample({"uid": "spoof", "subject": "Appointment confirmation for "
                         "application file E11111111111111.", "body": appt(),
                         "sender": "prankster@gmail.com", "received_at": datetime.now()})
check("a mail from a stranger is escalated, not filed",
      prank.get("status") == "escalated_untrusted_sender", str(prank.get("status")))
real = L.ingest_sample({"uid": "real", "subject": "Appointment confirmation for "
                        "application file E22222222222222.",
                        "body": "... code E22222222222222 at Colombo, for 20.10.2026,10:25",
                        "sender": "MAE@evisa.ro", "received_at": datetime.now()})
check("a real embassy mail still goes through", real.get("status") == "batched",
      str(real.get("status")))

print("\n=== 5. an appointment it cannot read is handed to a person ===")
bad = L.ingest_sample({"uid": "baddate", "subject": "Appointment confirmation for "
                       "application file E33333333333333.",
                       "body": "... code E33333333333333 at Colombo, for 32.13.2026,10:25",
                       "sender": "MAE@evisa.ro", "received_at": datetime.now()})
check("unreadable date -> escalated", bad.get("status") == "escalated_incomplete",
      str(bad.get("status")))

print("\n=== 6. an empty batch must not announce itself as sent ===")
check("empty payload is not 'clean'",
      L._is_clean({}, []) is False)
check("a batch with nothing in it does not auto-send",
      L._is_clean({"client_messages": [], "group_messages": []}, []) is False)
check("a normal clean batch still auto-sends",
      L._is_clean({"client_messages": [{"phone": "947700000001", "name": "A",
                                        "e_number": "E1", "text": "Dear Applicant..."}],
                   "group_messages": [{"text": "x"}]}, []) is True)
check("a batch with a blank client message does not auto-send",
      L._is_clean({"client_messages": [{"phone": "947700000001", "name": "A",
                                        "e_number": "E1", "text": ""}],
                   "group_messages": [{"text": "x"}]}, []) is False)

print("\n=== 7. the same e-mail twice ===")
rec = {"uid": "twice", "subject": "Appointment confirmation for application file "
       "E44444444444444.", "body": "... code E44444444444444 at Colombo, for 20.10.2026,11:00",
       "sender": "MAE@evisa.ro", "received_at": datetime.now()}
L.ingest_sample(rec)
second = L.ingest_sample(rec)
check("it is not processed twice", second.get("skipped") == "duplicate",
      str(second)[:60])

print("\n=== 8. phone numbers written every way ===")
for raw, want in [("0772798072", "94772798072"), ("+94772798072", "94772798072"),
                  ("94772798072", "94772798072"), ("077 279 8072", "94772798072"),
                  ("94-77-279-8072", "94772798072")]:
    check(f"{raw!r}", DB.normalize_phone(raw) == want, DB.normalize_phone(raw))
check("junk does not crash", DB.normalize_phone("not a number") is not None)

print("\n=== 9. a message that came out blank must never be sent ===")
# A collection e-mail arrives with no readable date. The Sinhala notice therefore
# cannot be written. It used to be sent anyway - as an empty WhatsApp bubble.
DB.execute("INSERT OR REPLACE INTO applicants (e_number,name,whatsapp,language,opted_in) "
           "VALUES (?,?,?,?,?)", ("E55555555555555", "KAMAL PERERA", "94772798072", "si", 1))
DB.execute("INSERT OR REPLACE INTO applicants (e_number,name,whatsapp,language,opted_in) "
           "VALUES (?,?,?,?,?)", ("E66666666666666", "NIMALI SILVA", "94712345678", "si", 1))
DB.execute("INSERT OR REPLACE INTO batches (id,kind,status,created_at) VALUES (?,?,?,?)",
           ("COLL-BLANK", "collection", "pending", datetime.now().isoformat()))
DB.execute("INSERT OR REPLACE INTO collections (e_number,name,collection_date,batch_id,"
           "created_at) VALUES (?,?,?,?,?)",
           ("E55555555555555", "KAMAL PERERA", None, "COLL-BLANK", datetime.now().isoformat()))
DB.execute("INSERT OR REPLACE INTO collections (e_number,name,collection_date,batch_id,"
           "created_at) VALUES (?,?,?,?,?)",
           ("E66666666666666", "NIMALI SILVA", "2026-10-18", "COLL-BLANK",
            datetime.now().isoformat()))

pay = L.build_batch_payload("COLL-BLANK")
check("auto mode refuses to send a batch containing a blank message",
      L._is_clean(pay, []) is False)
rep = L.send_batch("COLL-BLANK", approver="test", dry_run=True)
blank_skipped = [s for s in rep["skipped"] if s.get("reason") == "empty_message"]
check("the blank message is held back, not sent", len(blank_skipped) == 1, str(rep["skipped"]))
check("the applicant who could be messaged still was", rep["clients_sent"] == 1,
      str(rep["clients_sent"]))
check("nothing blank reached the outbox",
      not DB.one("SELECT COUNT(*) n FROM outbox WHERE TRIM(COALESCE(body,''))='' "
                 "AND status IN ('sent','dry_run','sending')")["n"])
check("a person is asked to write it by hand",
      DB.one("SELECT COUNT(*) n FROM tasks WHERE type='missing_message_text' "
             "AND status='pending'")["n"] >= 1)
row = DB.one("SELECT sent_client FROM collections WHERE e_number=? AND batch_id=?",
             ("E55555555555555", "COLL-BLANK"))
check("the applicant is not marked as having been told", row["sent_client"] == 0,
      f"sent_client={row['sent_client']}")
row2 = DB.one("SELECT sent_client FROM collections WHERE e_number=? AND batch_id=?",
              ("E66666666666666", "COLL-BLANK"))
# This was a DRY RUN, so nobody was actually told. Marking them as told here
# is what put 14 files at "Applicant told" on the watch board when every one
# of those messages had failed or was only ever a dry run.
check("a dry run does NOT mark anyone as having been told",
      row2["sent_client"] == 0, f"sent_client={row2['sent_client']}")
check("the dry run says plainly that nobody was messaged",
      "E66666666666666" in (rep.get("dry_run_only") or []),
      str(rep.get("dry_run_only")))
check("the dry run warns that the file stays at 'interview date got'",
      any("NOT actually messaged" in w for w in rep.get("warnings", [])),
      str(rep.get("warnings"))[:90])

print(f"\n{'=' * 62}\n  {ok} passed, {fail} failed\n{'=' * 62}\n")
sys.exit(1 if fail else 0)
