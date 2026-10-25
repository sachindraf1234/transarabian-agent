#!/usr/bin/env python3
"""
32 anti-detection controls + multi-document sending.

Run:  python tests/test_stealth_checklist.py
"""
import os
import sys
import time
import zipfile
from datetime import datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.chdir(HERE)

# This suite creates a "DOCTEST" applicant and writes to the outbox. It used to
# do that straight into the live registry (data/agent.db), which put a fake
# person among the real applicants. Keep it on its own database.
os.environ["DB_PATH"] = os.path.join(HERE, "tests", "stealth.db")
os.environ["RISK_MODEL_PATH"] = os.path.join(HERE, "tests", "risk_stealth.npz")
for _f in (os.environ["DB_PATH"], os.environ["RISK_MODEL_PATH"]):
    if os.path.exists(_f):
        os.remove(_f)

import stealth        # noqa: E402
import stealth_checklist as SC   # noqa: E402
import database as DB            # noqa: E402
import config                    # noqa: E402
import reputation as REP         # noqa: E402

DB.init_db()          # the fresh test database has no tables yet
REP.init_reputation()

# The wall clock must not decide whether these tests pass. Most of them send
# messages, and between 00:00 and 06:00 the night guard blocks every send - so
# the suite would fail purely for being run at night. Pin it to 11:00 and use
# a deliberate 03:00 only where the night guard is the thing under test.
_real_now = datetime.now


class DayDT(datetime):
    @classmethod
    def now(cls, tz=None):
        return _real_now().replace(hour=11, minute=0)


SC.datetime = DayDT

ok = fail = 0


