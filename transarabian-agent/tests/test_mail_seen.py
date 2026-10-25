#!/usr/bin/env python3
"""
mail_seen.py - the "a colleague read it first" fix, tested on a throwaway DB.

Run:  python tests/test_mail_seen.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# a throwaway database, so the real record is never touched
os.environ["DB_PATH"] = os.path.join(HERE, "mail_seen_test.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["MAIL_DEDUP"] = "false"          # we call mail_seen directly

import mail_seen as MS                                        # noqa: E402

ok = fail = 0


def check(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {label} {extra}")
    else:
        fail += 1
        print(f"  FAIL  {label} {extra}")


def rec(mid, subject="Appointment confirmation", uid="1", day="2026-10-19"):
    return {"message_id": mid, "subject": subject, "uid": uid,
            "sender": "MAE@evisa.ro", "received_at": day}


print("\n=== 1. the identity of a message is stable ===")
a = rec("<abc@evisa.ro>", uid="7")
b = rec("<abc@evisa.ro>", uid="999")          # same mail, different IMAP uid
check("same Message-ID gives the same fingerprint even if the uid changes",
      MS.fingerprint(a) == MS.fingerprint(b), MS.fingerprint(a))
check("fingerprint is prefixed", MS.fingerprint(a).startswith("mid:"),
      MS.fingerprint(a))

c = rec("<zzz@evisa.ro>", uid="7")
check("different mails get different fingerprints",
      MS.fingerprint(a) != MS.fingerprint(c))

print("\n=== 2. a mail with no Message-ID is still recognised ===")
no_mid = rec("", uid="42")
check("falls back to the uid", MS.fingerprint(no_mid) == "uid:42",
      MS.fingerprint(no_mid))
bare = {"subject": "x", "received_at": "y"}
check("falls back to a hash when there is nothing else",
      MS.fingerprint(bare).startswith("hash:"))
check("the hash is deterministic",
      MS.fingerprint(bare) == MS.fingerprint(dict(bare)))

print("\n=== 3. the bug this fixes: a mail a human already READ ===")
# This is the exact failure. 'read_by_human' is not UNSEEN, so the old
# UNSEEN-only search never returned it and the appointment was missed.
read_by_human = rec("<read-first@evisa.ro>", "Appointment confirmation for "
                    "application file E24712502281412.")
batch = [read_by_human]
fresh, already = MS.filter_new(batch)
check("a mail that is NOT unread is still offered to the agent",
      len(fresh) == 1, f"{len(fresh)} new / {already} already handled")
check("nothing is wrongly treated as already handled", already == 0)

print("\n=== 4. it is not offered a second time ===")
for r in fresh:
    MS.mark_processed(r)
again, already2 = MS.filter_new(batch)
check("the same mail is skipped on the next pass", len(again) == 0)
check("and is counted as already handled", already2 == 1, str(already2))
check("it really is in the record", MS.is_processed(MS.fingerprint(read_by_human)))

print("\n=== 5. a genuinely new mail still gets through ===")
brand_new = rec("<brand-new@evisa.ro>", "Your E24712502281412 file was decided upon")
fresh3, already3 = MS.filter_new([read_by_human, brand_new])
check("only the new one is returned", len(fresh3) == 1)
check("and it is the new one", fresh3[0]["message_id"] == "<brand-new@evisa.ro>")

print("\n=== 6. an operator can undo a mistake ===")
MS.mark_processed(brand_new)
check("marked", MS.is_processed(MS.fingerprint(brand_new)))
conn = MS._conn()
conn.execute("DELETE FROM processed_mail WHERE fp=?",
             (MS.fingerprint(brand_new),))
conn.commit(); conn.close()
check("forgetting it lets it be read again",
      not MS.is_processed(MS.fingerprint(brand_new)))

print("\n=== 7. the record survives a new connection (it is on disk) ===")
check("earlier entry still present after reconnecting",
      MS.is_processed(MS.fingerprint(read_by_human)))

print("\n=== 8. it never invents work out of nothing ===")
empty, n0 = MS.filter_new([])
check("an empty batch is handled cleanly", empty == [] and n0 == 0)

print(f"\n{'=' * 62}\n  {ok} passed, {fail} failed\n{'=' * 62}\n")
sys.exit(1 if fail else 0)
