"""
tests/test_evolution.py - rehearsal of the Evolution + stealth + risk layer.

Nothing is sent: the Evolution server is faked in-process and every send runs
in dry-run mode, but the *order* and *timing shape* of the calls is asserted -
that is what Meta's behavioural models actually see.

  python tests/test_evolution.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(os.path.dirname(__file__), "test_evolution.db")
os.environ["RISK_MODEL_PATH"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "risk_test_evolution.db.npz")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])

from database import init_db, one, query                     # noqa: E402
from human_behavior import init_behavior_tables              # noqa: E402

LINE = "=" * 78


# ----------------------------------------------------------------- fake server
class FakeEvolution:
    """Records the exact call sequence so we can prove the choreography."""

    def __init__(self):
        self.calls = []
        self.enabled = True
        self.base = "http://127.0.0.1:8080"
        self.instance = "transarabian"

    def jid(self, n, group=False):
        return f"{n}@g.us" if group else f"{n}@s.whatsapp.net"

    def mark_read(self, to, message_id, from_me=False):
        self.calls.append(("mark_read", to, message_id))

    def send_presence(self, to, presence="composing", delay_ms=0, group=False):
        self.calls.append(("presence", to, presence))

    def send_text(self, to, text, group=False):
        self.calls.append(("send", to, text[:40]))
        return {"key": {"id": "FAKE-" + str(len(self.calls))}}

    def state(self):
        return {"state": "open"}


def main():
    init_db()
    init_behavior_tables()
    import reputation as REP
    REP.init_reputation()
    import schemas, stealth
    from whatsapp_client import EvolutionAdapter

    print(LINE); print("1. EVOLUTION WEBHOOK -> canonical JSON envelope"); print(LINE)
    payload = {
        "event": "messages.upsert", "instance": "transarabian",
        "data": {"key": {"remoteJid": "94771234567@s.whatsapp.net", "fromMe": False,
                         "id": "ABC123"},
                 "pushName": "Ayani Nirosha",
                 "message": {"conversation": "mge interview eka kavadada"},
                 "messageType": "conversation"}}
    env = schemas.from_evolution(payload)
    print(json.dumps({k: v for k, v in env.items() if k != "raw"}, indent=1))
    assert env["phone"] == "94771234567" and env["text"] == "mge interview eka kavadada"
    group_payload = json.loads(json.dumps(payload).replace(
        "94771234567@s.whatsapp.net", "12036312345@g.us"))
    g = schemas.from_evolution(group_payload)
    print(f"   group detection: is_group={g['is_group']} jid={g['group_jid']}")
    assert g["is_group"]

    print(); print(LINE); print("2. HUMAN CHOREOGRAPHY (fake transport, real timings)"); print(LINE)
    from database import upsert_applicant
    upsert_applicant({"e_number": "E99999999999999", "se_number": "SE9999999",
                      "name": "AYANI NIROSHA", "whatsapp": "94771234567", "source": "test"})
    fake = FakeEvolution()
    ad = EvolutionAdapter(fake)
    bubbles = ["Ayubowan! Your embassy interview is on 14.10.2026 at 10.25AM.",
               "Please bring your printed file and originals."]
    # silence the reputation gate for the timing test (no history yet => ok)
    stealth.STEALTH["think_min"], stealth.STEALTH["think_max"] = 0.2, 0.4
    stealth.STEALTH["typing_sec_per_char"] = 0.01
    stealth.STEALTH["reply_floor"] = 0.5
    t0 = time.time()
    report = stealth.perform(ad, "94771234567", bubbles, message_id="ABC123",
                             consent_phone="94771234567")
    took = time.time() - t0
    for c in fake.calls:
        print("   ", c)
    print(f"   -> {len(bubbles)} bubbles in {took:.2f}s, typing budget {report['typing_seconds']}s")
    order = [c[0] for c in fake.calls]
    assert order[0] == "mark_read", order
    assert order[1] == "presence" and fake.calls[1][2] == "composing", order
    assert "composing" in [c[2] for c in fake.calls if c[0] == "presence"]
    assert "paused" in [c[2] for c in fake.calls if c[0] == "presence"]
    assert order.count("send") == 2

    print(); print(LINE); print("3. TYPING CAP (a long message must not type for a minute)"); print(LINE)
    for n in (50, 400, 2000):
        print(f"   {n:>5} chars -> {stealth.typing_seconds('x'*n):.2f}s of typing")
    assert stealth.typing_seconds("x" * 5000) <= stealth.STEALTH["typing_cap_hard"]
    print(f"   cap respected: {stealth.typing_seconds('x'*5000):.2f}s <= "
          f"{stealth.STEALTH['typing_cap_hard']}s")

    print(); print(LINE); print("4. CONSENT GATE (cold outreach is refused)"); print(LINE)
    ok, why = stealth.consent_ok("94779990001")
    print(f"   stranger 94779990001 -> allowed={ok} ({why})")
    assert not ok
    from database import execute, normalize_phone
    execute("INSERT INTO inbound_messages (phone,body,created_at) VALUES (?,?,?)",
            (normalize_phone("94779990001"), "hi", "2026-10-01T09:00:00"))
    ok, why = stealth.consent_ok("94779990001")
    print(f"   after they wrote to us -> allowed={ok} ({why})")
    assert ok
    upsert_applicant({"e_number": "E88888888888888", "se_number": "SE8888888",
                      "name": "TEST APPLICANT", "whatsapp": "9471234567", "source": "test"})
    ok, why = stealth.consent_ok("9471234567")
    print(f"   applicant in the registry -> allowed={ok} ({why})")
    assert ok

    print(); print(LINE); print("5. RISK MODEL + CIRCUIT BREAKER"); print(LINE)
    print("   healthy:", json.dumps({k: v for k, v in REP.assess().items()
                                     if k in ("risk", "level", "speed", "halted")}))
    # simulate a bad day: delivery failures + opt-outs + blocks
    for _ in range(12):
        REP.record("send_failed", "94770000001", meta={"error": "undeliverable"})
    for p in ("94770000002", "94770000003", "94770000004"):
        REP.record("optout", p)
    for p in ("94770000005", "94770000006", "94770000007"):
        REP.record("block_hint", p)
    REP.record("connection_lost")
    a = REP.assess()
    print("   after a bad day:", json.dumps({k: v for k, v in a.items()
                                            if k in ("risk", "level", "speed", "halted",
                                                     "floors", "halt_reason")}, indent=1))
    assert a["level"] == "halted" and a["halted"]

    # a blocked send must be refused while halted
    fake2 = FakeEvolution()
    rep2 = stealth.perform(EvolutionAdapter(fake2), "94771234567", ["hello"],
                           consent_phone="94771234567")
    print("   send while halted:", rep2["errors"], "| calls made:", len(fake2.calls))
    assert rep2["sent"] == 0 and fake2.calls == []

    # the red signals age out and a human resumes -> sending must come back
    from database import execute as _e
    _e("UPDATE reputation_events SET created_at=datetime('now','-4 days') "
       "WHERE kind IN ('send_failed','optout','block_hint','connection_lost')")
    print("   resume:", REP.resume(by="test")["ok"])
    a3 = REP.assess()
    print("   after human resume:", json.dumps({k: v for k, v in a3.items()
                                               if k in ("risk", "level", "halted", "speed",
                                                        "override")}))
    assert not a3["halted"]
    # new trouble arrives -> the breaker trips again even inside the grace window
    for p_ in ("94771110001", "94771110002", "94771110003"):
        REP.record("block_hint", p_)
    a4 = REP.assess()
    print("   new blocks arrive during grace:", json.dumps({k: v for k, v in a4.items()
                                                           if k in ("level", "halted", "override")}))
    assert a4["halted"]
    REP.resume(by="test")

    print(); print(LINE); print("6. MODEL LEARNS FROM LABELLED DAYS"); print(LINE)
    print("   day 1 (shock):", REP.daily_feedback())
    for _ in range(10):
        for i in range(30):
            REP.record("send_ok", f"9477000{i:04d}")
        for i in range(20):
            REP.record("inbound", f"9477000{i:04d}")
        REP.daily_feedback()
    a2 = REP.assess()
    print("   after 10 healthy days:", json.dumps({k: v for k, v in a2.items()
                                                  if k in ("risk", "level", "speed", "learned",
                                                           "samples")}))
    print("   weights:", {k: round(v, 2) for k, v in
                          zip(REP.FEATURE_ORDER, REP.risk_model.w)})

    print(); print(LINE); print("7. STRUCTURED JSON I/O"); print(LINE)
    good = '```json\n{"intent":"appointment_query","language":"en","reply":"Your interview is on 14.10.2026","escalate":false,"confidence":0.91,"facts_used":["app_date"]}\n```'
    bad = 'Sure! {"intent":"x","reply":"' + "y" * 900 + '","language":"xx","confidence":9}'
    p1 = schemas.parse_decision(good)
    p2 = schemas.parse_decision(bad, fallback_reply="Please hold.")
    print("   good output ->", p1["ok"], p1["decision"]["intent"], p1["decision"]["confidence"])
    print("   broken output -> ok=%s errors=%s" % (p2["ok"], p2["errors"][:3]))
    print("   repaired length:", len(p2["decision"]["reply"]), "| language:", p2["decision"]["language"])
    tc = schemas.parse_tool_call('{"tool":"send_whatsapp","args":{"to":"9477","text":"hi"}}')
    print("   tool call ->", tc["ok"], tc["call"]["tool"])
    env_out = schemas.outbound_envelope(to="94771234567", text="hi", target_type="individual",
                                        transport="evolution", bubbles=1)
    print("   outbound envelope keys:", list(env_out.keys()))

    print(); print(LINE); print("DONE"); print(LINE)


if __name__ == "__main__":
    main()
