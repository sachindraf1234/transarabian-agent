#!/usr/bin/env python3
"""
Tests for adding and editing applicant details (people_admin.py).

Every check here is a bug that actually happened:

  * a partial PUT (send only the E-number) wiped the person's name, SE number,
    phone and company, and left their key blank - the record was destroyed;
  * writing through two SQLite connections at once deadlocked the request;
  * an exception mid-edit leaked the connection, which then held the write lock
    so every following request hung until it timed out;
  * data.get("e_number", "") returns None, not "", when the key is present but
    null - that crashed any edit that did not include an E-number.

Plus the standing rules: one E-number per person, one passport per person,
no digits in a name, no undiallable phone numbers.

Run:  python tests/test_people_admin.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

os.environ["DB_PATH"] = os.path.join(HERE, "people_test.db")
os.environ["RISK_MODEL_PATH"] = os.path.join(HERE, "risk_people.npz")
for f in (os.environ["DB_PATH"], os.environ["RISK_MODEL_PATH"]):
    if os.path.exists(f):
        os.remove(f)

import database as DB                                    # noqa: E402
DB.init_db()

from fastapi.testclient import TestClient                # noqa: E402
import people_admin as PA                                # noqa: E402
from fastapi import FastAPI                              # noqa: E402

app = FastAPI()
app.include_router(PA.router)
client = TestClient(app)

ok = fail = 0


def check(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {label} {extra}")
    else:
        fail += 1
        print(f"  FAIL  {label} {extra}")


# two people who exist before any test runs
DB.execute("INSERT INTO applicants (e_number,se_number,name,name_key,passport_no,"
           "company,whatsapp,language,opted_in) VALUES (?,?,?,?,?,?,?,?,1)",
           ("E24605764875104", "SE2430501", "SUMUDITHA SANJEEWA",
            "SUMUDITHA SANJEEWA", "P0703909", "RETEX GREEN", "94761393140", "si"))
DB.execute("INSERT INTO applicants (e_number,se_number,name,name_key,passport_no,"
           "company,whatsapp,language,opted_in) VALUES (?,?,?,?,?,?,?,?,1)",
           ("SE:SE2447739", "SE2447739", "SUMUDU PRIYADARSHANA",
            "SUMUDU PRIYADARSHANA", "P1231469", "RETEX GREEN", "94767715086", "si"))

print("\n=== 1. a partial edit must change ONLY what was sent ===")
r = client.post("/api/people", json={"name": "TEST PERSON", "se_number": "SE9999999",
                                     "whatsapp": "077 123 4567", "company": "CLEVER"})
check("add a person", r.status_code == 200, str(r.status_code))
key = r.json().get("e_number")
check("phone stored in international form",
      r.json()["person"]["whatsapp"] == "94771234567",
      r.json()["person"]["whatsapp"])

r = client.put(f"/api/people/{key}", json={"e_number": "E99999999999999"})
p = r.json().get("person", {})
check("partial PUT succeeds", r.status_code == 200, str(r.status_code))
check("only the E-number changed", r.json().get("changed") == ["e_number"],
      str(r.json().get("changed")))
check("name survived", p.get("name") == "TEST PERSON", str(p.get("name")))
check("SE number survived", p.get("se_number") == "SE9999999", str(p.get("se_number")))
check("phone survived", p.get("whatsapp") == "94771234567", str(p.get("whatsapp")))
check("company survived", p.get("company") == "CLEVER", str(p.get("company")))

print("\n=== 2. a second partial edit, and the key it moved to ===")
r = client.put("/api/people/E99999999999999", json={"whatsapp": "077 987 6543"})
check("edit by the new E-number works", r.status_code == 200, str(r.status_code))
check("phone updated", r.json()["person"]["whatsapp"] == "94779876543",
      r.json()["person"]["whatsapp"])
check("name still there", r.json()["person"]["name"] == "TEST PERSON")

print("\n=== 3. nothing may blank the primary key ===")
r = client.put("/api/people/E99999999999999", json={"e_number": ""})
check("blank E-number does not 500", r.status_code == 200, str(r.status_code))
check("it is reported as a warning", bool(r.json().get("warnings")))
still = DB.one("SELECT e_number FROM applicants WHERE e_number=?",
               ("E99999999999999",))
check("the key is still intact", still is not None)
check("no row anywhere has a blank key",
      not DB.query("SELECT e_number FROM applicants WHERE TRIM(COALESCE(e_number,''))=''"))

print("\n=== 4. the rules that protect real people ===")
r = client.put("/api/people/SE:SE2447739", json={"e_number": "E24605764875104"})
check("SUMUDU cannot be given SUMUDITHA's E-number", r.status_code == 400,
      str(r.status_code))
check("the refusal names the real holder",
      "SUMUDITHA" in str(r.json()), str(r.json())[:90])
sumudu = DB.one("SELECT * FROM applicants WHERE se_number='SE2447739'")
check("SUMUDU unchanged", sumudu["e_number"] == "SE:SE2447739", sumudu["e_number"])

for label, body in [("an undiallable phone", {"whatsapp": "+7 977 810-43-97"}),
                    ("a name containing digits", {"name": "X 12345"}),
                    ("a bad E-number", {"e_number": "12345"}),
                    ("a bad SE number", {"se_number": "XX"}),
                    ("a bad passport", {"passport_no": "123"})]:
    r = client.put("/api/people/E99999999999999", json=body)
    check(f"{label} is refused", r.status_code == 400, str(r.status_code))

print("\n=== 5. warnings do not block a save ===")
r = client.put("/api/people/E99999999999999", json={"passport_no": "P0703909"})
check("shared passport still saves", r.status_code == 200, str(r.status_code))
check("but it warns", bool(r.json().get("warnings")), str(r.json().get("warnings"))[:80])

print("\n=== 6. history is recorded ===")
h = client.get("/api/people/history/E99999999999999").json()
check("changes were logged", len(h) > 0, f"{len(h)} entries")
check("an entry names who made it", any(e.get("by") for e in h))

print("\n=== 7. add needs a name and some way to identify the person ===")
check("no name is refused",
      client.post("/api/people", json={"se_number": "SE1111111"}).status_code == 400)
check("no E and no SE is refused",
      client.post("/api/people", json={"name": "NOBODY"}).status_code == 400)
check("a duplicate E-number is refused",
      client.post("/api/people",
                  json={"name": "IMPOSTOR", "e_number": "E24605764875104"}).status_code == 400)

print("\n=== 8. delete, and the app still answers afterwards ===")
r = client.delete("/api/people/E99999999999999")
check("delete works", r.status_code == 200, str(r.status_code))
check("the person is gone",
      DB.one("SELECT * FROM applicants WHERE e_number='E99999999999999'") is None)
r = client.get("/api/people?missing=anything")
check("the API still answers", r.status_code == 200, str(r.status_code))
check("no test rows left behind",
      not DB.query("SELECT e_number FROM applicants WHERE e_number LIKE '%9999%'"))
check("exactly the two original people remain",
      DB.one("SELECT COUNT(*) n FROM applicants")["n"] == 2,
      str(DB.one("SELECT COUNT(*) n FROM applicants")["n"]))


print("\n=== 9. reading a document and applying it ===")
import ocr_engine                                          # noqa: E402

SHEET = os.path.join(ROOT, "tests", "sample_sheet.txt")
open(SHEET, "w").write(
    "EMBASSY INTERVIEW DATE PENDING PERSONS LIST\n"
    "NO NAME PASSPORT NO SE NUMBER COMPANY NAME E NUMBER WHATS APP\n"
    "1 NEW ONE N1234567 SE7000001 CLEVER 5/6/2026 E70000000000001 +94 77 111 2222\n"
    "2 NO PHONE YET N7654321 SE7000002 RETEX GREEN 6/6/2026\n"
    "3 BAD PHONE N2222222 SE7000003 RETEX GREEN 6/6/2026 E70000000000003 +7 977 810-43-97\n"
    "4 TAKES HIS E N3333333 SE7000004 RETEX GREEN 6/6/2026 E24605764875104 +94 77 333 4444\n")
res = ocr_engine.read_document(SHEET)
check("rows were read", res["row_count"] == 4, str(res["row_count"]))
check("the unreadable phone is flagged",
      any("not a number we can dial" in p["message"] for p in res["problems"]))
check("a row claiming someone else's E-number is flagged",
      any("already belongs to" in p["message"] for p in
          (res["problems"] + [{"level": lv, "where": w, "message": m}
                              for lv, w, m in ocr_engine.cross_check_registry(res["rows"])])))
check("nothing was saved by reading", 
      DB.one("SELECT COUNT(*) n FROM applicants")["n"] == 2)

r = client.post("/api/people/documents/apply", json={"rows": res["rows"]})
out = r.json()
check("apply reports what it did", r.status_code == 200, str(r.status_code))
saved = out.get("filled", 0) + out.get("added", 0)
check("the good rows were saved", saved >= 1, str(saved))
check("the row with the stolen E-number was refused",
      DB.one("SELECT COUNT(*) n FROM applicants WHERE e_number='E24605764875104'")["n"] == 1)
check("SUMUDITHA still holds his own E-number",
      DB.one("SELECT se_number FROM applicants WHERE e_number='E24605764875104'")["se_number"]
      == "SE2430501")
check("no one was given the unreadable phone",
      DB.one("SELECT COUNT(*) n FROM applicants WHERE whatsapp='79778104397'")["n"] == 0)
os.remove(SHEET)


print("\n=== 10. rows go to the right place: fill gaps, or add a new person ===")
# three people, each missing something different
DB.execute("INSERT INTO applicants (e_number,se_number,name,name_key,passport_no,"
           "whatsapp,company,opted_in) VALUES (?,?,?,?,?,?,?,1)",
           ("E11111111111111", "SE1111111", "HAS E ONLY", "HAS E ONLY",
            None, None, None))
DB.execute("INSERT INTO applicants (e_number,se_number,name,name_key,passport_no,"
           "whatsapp,company,opted_in) VALUES (?,?,?,?,?,?,?,1)",
           ("SE:SE2222222", "SE2222222", "NO E YET", "NO E YET",
            "N9000002", "94772222222", "RETEX GREEN"))
DB.execute("INSERT INTO applicants (e_number,se_number,name,name_key,passport_no,"
           "whatsapp,company,opted_in) VALUES (?,?,?,?,?,?,?,1)",
           ("E33333333333333", "SE3333333", "COMPLETE", "COMPLETE",
            "N3333333", "94773333333", "CLEVER"))

r = client.post("/api/people/documents/apply", json={"rows": [
    # belongs to HAS E ONLY -> fill the three gaps, change nothing else
    {"row_no": 1, "name": "HAS E ONLY", "se_number": "SE1111111",
     "passport_no": "N1111111", "company": "CLEVER", "whatsapp": "077 900 1001"},
    # belongs to NO E YET -> gets an E-number, so the key moves
    {"row_no": 2, "name": "NO E YET", "se_number": "SE2222222",
     "e_number": "E22222222222222", "passport_no": "N9000002",
     "embassy_applied_date": "7/7/2026"},
    # belongs to nobody -> a new row
    {"row_no": 3, "name": "BRAND NEW PERSON", "se_number": "SE4444444",
     "passport_no": "N4444444", "company": "CLEVER", "whatsapp": "077 900 2002"},
    # already complete -> must not be touched
    {"row_no": 4, "name": "COMPLETE", "se_number": "SE3333333",
     "e_number": "E33333333333333", "passport_no": "N3333333",
     "company": "CLEVER", "whatsapp": "94773333333"},
]})
d = r.json()
check("two people had gaps filled", d.get("filled") == 2, str(d.get("filled")))
check("one new person was added", d.get("added") == 1, str(d.get("added")))
check("the complete person was left alone", d.get("unchanged") == 1,
      str(d.get("unchanged")))
check("nothing was skipped", not d.get("skipped"), str(d.get("skipped"))[:200])

h = DB.one("SELECT * FROM applicants WHERE se_number='SE1111111'")
check("gaps were filled", h["passport_no"] == "N1111111" and h["whatsapp"]
      == "94779001001" and h["company"] == "CLEVER",
      f"{h['passport_no']} {h['whatsapp']} {h['company']}")
n = DB.one("SELECT * FROM applicants WHERE se_number='SE2222222'")
check("the E-number was attached and the key moved",
      n["e_number"] == "E22222222222222", n["e_number"])
check("their existing phone was not overwritten",
      n["whatsapp"] == "94772222222", n["whatsapp"])
check("their applied date was filled",
      n["embassy_applied_date"] == "7/7/2026", str(n["embassy_applied_date"]))
new = DB.one("SELECT * FROM applicants WHERE se_number='SE4444444'")
check("the new person exists", new is not None)
check("the new person got a phone", new["whatsapp"] == "94779002002",
      str(new["whatsapp"]))
c = DB.one("SELECT * FROM applicants WHERE se_number='SE3333333'")
check("the complete person is untouched",
      c["name"] == "COMPLETE" and c["passport_no"] == "N3333333")

print("\n=== 11. ugly input must not crash the endpoint ===")
for label, body in [("a row with nothing in it", {"rows": [{}]}),
                    ("nulls", {"rows": [{"name": None, "se_number": None}]}),
                    ("rows is not a list of rows", {"rows": ["nonsense"]}),
                    ("an integer row_no", {"rows": [{"row_no": 7, "name": "X",
                                                     "se_number": "SE7777777"}]})]:
    r = client.post("/api/people/documents/apply", json=body)
    check(f"{label} does not 500", r.status_code in (200, 400, 422),
          str(r.status_code))

print(f"\n{'=' * 62}\n  {ok} passed, {fail} failed\n{'=' * 62}\n")
sys.exit(1 if fail else 0)
