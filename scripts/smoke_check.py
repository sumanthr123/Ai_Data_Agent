"""Smoke test steps that read or write JSON; a failure exits non-zero with the reason."""
import json
import os
import sys

expected = os.environ["DEFAULT_DATASET"]
step = sys.argv[1]
if step == "body":
    print(json.dumps({"question": os.environ["SMOKE_QUESTION"], "council": os.environ["COUNCIL"] == "true"}))
elif step == "datasets":
    shared = [d["dataset"] for d in json.load(sys.stdin) if d["kind"] == "shared"]
    print("Listed:", shared)
    if shared[:1] != [expected]:
        sys.exit(f"The UI would preselect {shared[:1]}, not {expected}")
elif step == "answer":
    text = sys.stdin.read()
    r = json.loads(text)
    print(r["status"], "reviewed" if r["verification"]["reviewed"] else "not reviewed", r["verification"]["total_tokens"], "tokens")
    if r["status"] != "ANSWERED" or not r["verification"]["reviewed"]:
        sys.exit(f"Not a reviewed answer: {r['status']}")
    if expected not in text:
        sys.exit(f"The answer didn't use {expected}")
else:
    sys.exit(f"Unknown step {step}")
