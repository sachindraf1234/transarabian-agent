#!/usr/bin/env python3
"""
AUTO MODE: the agent does the whole job by itself and only stops to ask a
person when something is genuinely unclear.

Run:  python tests/test_auto_mode.py
"""
import os
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ["WHATSAPP_TOKEN"] = ""          # force dry-run: nothing leaves the machine
os.environ["DB_PATH"] = os.path.join(ROOT, "tests", "test_auto.db")
os.environ["RISK_MODEL_PATH"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "risk_test_auto.db.npz")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.chdir(ROOT)

import database as DB                       # noqa: E402
import registry as R                        # noqa: E402
import loop_engine as L                     # noqa: E402
import observation as OBS                   # noqa: E402
from config import AUTO_MODE                # noqa: E402

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
import reputation as REP                    # noqa: E402
REP.init_reputation()
OBS.init_observation()
L.APPOINTMENT_DEBOUNCE_SECONDS = 0          # no 3-minute wait inside the test
L.COLLECTION_DEBOUNCE_SECONDS = 0

# two applicants we know everything about, one we only know by E-number
DB.upsert_applicant({"e_number": "E11111111111111", "name": "AA KNOWN PERSON",
          "se_number": "SE1001", "whatsapp": "94771110001"})
DB.upsert_applicant({"e_number": "E22222222222222", "name": "BB KNOWN PERSON",
          "se_number": "SE1002", "whatsapp": "94771110002"})
DB.upsert_applicant({"e_number": "E33333333333333", "name": "CC NO NUMBER",
          "se_number": "SE1003", "whatsapp": ""})
OBS.sync_registry()

APPT = ("Appointment confirmation for application file {e}.",
        "Your appointment is confirmed for visa application file identified by "
        "code {e} at Colombo, for 20.10.2026,{t}")

print("\n=== 1. a clean batch goes out by itself ===")
check("auto mode is on", AUTO_MODE is True)
# Unique E-numbers per run. These used to be fixed, so a second run found the
# uids already in the emails table, ingest_sample returned "duplicate", no
# batch was made, and the lookup below silently grabbed some other batch
# still lying around from manual testing.
_run = str(int(time.time()))
E1 = "E901" + _run[-11:]
E2 = "E902" + _run[-11:]
for e, t in ((E1, "09:00"), (E2, "09:30")):
    DB.upsert_applicant({"e_number": e,
                         "name": f"AUTO {e[-4:]}", "se_number": "SE" + e[-4:],
                         "whatsapp": "9477111" + e[-4:]})

_batch_ids_before = {r["id"] for r in DB.query("SELECT id FROM batches")}
for e, t in ((E1, "09:00"), (E2, "09:30")):
    L.ingest_sample({"uid": f"auto-{e}-{_run}", "subject": APPT[0].format(e=e),
                     "body": APPT[1].format(e=e, t=t), "sender": "MAE@evisa.ro",
                     "received_at": datetime.now()})

b = DB.one("SELECT * FROM batches WHERE kind='appointment' ORDER BY rowid DESC LIMIT 1")
check("the test got its own new batch", b and b["id"] not in _batch_ids_before,
      str(b and b["id"]))
check("the two confirmations became one batch", b and b["item_count"] == 2,
      str(b and b["item_count"]))
res = L.release_batch(b["id"])
# An approved Meta template on an applicant's phone cannot be recalled, so
# the automation stops here and waits. "Sent itself" is now the BUG, not
# the feature it used to be.
check("it did NOT send itself - it stopped for a person",
      res.get("auto_sent") is False and res.get("awaiting_approval") is True,
      str(res)[:160])
check("the group list was parked for the human to paste",
      res.get("group_queued", 0) >= 1, str(res.get("group_queued")))
check("the applicant messages are counted and held",
      res.get("clients_pending", 0) >= 1, str(res.get("clients_pending")))

st = DB.one("SELECT status FROM batches WHERE id=?", (b["id"],))["status"]
check("the batch waits at 'awaiting_approval'", st == "awaiting_approval", st)
check("no applicant was contacted",
      DB.one("SELECT COUNT(*) n FROM outbox WHERE batch_id=?", (b["id"],))["n"] == 0)

# ...and a machine cannot sneak past that gate by calling send directly.
_gate = L.send_batch(b["id"], approver="auto-mode")
check("send_batch refuses a non-human approver", _gate.get("refused") is True,
      str(_gate.get("error"))[:70])
for _who in ("auto", "auto-timeout", "system", ""):
    _g = L.send_batch(b["id"], approver=_who)
    check(f"  refuses approver {_who!r}", _g.get("refused") is True)
check("a named human approver is allowed through",
      L.send_batch(b["id"], approver="Nuwan", dry_run=True).get("refused") is not True)

print("\n=== 2. when something is unclear it STOPS and asks ===")
L.ingest_sample({"uid": "auto-no-phone", "subject": APPT[0].format(e="E33333333333333"),
                 "body": APPT[1].format(e="E33333333333333", t="10:00"),
                 "sender": "MAE@evisa.ro", "received_at": datetime.now()})
b2 = DB.one("SELECT * FROM batches WHERE kind='appointment' ORDER BY rowid DESC LIMIT 1")
res2 = L.release_batch(b2["id"])
check("it did NOT send itself", res2.get("auto_sent") is not True, str(res2)[:120])
check("a task is waiting for a person",
      bool(DB.query("SELECT * FROM tasks WHERE type='approve_batch' AND status='pending'")))
task = DB.one("SELECT * FROM tasks WHERE type='approve_batch' AND status='pending' "
              "ORDER BY id DESC LIMIT 1")
check("the task says which applicant is the problem",
      "CC NO NUMBER" in (task["detail"] or "") or "no WhatsApp" in (task["detail"] or ""),
      (task["detail"] or "")[:120])
check("the file stays at 'appointment_seen' until a person acts",
      OBS.stage_after("E33333333333333") == "appointment_seen",
      OBS.stage_after("E33333333333333"))

print("\n=== 3. the console can see what needs a person ===")
alerts = DB.query("SELECT * FROM tasks WHERE status='pending' ORDER BY priority, id")
check("there is something for the human to look at", len(alerts) >= 1, str(len(alerts)))
board = OBS.board()
# Nothing here was really sent - this test runs in dry-run mode - so nobody
# may sit at "Applicant told". They were being marked as told on a dry run,
# which is how the board ended up claiming 14 people had been notified when
# none of them had received anything.
check("the watch board does NOT claim anyone was told on a dry run",
      board["counts"]["appointment_sent"] == 0, str(board["counts"]))
check("the files wait at 'interview date got'",
      board["counts"]["appointment_seen"] >= 1, str(board["counts"]))

print(f"\n{'=' * 60}\n  {ok} passed, {fail} failed\n{'=' * 60}\n")
sys.exit(1 if fail else 0)
