#!/usr/bin/env python3
"""
The ban-risk model must not talk itself into a panic on thin evidence.

Background (a real bug, found 2026-10-09): the Evolution simulation test fed 11
synthetic "blocked" days into the risk model, fit() saved those weights to the
shared ml/risk_model.npz, and from then on a completely quiet, healthy number
scored 0.61 - "throttle" - which silently turned auto-mode off. Nobody could
see why.

Run:  python tests/test_risk_model.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ["DB_PATH"] = os.path.join(HERE, "test_risk.db")
os.environ["RISK_MODEL_PATH"] = os.path.join(HERE, "risk_test.npz")
for f in (os.environ["DB_PATH"], os.environ["RISK_MODEL_PATH"]):
    if os.path.exists(f):
        os.remove(f)
os.chdir(ROOT)

# Snapshot the model the agent actually uses, so we can prove THIS test never
# touched it. It used to assert the file must not exist, which broke as soon as
# the app legitimately trained one - that is not the same thing as being safe.
PROD_MODEL = os.path.join(ROOT, "ml", "risk_model.npz")


def _model_state():
    if not os.path.exists(PROD_MODEL):
        return None
    st = os.stat(PROD_MODEL)
    return (st.st_mtime_ns, st.st_size)


MODEL_BEFORE = _model_state()

import database as DB          # noqa: E402
import reputation as REP       # noqa: E402

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
REP.init_reputation()

print("\n=== 1. a quiet number is healthy ===")
a = REP.assess()
check("no messages at all -> risk is low", a["risk"] < 0.20, f"risk={a['risk']}")
check("and the level is ok, not throttle", a["level"] == "ok", a["level"])
check("no halt", a["halted"] is False)

print("\n=== 2. thin 'evidence' cannot hijack the model ===")
quiet = REP.features()
for flat in (quiet, {**quiet, "block_rate": 1.0}):
    pass
for _ in range(11):                       # exactly what the old bug did
    REP.risk_model.add_sample({**quiet, "block_rate": 1.0}, 1)
fit = REP.risk_model.fit()
check("it still trains without error", fit.get("trained") is True, str(fit)[:90])
check("but 11 samples are not trusted yet", REP.risk_model.learned is False,
      f"samples={REP.risk_model.samples}")
check("...and it says so", "needs" in (fit.get("note") or ""), fit.get("note", "")[:70])
a2 = REP.assess()
check("a quiet number is STILL healthy after 11 bad days", a2["risk"] < 0.25,
      f"risk={a2['risk']} (was {a['risk']})")
check("auto-send would still be allowed", a2["level"] != "throttle", a2["level"])
check("the bias is on a leash",
      abs(REP.risk_model.b - REP.PRIOR_B) <= REP.MAX_BIAS_SHIFT + 1e-9,
      f"b={REP.risk_model.b:.2f} prior={REP.PRIOR_B}")

print("\n=== 3. with real evidence behind it, learning still works ===")
for _ in range(60):
    REP.risk_model.add_sample({**quiet, "block_rate": 1.0}, 1)
REP.risk_model.fit()
check("60 samples are trusted", REP.risk_model.learned is True,
      f"samples={REP.risk_model.samples}")
check("the model is now allowed to raise the risk",
      REP.risk_model.predict({**quiet, "block_rate": 1.0}) > 0.5,
      f"{REP.risk_model.predict({**quiet, 'block_rate': 1.0}):.2f}")
a3 = REP.assess()
check("it now trusts what it learned", a3["model_trust"] > 0, f"trust={a3['model_trust']}")
check("but a quiet number is still not punished - it learned WHICH signal matters",
      a3["risk"] < 0.30, f"risk={a3['risk']} with zero bad signals")
check("the same features WITH blocks are dangerous",
      REP.risk_model.predict({**quiet, "block_rate": 1.0}) > 0.6,
      f"{REP.risk_model.predict({**quiet, 'block_rate': 1.0}):.2f}")
check("assess() shows priors and learning side by side",
      "prior_risk" in a3 and "model_risk" in a3,
      f"prior={a3['prior_risk']} learned={a3['model_risk']}")

print("\n=== 4. tests cannot poison the real model ===")
check("the test wrote its own model file",
      os.path.exists(os.environ["RISK_MODEL_PATH"]))
_after = _model_state()
check("the agent's own model file was never written by this test",
      _after == MODEL_BEFORE,
      "ml/risk_model.npz untouched" if _after == MODEL_BEFORE
      else f"ml/risk_model.npz CHANGED {MODEL_BEFORE} -> {_after}")

for f in (os.environ["DB_PATH"], os.environ["RISK_MODEL_PATH"]):
    if os.path.exists(f):
        os.remove(f)

print(f"\n{'=' * 62}\n  {ok} passed, {fail} failed\n{'=' * 62}\n")
sys.exit(1 if fail else 0)
