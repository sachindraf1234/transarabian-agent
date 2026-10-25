"""
tests/test_pipeline.py - end-to-end rehearsal (no live mail, no live WhatsApp).

    python tests/test_pipeline.py

It wipes a scratch database, imports the pending-persons PDF, feeds the nine
sample embassy e-mails through the loop, and prints exactly what would be sent
to the Romania group and to each applicant.
"""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(os.path.dirname(__file__), "test_agent.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])

from database import init_db, one, query                      # noqa: E402
from human_behavior import init_behavior_tables               # noqa: E402
import registry as R                                          # noqa: E402
import loop_engine as L                                       # noqa: E402
import learning_engine as LE0                                  # noqa: E402
import formatter as F                                         # noqa: E402
from tests.sample_data import as_records                      # noqa: E402

LINE = "=" * 78


def main():
    init_db()
    init_behavior_tables()
    import reputation as REP
    REP.init_reputation()

    print(LINE); print("1. IMPORT THE PENDING-PERSONS SHEET"); print(LINE)
    res = R.import_pending("pdf")
    print(f"   imported {res['imported']}, updated {res['updated']}, skipped rows {len(res['skipped'])}")
    print("   registry:", R.stats())

    print(); print(LINE); print("2. INGEST EMBASSY E-MAILS"); print(LINE)
    for rec in as_records():
        out = L.ingest_sample(rec)
        p = out.get("parsed", {})
        who = (out.get("applicant") or {}).get("name") or "-"
        print(f"   [{p.get('kind'):<11}] {p.get('e_number'):<16} "
              f"{p.get('appointment_date') or p.get('collection_date') or '':<12} "
              f"{p.get('appointment_time') or '':<6} -> {who:<26} ({out.get('method')})")

    print(); print(LINE); print("3. DEBOUNCE -> RELEASE BATCHES"); print(LINE)
    for b in query("SELECT id FROM batches WHERE status='open'"):
        r = L.release_batch(b["id"])
        payload = r["payload"]
        print(f"\n--- batch {b['id']} ({payload['kind']}) : {payload['item_count']} item(s) ---")
        for gm in payload["group_messages"]:
            print(F.split_for_whatsapp(gm["text"])[0] if payload["kind"] == "collection" else gm["text"])
        print("\n   personal messages:")
        for c in payload["client_messages"]:
            print(f"   • {c['name'] or '?':<28} {c.get('phone') or 'NO NUMBER':<14} :: {c['text'][:70]}")

    print(); print(LINE); print("4. HUMAN QUEUE"); print(LINE)
    for t in query("SELECT * FROM tasks WHERE status='pending'"):
        print(f"   #{t['id']:<3} {t['type']:<20} {t['title'][:60]}")

    print(); print(LINE); print("5. TEACH THE AGENT THE TWO UNKNOWN FILES"); print(LINE)
    from database import resolve_task
    for t in query("SELECT * FROM tasks WHERE type='unknown_applicant' AND status='pending'"):
        e = json.loads(t["payload_json"])["e_number"]
        if e.endswith("1352"):
            R.apply_human_mapping(e, "DILUSHIMA SHESHANI", "94771234567", se_number="SE2400111")
            print(f"   learned {e} -> DILUSHIMA SHESHANI")
        else:
            R.apply_human_mapping(e, "ASHEN HASANKA", "94777654321", se_number="SE2400222")
            print(f"   learned {e} -> ASHEN HASANKA")
        LE0.learn_from_task(t["id"], {"outcome": "good", "name": "x", "whatsapp": ""}, by="test")
        resolve_task(t["id"], "done", {"outcome": "good"}, "test")

    print(); print(LINE); print("6. DRY-RUN SEND (nothing leaves the machine)"); print(LINE)
    for b in query("SELECT id FROM batches WHERE status='awaiting_approval'"):
        payload = json.loads(one("SELECT payload_json FROM batches WHERE id=?", (b["id"],))["payload_json"])
        # refresh phones now that the humans taught us the mapping
        for c in payload["client_messages"]:
            a = R.get_applicant_by_e(c["e_number"]) or {}
            c["phone"] = a.get("whatsapp") or c["phone"]
        from database import execute
        execute("UPDATE batches SET payload_json=? WHERE id=?", (json.dumps(payload), b["id"]))
        rep = L.send_batch(b["id"], approver="test", dry_run=True)
        print(f"   {rep['kind']}: group bubbles {rep['group_sent']}, "
              f"clients {rep['clients_sent']}, skipped {len(rep['skipped'])}, failed {len(rep['failed'])}")
        for s in rep["skipped"]:
            print("     skipped:", s)

    print(); print(LINE); print("7. LEARNING CYCLE"); print(LINE)
    import learning_engine as LE
    cyc = LE.daily_cycle()
    print("   stats:", json.dumps(cyc["stats"], indent=2)[:600])
    print("   training:", cyc["training"])
    for l in cyc["lessons"]:
        print("   lesson -", l)

    print(); print(LINE); print("8. CUSTOMER CHAT (AI brain, dry-run)"); print(LINE)
    import agent_brain
    for msg in ["hi", "mge interview eka kavadada", "passport eka ganna dinaya kavadada",
                "monawada documents genna one", "you people are useless, I want a refund",
                "who is the president of france"]:
        r = agent_brain.handle_inbound("94771234567", msg, name="Test Applicant", dry_run=True)
        print(f"   you: {msg}\n   bot: {r['reply'][:150]}   [intent={r['intent']} "
              f"p_escalate={r['escalation_probability']} escalated={r['escalated']}]\n")

    print(LINE); print("DONE - database:", os.environ["DB_PATH"]); print(LINE)


if __name__ == "__main__":
    main()
