#!/usr/bin/env python3
"""
Data-quality checks on the real registry (data/agent.db).

These exist because two things went wrong with imported data:

  1. A stray line in the PDF got glued onto the last person's name, so
     BALASUBRAMANIYAM NAGESWARAN ended up with every phone number in the
     sheet inside his name field (1,736 characters).
  2. The sheet gives E24605764875104 to two different people. It belongs to
     SUMUDITHA SANJEEWA (SE2430501) - confirmed by the user on 10 Oct 2026 -
     so SUMUDU PRIYADARSHANA must never be given it.

Run:  python tests/test_registry_data.py
"""
import os
import re
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "agent.db")

if not os.path.exists(DB):
    print(f"  no registry at {DB} - skipped")
    sys.exit(0)

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
rows = con.execute("SELECT * FROM applicants").fetchall()

ok = fail = 0


def check(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {label} {extra}")
    else:
        fail += 1
        print(f"  FAIL  {label} {extra}")


print(f"\n=== registry: {len(rows)} people ===")

print("\n--- names ---")
bad_name = [r for r in rows
            if re.search(r"[^A-Za-z \-'.]", r["name"] or "")
            or len(r["name"] or "") > 45
            or "WHATS" in (r["name"] or "").upper()]
check("no name contains digits, symbols or stray header words",
      not bad_name, f"{len(bad_name)} bad")
for r in bad_name[:5]:
    print(f"        {r['se_number']}: {str(r['name'])[:70]!r}")

print("\n--- phone numbers ---")
bad_phone = [r for r in rows
             if (r["whatsapp"] or "").strip()
             and not re.fullmatch(r"\d{9,15}", r["whatsapp"].strip())]
check("every stored number is 9-15 digits", not bad_phone, f"{len(bad_phone)} bad")
for r in bad_phone[:5]:
    print(f"        {r['se_number']} {r['name'][:28]}: {r['whatsapp']!r}")

withnum = [r for r in rows if (r["whatsapp"] or "").strip()]
print(f"        {len(withnum)} of {len(rows)} people have a number")

print("\n--- duplicates ---")
for col in ("e_number", "se_number", "whatsapp"):
    dupes = con.execute(
        f"SELECT {col} v, COUNT(*) c FROM applicants "
        f"WHERE {col} IS NOT NULL AND TRIM({col})<>'' GROUP BY {col} HAVING c>1"
    ).fetchall()
    check(f"no two people share a {col}", not dupes,
          "" if not dupes else str([d["v"] for d in dupes[:3]]))

print("\n--- the E-number you told me about ---")
sumudu = con.execute("SELECT * FROM applicants WHERE se_number='SE2447739'").fetchone()
sumuditha = con.execute("SELECT * FROM applicants WHERE se_number='SE2430501'").fetchone()
if sumudu:
    check("SUMUDU PRIYADARSHANA does NOT hold E24605764875104",
          (sumudu["e_number"] or "") != "E24605764875104",
          f"holds {sumudu['e_number']}")
if sumuditha:
    check("SUMUDITHA SANJEEWA DOES hold E24605764875104",
          (sumuditha["e_number"] or "") == "E24605764875104",
          f"holds {sumuditha['e_number']}")

print("\n--- identifying fields ---")
bad_pp = [r for r in rows if r["passport_no"]
          and not re.fullmatch(r"[NP]\d{6,8}", r["passport_no"])]
check("passport numbers look like passports", not bad_pp, f"{len(bad_pp)} bad")
bad_se = [r for r in rows if not re.fullmatch(r"SE\d{4,8}", r["se_number"] or "")]
check("every row has a valid SE number", not bad_se, f"{len(bad_se)} bad")

print(f"\n{'=' * 62}\n  {ok} passed, {fail} failed\n{'=' * 62}\n")
sys.exit(1 if fail else 0)