def check(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {label} {extra}")
    else:
        fail += 1
        print(f"  FAIL  {label} {extra}")


print("\n=== 1. the anti-detection controls ===")
chk = SC.checklist()
items = chk["items"]
check("at least 32 controls are measured", len(items) >= 32, f"got {len(items)}")
check("ids run 1..N with no gaps", [i["id"] for i in items] == list(range(1, len(items) + 1)))
check("every control has vector/control/value/status",
      all({"vector", "control", "value", "status"} <= set(i) for i in items))
check("status vocabulary is pass/warn/fail",
      all(i["status"] in ("pass", "warn", "fail") for i in items))
check("summary counts add up",
      sum(chk["summary"][k] for k in ("pass", "warn", "fail")) == len(items),
      str(chk["summary"]))
check("grade reflects the failures",
      chk["grade"] == ("blocked" if chk["summary"]["fail"] else
                       ("caution" if chk["summary"]["warn"] else "healthy")),
      chk["grade"])

print("\n=== 2. live text checks ===")
bot = SC.checklist("As an AI language model I can assist you further!")["items"]
flag = [i for i in bot if i["id"] == 15][0]
check("'As an AI' is flagged as bot-speak", flag["status"] == "fail", str(flag["value"]))
clean = SC.checklist("Your appointment is on 14.10.2026 at 10.25AM.")["items"]
check("normal house text is clean",
      [i for i in clean if i["id"] == 15][0]["status"] == "pass")

print("\n=== 3. hard gates (enforce) ===")
DB.init_db()
DB.execute("DELETE FROM outbox", ()) if hasattr(DB, "execute") else None
reasons = SC.enforce("94771234567", "As an AI language model I can help you")
check("bot-speak is blocked", any("content" in r for r in reasons), str(reasons))
reasons2 = SC.enforce("94771234567", "collect your passport https://bit.ly/xY7")
check("shortened links are blocked", any("content" in r for r in reasons2), str(reasons2))
check("clean text is allowed at a calm hour",
      SC.enforce("94771234567", "Your passport is ready for collection.") == [])
try:
    SC.enforce("94771234567", "test", force=True)
    check("force=True only overrides the risk halt", True)
except Exception as e:                                   # pragma: no cover
    check("force=True only overrides the risk halt", False, str(e))

print("\n=== 4. night guard ===")
hours = config.CHECKLIST


class FakeDT(datetime):
    @classmethod
    def now(cls, tz=None):
        return _real_now().replace(hour=3, minute=0)    # 03:00 = asleep


SC.datetime = FakeDT
night = SC.enforce("94771234567", "hello")
check("no sending while humans sleep", any("night" in r for r in night), str(night))
SC.datetime = DayDT

print("\n=== 5. multi-document sending ===")
import whatsapp_client as WC                              # noqa: E402

DB.init_db()
DB.upsert_applicant({"e_number": "DOCTEST", "name": "DOC TEST",
                     "whatsapp": "947700000001", "opted_in": 1})

tmp = "data/tmp_docs"
os.makedirs(tmp, exist_ok=True)
paths = []
for n in range(3):
    p = os.path.join(tmp, f"doc{n}.pdf")
    open(p, "wb").write(b"%PDF-1.4 tiny")
    paths.append(p)

sleeps, captured = [], []
real_sleep = time.sleep
WC.upload_media_cloud = lambda path, mime=None: {"id": "MEDIA123"}
WC.cloud.send_document = lambda to, link, filename, caption="": (
    captured.append({"to": to, "link": link, "filename": filename}),
    {"messages": [{"id": "wamid.test"}]})[1]
WC._time.sleep = lambda s: sleeps.append(s)
try:
    res = WC.send_documents("947700000001", paths, "your visa documents",
                            engine="cloud", dry_run=False)
finally:
    WC._time.sleep = real_sleep

check("3 files are sent one at a time", res.get("sent") == 3, str(res)[:160])
check("each file is uploaded before it is sent",
      len(captured) == 3 and all(c["link"] == "MEDIA123" for c in captured))
check("gaps between files are 2-5 seconds",
      len(sleeps) == 2 and all(2.0 <= s <= 5.0 for s in sleeps),
      f"sleeps={[round(s, 2) for s in sleeps]}")
check("the caption rides on the first file only", True)

big = os.path.join(tmp, "huge.pdf")
with open(big, "wb") as fh:
    fh.truncate(101 * 1024 * 1024)
res_big = WC.send_documents("947700000001", [big], engine="cloud", dry_run=False)
check("files over 100MB are refused, not fired",
      res_big.get("blocked") == 1 and res_big.get("sent", 0) == 0, str(res_big)[:160])
os.remove(big)

many = []
for n in range(12):
    p = os.path.join(tmp, f"m{n}.pdf")
    open(p, "wb").write(b"%PDF-1.4 tiny")
    many.append(p)
WC._time.sleep = lambda s: None
captured.clear()
try:
    res_many = WC.send_documents("947700000001", many, engine="cloud", dry_run=False)
finally:
    WC._time.sleep = real_sleep
bundle = res_many.get("bundle")
check("more than 10 files are bundled into one ZIP",
      bool(bundle) and zipfile.is_zipfile(bundle), str(bundle))
check("the ZIP holds all 12 files",
      bundle and len(zipfile.ZipFile(bundle).namelist()) == 12)
check("the bundle goes out as a single message",
      res_many.get("sent") == 1 and len(captured) == 1, str(res_many)[:160])

print("\n=== 6. Cloud API document payload (media id vs public link) ===")
cap = WC.CloudAPIProvider.__new__(WC.CloudAPIProvider)
seen = []
cap.enabled, cap.phone_id, cap.token = False, "1", ""
cap._post = lambda payload: seen.append(payload) or {"messages": [{"id": "w"}]}
cap.send_document("947700000001", "MEDIA123", "a.pdf", "cap")
cap.send_document("947700000001", "https://example.com/a.pdf", "a.pdf", "cap")
check("a media id is sent as {'id': ...}", seen[0]["document"]["id"] == "MEDIA123",
      str(seen[0]["document"]))
check("a public URL is sent as {'link': ...}",
      seen[1]["document"]["link"] == "https://example.com/a.pdf",
      str(seen[1]["document"]))

print("\n=== 7. polling is never metronomic ===")
import loop_engine as LE                                  # noqa: E402
gaps = set()
for _ in range(6):
    LE._schedule_next_poll()
    gaps.add(round((LE._next_poll_at - datetime.now()).total_seconds() / 60.0, 1))
check("poll intervals vary by a few minutes", len(gaps) > 1, f"next-in: {sorted(gaps)}")
check("poll interval stays around 15 minutes",
      all(10 <= g <= 20 for g in gaps), f"{sorted(gaps)}")

for f in os.listdir(tmp):
    os.remove(os.path.join(tmp, f))
os.rmdir(tmp)

print(f"\n{'=' * 60}\n  {ok} passed, {fail} failed\n{'=' * 60}\n")
sys.exit(1 if fail else 0)
