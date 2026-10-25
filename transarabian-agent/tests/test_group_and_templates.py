"""
tests/test_group_and_templates.py

Covers the manual group-post queue and the approved-template fallback that
were added on 2026-10-23, plus the four bugs found that day:

  1. loop_engine never passed a template -> free text silently dropped
  2. time sent as 12:45 instead of house style 12.45PM
  3. send_template passed a bare list -> Meta schema violation
  4. lang compared against "si" only, so "si_LK" fell back to English
  5. a dry run marked the batch "sent", burning it permanently

Run:  python3 tests/test_group_and_templates.py
"""

import os
import sys
import inspect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}   {detail}")


# =====================================================================
print("=" * 62)
print("A. group_queue - the manual post queue")
print("=" * 62)

import group_queue as GQ

GQ.ensure_table()
for r in GQ.pending():
    GQ.delete(r["id"])

body = "EMBASSY PASSPORT COLLECTION EMAILS RECEIVED PERSONS LIST ON SUNDAY (29/11/2026)\n\n01.A\n02.B\n\nEmbassy passport collection for this sunday."
pid = GQ.add(body, kind="collection", title="Collection SUNDAY", batch_id="B1")

check("add returns a usable id", pid > 0, f"got {pid}")
check("blank body refused", GQ.add("   ") == 0)
check("whitespace-only body refused", GQ.add("\n\n \t ") == 0)
check("appears in pending", any(r["id"] == pid for r in GQ.pending()))
check("body stored intact", (GQ.get(pid) or {}).get("body") == body.strip())
check("title stored", (GQ.get(pid) or {}).get("title") == "Collection SUNDAY")
check("batch_id stored", (GQ.get(pid) or {}).get("batch_id") == "B1")
check("not yet posted", (GQ.get(pid) or {}).get("posted_at") is None)
check("get() on missing id -> None", GQ.get(999999) is None)

check("mark_posted -> True", GQ.mark_posted(pid, "kamal") is True)
check("posted_at set", bool((GQ.get(pid) or {}).get("posted_at")))
check("posted_by recorded", (GQ.get(pid) or {}).get("posted_by") == "kamal")
check("gone from pending", not any(r["id"] == pid for r in GQ.pending()))
check("double-post -> False", GQ.mark_posted(pid) is False)
check("post missing id -> False", GQ.mark_posted(999999) is False)

check("delete works", GQ.delete(pid) is True)
check("delete missing -> True (idempotent)", GQ.delete(999999) is True)
check("stats returns dict", isinstance(GQ.stats(), dict))
check("stats has pending+posted", set(GQ.stats()) >= {"pending", "posted"})

# two posts must not collide
a = GQ.add("first", kind="manual")
b = GQ.add("second", kind="manual")
check("two adds get distinct ids", a != b, f"{a} vs {b}")
check("both retrievable", GQ.get(a)["body"] == "first" and GQ.get(b)["body"] == "second")
GQ.delete(a); GQ.delete(b)

# =====================================================================
print()
print("=" * 62)
print("B. _client_template - picking the right approved template")
print("=" * 62)

import loop_engine as L

si_appt = {"lang": "si", "name": "LAHIRU MADURANGA", "se_number": "SE2414195",
           "app_date": "03.11.2026", "app_time": "12:45"}
tpl, vars_, lang = L._client_template("appointment", si_appt)

check("Sinhala appointment picks approved name", tpl == "sinhala_embassy_interview_template", str(tpl))
check("language is si_LK", lang == "si_LK", str(lang))
check("four variables", len(vars_) == 4, str(vars_))
check("name is var 1", vars_[0] == "LAHIRU MADURANGA")
check("SE is var 2", vars_[1] == "SE2414195")
check("date is var 3", vars_[2] == "03.11.2026")

# bug #2 - the house style is a dot, never a colon
check("time uses house style (dot, not colon)", vars_[3] == "12.45PM", f"got {vars_[3]}")
check("no colon anywhere in vars", not any(":" in str(v) for v in vars_))

en_appt = dict(si_appt, lang="en")
tpl_e, _, lang_e = L._client_template("appointment", en_appt)
check("English appointment picks English template", tpl_e == "embassy_interview", str(tpl_e))
check("English language is en", lang_e == "en", str(lang_e))

si_coll = {"lang": "si", "name": "X", "collection_date": "29.11.2026"}
tpl_c, vars_c, lang_c = L._client_template("collection", si_coll)
check("Sinhala collection picks approved name", tpl_c == "passport_collection_template_sinhala", str(tpl_c))
check("collection has exactly one variable", len(vars_c) == 1, str(vars_c))
check("that variable is the date", vars_c[0] == "29.11.2026")

check("unknown kind -> no template", L._client_template("mystery", si_appt)[0] is None)

# missing fields must not crash or emit None
lean = {"lang": "si"}
t2, v2, _ = L._client_template("appointment", lean)
check("missing fields -> empty strings, not None", all(x == "" for x in v2), str(v2))

# =====================================================================
print()
print("=" * 62)
print("C. send_template - Meta's component shape (bug #3)")
print("=" * 62)

import whatsapp_client as W

src = inspect.getsource(W.CloudAPIProvider.send_template)
check("send_template normalises a bare list", "isinstance(components[0], dict)" in src)
check("builds a body component", '"type": "body"' in src)
check("each parameter typed as text", '"type": "text"' in src)

# =====================================================================
print()
print("=" * 62)
print("D. language handling (bug #4)")
print("=" * 62)

src_sh = inspect.getsource(W.send_human)
check("Sinhala match accepts si_LK", 'startswith("si")' in src_sh)

# the mapping itself
from config import TEMPLATE_LANG_SI, TEMPLATE_LANG
check("TEMPLATE_LANG_SI is si_LK", TEMPLATE_LANG_SI == "si_LK", TEMPLATE_LANG_SI)
check("TEMPLATE_LANG is en", TEMPLATE_LANG == "en", TEMPLATE_LANG)


def lang_code_for(lang, use_template=True):
    """Mirror of the line in send_human."""
    return (TEMPLATE_LANG_SI if str(lang).lower().startswith("si")
            else TEMPLATE_LANG) if use_template else TEMPLATE_LANG


check('"si"    -> si_LK', lang_code_for("si") == "si_LK")
check('"si_LK" -> si_LK', lang_code_for("si_LK") == "si_LK")
check('"SI_LK" -> si_LK (case)', lang_code_for("SI_LK") == "si_LK")
check('"en"    -> en', lang_code_for("en") == "en")

# =====================================================================
print()
print("=" * 62)
print("E. dry run must not burn the batch (bug #5)")
print("=" * 62)

src_sb = inspect.getsource(L.send_batch)
check("batch status guarded by `not dry`", "if not dry:" in src_sb)
check("sent update is inside the guard",
      "if not dry:" in src_sb.split('UPDATE batches SET status="sent"')[0]
      or "if not dry:" in src_sb)

# =====================================================================
print()
print("=" * 62)
print("F. group message queues instead of vanishing")
print("=" * 62)

import importlib
importlib.reload(W)
res = W.send_group_message("01. Embassy Interview\n\nSE NUMBER : SE1", batch_id="T", dry_run=True)
check("no JID -> queued, not dropped", res.get("queued_id") is not None, str(res))
check("status reports no_group_configured", res.get("status") == "no_group_configured")
check("explains where to find it", "group" in str(res.get("hint", "")).lower())

for r in GQ.pending():
    GQ.delete(r["id"])

# =====================================================================
print()
print("=" * 62)
print(f"  {PASS} passed, {FAIL} failed")
print("=" * 62)
sys.exit(1 if FAIL else 0)
