#!/usr/bin/env python3
"""
Sinhala voice agent - runs completely offline (no models, no keys, no network).

Run:  python tests/test_voice_sinhala.py
"""
import os
import sys
import wave
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ["DB_PATH"] = os.path.join(ROOT, "tests", "test_voice.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.chdir(ROOT)

import config                       # noqa: E402
import database as DB               # noqa: E402
import reputation as REP            # noqa: E402

ok = fail = 0


def check(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {label} {extra}")
    else:
        fail += 1
        print(f"  FAIL  {label} {extra}")


def wav(path, seconds=0.5):
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"".join(struct.pack("<h", 0) for _ in range(int(16000 * seconds))))
    return path


DB.init_db()
REP.init_reputation()

import voice_stt as STT             # noqa: E402
import voice_tts as TTS             # noqa: E402
import voice_emotion as EMO         # noqa: E402
import ml_intent as MLI             # noqa: E402
import dl_semantic as DLS           # noqa: E402
import synthesis as SYN             # noqa: E402
import response_harness as RH       # noqa: E402
import synth_data as SD             # noqa: E402
import voice_engine as VE           # noqa: E402
import whatsapp_voice as WV         # noqa: E402

print("\n=== 1. nothing here breaks when no engine is installed ===")
check("STT falls back to stub", STT.pick() in STT.PROVIDERS, STT.pick())
check("TTS falls back to stub", TTS.pick() in TTS.PROVIDERS, TTS.pick())
tmp = os.path.join(ROOT, "tests", "_t.wav")
wav(tmp)
tr = STT.transcribe(tmp, provider="stub")
check("transcribe never raises", isinstance(tr, dict) and tr["ok"] is False, str(tr)[:80])
check("the reason is reported", tr.get("error") == "empty transcript", tr.get("error"))

print("\n=== 2. voice cloning is refused without consent ===")
c0 = TTS.consent_status()
check("cloning is off by default", c0["cloning_allowed"] is False, c0["reason"][:60])
r = TTS.synthesize("ආයුබෝවන්", clone=True)
check("a clone request is refused, not silently done", "consent" in (r.get("error") or "").lower(),
      str(r.get("error"))[:90])
check("...but it still produced safe fallback audio", r.get("ok") is True)
check("faking consent without a recording fails",
      TTS.register_consent("Test Owner", reference_wav="does_not_exist.wav")["ok"] is False)
wav(os.path.join(TTS.voices_dir(), "default.wav"), 1.0)
check("consent WITH a recording is accepted",
      TTS.register_consent("Test Owner", "default.wav", "written consent")["ok"] is True)
config.VOICE["clone_enabled"] = True
check("cloning now allowed (consent + enabled)", TTS.consent_status()["cloning_allowed"] is True)
config.VOICE["clone_enabled"] = False
check("switching it back off disables cloning again",
      TTS.consent_status()["cloning_allowed"] is False)
TTS.revoke_consent()

print("\n=== 3. emotion -> prosody (the 'emotional voice' layer) ===")
check("anger detected", EMO.detect("mekata godak kenthi!")["tone"] == "angry")
check("worry detected", EMO.detect("mage visa eka parakku ai??")["tone"] == "worried")
check("thanks detected", EMO.detect("godak sthuuthi")["tone"] == "happy")
check("urgency detected", EMO.detect("mata adema ona")["tone"] == "urgent")
check("neutral otherwise", EMO.detect("office eka koheda")["tone"] == "neutral")
check("anger is answered calmly, never matched",
      EMO.style_for("angry") == "calm", EMO.style_for("angry"))
check("worry is answered reassuringly", EMO.style_for("worried") == "reassuring")
p = EMO.prosody_for("excited", "x" * 300, intensity=1.0)
check("prosody stays inside human limits", 0.85 <= p["rate"] <= 1.25 and 0.90 <= p["pitch"] <= 1.15,
      f"rate={p['rate']} pitch={p['pitch']}")
short = EMO.prosody_for("excited", "x" * 40, intensity=1.0)
check("long answers are slowed down a little", p["rate"] < short["rate"],
      f"long={p['rate']} short={short['rate']}")
check("every style is documented", set(EMO.PRESETS) >= {"friendly", "professional", "happy",
                                                        "apologetic", "calm", "urgent"})

print("\n=== 4. machine learning: Sinhala + Singlish intent ===")
t = MLI.train()
check("the classifier trains", t.get("ok") is True, str(t)[:90])
for text, want in [("visa fee eka kiyada", "fee_price"),
                   ("වීසා එකට කීයක් යනවද", "fee_price"),
                   ("mage interview eka kavadada", "appointment_date"),
                   ("passport eka ganna dinaya kauda", "collection_date"),
                   ("STOP", "opt_out"),
                   ("ස්තූතියි", "thanks")]:
    got, conf, how = MLI.predict(text)
    check(f"understands {text[:26]!r}", got == want, f"-> {got} ({conf:.2f}, {how})")

print("\n=== 5. deep learning is optional and off by default ===")
check("deep learning disabled by default", DLS.enabled() is False)
check("matching returns nothing when disabled", DLS.match("test")[0] is None)

print("\n=== 6. synthesis + harness (facts stay locked) ===")
facts = {"intent": "appointment_date", "appointment_date": "14.10.2026",
         "appointment_time": "10:25"}
_orig_llm = SYN.llm_reply
SYN.llm_reply = lambda *a, **k: (None, "no_llm")     # stay offline
s = SYN.synthesize_reply("interview eka kavadada", "appointment_date", facts)
SYN.llm_reply = _orig_llm
check("template reply carries the real date", "14.10.2026" in s["grounded"], s["grounded"][:70])
check("no LLM key -> template is used", s["method"] == "no_llm", s["method"])
good = RH.validate(s["synthesized"], facts)
check("a grounded answer passes the harness", good["ok"] is True, str(good["failed"]))
bad_text = "ඔබගේ ගාස්තුව රුපියල් 999999 කි."
bad = RH.validate(bad_text, facts)
check("an INVENTED number is caught", "facts_locked" in bad["failed"], str(bad["detail"]["facts_locked"]))
check("...and a safe grounded reply is offered instead",
      "999999" not in bad["safe_reply"], bad["safe_reply"][:70])
check("bot-speak is caught", RH.validate("As an AI I can help", {})["failed"] and
      "no_bot_leak" in RH.validate("As an AI I can help", {})["failed"])
check("shouting is caught",
      "politeness_ok" in RH.validate("මේක හරි නෑ " + "A" * 40, {"intent": "other"})["failed"])
check("a huge answer is caught", "length_ok" in RH.validate("x" * 900, {})["failed"])

print("\n=== 7. synthetic engineering ===")
rows = SD.paraphrase("visa fee eka kiyada", "fee_price", n=5)
check("paraphrases are generated", len(rows) == 5, str(len(rows)))
check("they keep the intent label", all(r["intent"] == "fee_price" for r in rows))
sd = SD.generate_and_store([{"text": "interview eka kavadada", "intent": "appointment_date"}])
check("stored for training", sd.get("ok") is True, str(sd))

print("\n=== 8. full voice pipeline (dry run, nothing is sent) ===")
VE.init_voice_schema()
orig = STT.transcribe
STT.transcribe = lambda path, language=None, provider=None: {
    "ok": True, "text": "mage visa fee eka kiyada", "language": "si",
    "provider": "test", "error": None, "seconds": 0.2}
try:
    rep = VE.handle_voice("94771234567", tmp, dry_run=True)
finally:
    STT.transcribe = orig
check("transcript captured", rep["transcript"] == "mage visa fee eka kiyada")
check("intent understood", rep["intent"] == "fee_price", str(rep.get("intent")))
check("a Sinhala reply was produced", any("\u0d80" <= ch <= "\u0dff" for ch in rep["reply_text"]),
      rep["reply_text"][:60])
check("harness cleared it", rep.get("harness", {}).get("ok") is True, str(rep.get("harness")))
check("emotion chosen", rep["emotion"]["style"] in EMO.PRESETS, str(rep["emotion"]))
check("audio was produced (placeholder offline)", bool(rep.get("audio_path")))
check("nothing was sent in dry run", rep["sent"] is False)
check("it was remembered for learning",
      DB.one("SELECT COUNT(*) n FROM voice_interactions")["n"] == 1)

print("\n=== 9. loop engineering: a human correction retrains the model ===")
row = DB.one("SELECT id FROM voice_interactions ORDER BY id DESC LIMIT 1")
before = MLI.info()["examples"]
out = VE.learn_from_correction(row["id"], "fee_price", by="tester")
check("correction accepted", out["ok"] is True, str(out)[:90])
check("synthetic examples were generated", out.get("synthetic", 0) > 0, str(out.get("synthetic")))
check("the model was retrained", out.get("retrained", {}).get("ok") is True)
check("training data grew", MLI.info()["examples"] > before)

print("\n=== 10. the unofficial route is flagged, the official one is default ===")
info = WV.route_info()
check("default route is the official Cloud API", info["official"] is True, info["route"])
config.VOICE["whatsapp_route"] = "whatsmeow"
warn = WV.route_info()
check("whatsmeow carries a ban warning", "UNOFFICIAL" in warn["warning"], warn["warning"][:50])
config.VOICE["whatsapp_route"] = "cloud"

print("\n=== 11. no audio -> the customer still gets the answer as text ===")
sent = {}
import whatsapp_client as WC                       # noqa: E402
orig_send = WC.send_human
WC.send_human = lambda *a, **k: (sent.update(k), {"status": "sent"})[1]
try:
    out = WV.send_voice_message("94771234567", "හරි, මම බලන්නම්", None)
finally:
    WC.send_human = orig_send
check("it falls back to text", out.get("fell_back_to_text") is True, str(out)[:90])
check("and says so", out.get("reason") == "no audio produced")

print("\n=== 12. the 2026 stack: knows what to install and why ===")
import voice_stack as VS
rep = VS.stack_report()
check("stack report covers both directions", set(rep) >= {"stt", "tts", "catalog", "avoid"})
check("every recommended STT model states its license",
      all("license" in m for m in rep["catalog"]["stt"]))
check("every recommended TTS model states its license",
      all("license" in m for m in rep["catalog"]["tts"]))
check("non-commercial models are flagged, not recommended",
      any("NC" in a["why"] or "non-commercial" in a["why"].lower() for a in rep["avoid"]),
      rep["avoid"][0]["name"][:40])
check("recommendation always ends at the stub (never crashes)",
      rep["stt"]["fallback_order"][-1] == "stub" and rep["tts"]["fallback_order"][-1] == "stub")
check("install plan prints real commands",
      len(VS.install_plan("stt")["steps"]) > 3 and len(VS.install_plan("tts")["steps"]) > 3)
check("new engines are selectable",
      "onnx_sinhala" in STT.PROVIDERS and "whisper_ct2" in STT.PROVIDERS
      and "piper" in TTS.PROVIDERS and "coqui_vits" in TTS.PROVIDERS)
check("the recommended chain is what the routers use",
      STT.pick() in STT.PROVIDERS and TTS.pick() in TTS.PROVIDERS,
      f"stt={STT.pick()} tts={TTS.pick()}")

print("\n=== 13. dual-pass transcription (fast engine, then a second opinion) ===")
check("an empty transcript looks weak", STT.looks_weak("", 5.0) is True)
check("a 2-character transcript for 5s of audio looks weak", STT.looks_weak("ඔව්", 5.0) is True)
check("a real transcript does not", STT.looks_weak("මට වීසා ගාස්තුව දැනගන්න ඕන", 5.0) is False)
tb = STT.transcribe_best(tmp)
check("dual pass never raises and reports its attempts",
      isinstance(tb.get("attempts"), list), str(tb.get("attempts"))[:60])
check("it says whether a second engine was needed", "second_pass_used" in tb)

print("\n=== 14. benchmarking measures instead of guessing ===")
b = VS.bench("tts")
check("bench never crashes", isinstance(b, dict) and "rtf" in b, str(b)[:70])
if VS.what_could_run()["piper"]:
    check("piper really produced audio here", b["ok"] is True and b["rtf"] > 1,
          f"{b['provider']} RTF={b['rtf']}")
    r = TTS.synthesize("ආයුබෝවන්, මම සිංහලෙන් කතා කරමි.", engine="piper",
                       out_path="tests/_piper.wav")
    check("an explicit engine can be requested", r["provider"] == "piper" and r["ok"])
    check("emotion changes the timing (not just a label)",
          TTS.synthesize("ඔබගේ ගමන් බලපත්‍රය ලැබී ඇත.", emotion="urgent",
                         out_path="tests/_fast.wav")["seconds"]
          != TTS.synthesize("ඔබගේ ගමන් බලපත්‍රය ලැබී ඇත.", emotion="calm",
                            out_path="tests/_slow.wav")["seconds"])
    for f in ("tests/_piper.wav", "tests/_fast.wav", "tests/_slow.wav"):
        if os.path.exists(f):
            os.remove(f)
else:
    print("  SKIP  piper not installed here (install_plan('tts') prints how)")

os.remove(tmp)
print(f"\n{'=' * 62}\n  {ok} passed, {fail} failed\n{'=' * 62}\n")
sys.exit(1 if fail else 0)
