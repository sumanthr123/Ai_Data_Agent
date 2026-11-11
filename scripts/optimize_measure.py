"""Optimization evidence, measured in a Databricks job so nothing runs on a workstation: unit tests, static analysis
(ruff, vulture, deptry, knip), install size, cold start, and six fixed questions with tools, tokens and latency.
Every part records its own failure instead of stopping the run; the result is one JSON file in <root>/optimize_out/.

Job parameters: --root <workspace copy> --warehouse-id <id> --label <name> [--parts tests,static,size,start,questions] [--repeat 3]
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unittest
from pathlib import Path
from typing import Any

PARTS = ("tests", "static", "size", "start", "questions")
PORT = 8765
# Each case is a conversation; the last turn is the one measured.
CASES = [
    ("lakehouse_1", ["What were total sales by region in 2017?"]),
    ("lakehouse_2", ["How many orders were placed in 2016?"]),
    ("live", ["What is the stock price of Robinhood (HOOD) today?"]),
    ("general", ["Explain the difference between a Delta table and a view in two sentences."]),
    ("follow_up", ["What were total sales by region in 2017?", "And for 2016?"]),
    ("write", ["Drop the first table in the schema."]),
]


def in_thread(fn: Any) -> Any:
    """The job kernel already runs an event loop; asyncio.run() needs a thread without one."""
    out: dict[str, Any] = {}

    def target() -> None:
        try:
            out["value"] = fn()
        except BaseException as exc:
            out["error"] = exc
    t = threading.Thread(target=target)
    t.start()
    t.join()
    if "error" in out:
        raise out["error"]
    return out.get("value")


def tool(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None, keep: int = 20000, timeout: int = 900) -> dict[str, Any]:
    try:
        done = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        return {"rc": done.returncode, "out": (done.stdout + done.stderr)[-keep:]}
    except Exception as exc:
        return {"rc": None, "out": repr(exc)}


def size_mb(path: Path) -> float:
    return round(sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink()) / 1e6, 1)


def app_env(root: Path) -> dict[str, str]:
    """The plain `value:` settings from app.yaml, so the measured agent is configured like the deployed one."""
    pairs = re.findall(r"-\s*name:\s*(\w+)\s*\n\s*value:\s*\"([^\"]*)\"", (root / "app.yaml").read_text())
    return {k: v for k, v in pairs if "{" not in v}


def node_tools() -> tuple[Path, str, str]:
    import nodejs_wheel
    home = Path(nodejs_wheel.__file__).parent
    return home, str(home / "bin" / "node"), str(home / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js")


def part_tests() -> dict[str, Any]:
    buf = io.StringIO()
    result = in_thread(lambda: unittest.TextTestRunner(stream=buf, verbosity=1).run(
        unittest.defaultTestLoader.discover("backend/tests", top_level_dir=".")))
    return {"ran": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
            "passed": result.wasSuccessful(), "detail": buf.getvalue()[-6000:] if not result.wasSuccessful() else ""}


def frontend_copy(root: Path) -> tuple[Path, dict[str, str], dict[str, Any]]:
    home, node, npm = node_tools()
    work = Path(tempfile.mkdtemp()) / "frontend"
    shutil.copytree(root / "frontend", work, ignore=shutil.ignore_patterns("node_modules", "dist"))
    env = {**os.environ, "PATH": f"{home / 'bin'}:{work / 'node_modules' / '.bin'}:{os.environ['PATH']}"}
    return work, env, tool([node, npm, "ci", "--no-audit", "--no-fund"], work, env, keep=3000)


def part_static(root: Path) -> dict[str, Any]:
    py = ["app.py", "backend", "evals", "scripts", "data"]
    out: dict[str, Any] = {
        "versions": {t: tool([sys.executable, "-m", t, "--version"])["out"].strip() for t in ("ruff", "vulture", "deptry")},
        "ruff": tool([sys.executable, "-m", "ruff", "check", *py, "--select", "F401,F811,F841,ERA001", "--output-format", "concise", "--no-cache"]),
        "vulture_80": tool([sys.executable, "-m", "vulture", *py, "--min-confidence", "80"]),
        "vulture_60": tool([sys.executable, "-m", "vulture", *py, "--min-confidence", "60"]),
        "deptry": tool([sys.executable, "-m", "deptry", ".", "--requirements-files", "requirements.txt", "--extend-exclude", "frontend|data"]),
    }
    if out["deptry"]["rc"] not in (0, 1):
        out["deptry_help"] = tool([sys.executable, "-m", "deptry", "--help"], keep=6000)
    work, env, install = frontend_copy(root)
    out["npm_ci"] = install
    if install["rc"] == 0:
        _, node, npm = node_tools()
        out["knip"] = tool([node, npm, "exec", "--yes", "--", "knip", "--no-progress"], work, env)
        out["frontend_tests"] = tool([node, "--test", *sorted(str(p.relative_to(work)) for p in work.rglob("*.test.ts") if "node_modules" not in p.parts)], work, env, keep=3000)
        out["frontend_types"] = tool(["tsc", "-b", "--noEmit"], work, env, keep=3000)
    return out


def part_size(root: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    target = Path(tempfile.mkdtemp()) / "site"
    install = tool([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--target", str(target), "-r", "requirements.txt"], keep=3000)
    out["python"] = ({"install_mb": size_mb(target), "resolved_packages": len(list(target.glob("*.dist-info")))} if install["rc"] == 0
                     else {"error": install["out"]})
    work, _, install = frontend_copy(root)
    if install["rc"] == 0:
        lock = json.loads((work / "package-lock.json").read_text())
        out["node"] = {"install_mb": size_mb(work / "node_modules"), "resolved_packages": sum(1 for k in lock.get("packages", {}) if k)}
    else:
        out["node"] = {"error": install["out"]}
    return out


def part_start(root: Path) -> dict[str, Any]:
    env = {**os.environ, "PYTHONPATH": str(root)}
    timer = "import time; t = time.perf_counter(); import app; print(round(time.perf_counter() - t, 3))"
    imports = [tool([sys.executable, "-c", timer], root, env, keep=1500) for _ in range(3)]
    out: dict[str, Any] = {"import_app_s": [float(i["out"].strip().splitlines()[-1]) for i in imports if i["rc"] == 0]}
    if len(out["import_app_s"]) < 3:
        out["import_error"] = next(i["out"] for i in imports if i["rc"] != 0)
    else:
        out["import_app_median_s"] = statistics.median(out["import_app_s"])
    # Ready = uvicorn's own "running on" line: the job sandbox refuses loopback connections, so /api/health can't be polled.
    log = Path(tempfile.mkdtemp()) / "server.log"
    began = time.perf_counter()
    with log.open("wb") as sink:
        server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "info"],
                                  cwd=root, env=env, stdout=sink, stderr=sink)
        try:
            while time.perf_counter() - began < 60 and server.poll() is None:
                if "Uvicorn running on" in log.read_text(errors="replace"):
                    out["server_ready_s"] = round(time.perf_counter() - began, 2)
                    break
                time.sleep(0.05)
            if "server_ready_s" not in out:
                out["server_error"] = f"not ready (exit {server.poll()}): " + log.read_text(errors="replace")[-1500:]
        finally:
            server.terminate()
            server.wait(15)
    return out


async def ask_all(repeat: int) -> list[dict[str, Any]]:
    from databricks.sdk import WorkspaceClient

    from backend.ask.cache import ResultCache
    from backend.ask.contracts import AskRequest, AuthContext, ConversationState
    from backend.ask.models import ServingClient
    from backend.ask.orchestrator import DatabricksData, Orchestrator
    from backend.ask.settings import AskSettings
    from backend.ask.tracing import Tracer

    w, cfg = WorkspaceClient(), AskSettings()
    rows: list[dict[str, Any]] = []
    for attempt in range(repeat):
        for case, turns in CASES:
            state, r, error = ConversationState(), None, ""
            try:
                for n, question in enumerate(turns):
                    orch = Orchestrator(cfg, DatabricksData(w, cfg, threading.Event()), ServingClient(w, cfg.efforts()),
                                        AuthContext(mode="service_principal"), "optimize", ResultCache(1), Tracer(""))
                    r = await orch.run(AskRequest(question=question, datasets=[cfg.default_dataset] if n == 0 else [], state=state))
                    state = r.state
            except Exception as exc:
                error = f"{exc!r}\n{traceback.format_exc()[-600:]}"
            if r is None or error:
                rows.append({"case": case, "attempt": attempt, "error": error})
                continue
            calls = [c for c in r.verification.calls if c.status == "ok"]
            rows.append({
                "case": case, "attempt": attempt, "question": turns[-1], "status": r.status, "kind": r.kind, "reviewed": r.verification.reviewed,
                "tools": [e.stage for e in r.events if e.status == "succeeded"], "events": [f"{e.stage}:{e.status}" for e in r.events],
                "calls": [c.purpose for c in calls], "failed_calls": [f"{c.purpose}:{c.status}" for c in r.verification.calls if c.status != "ok"],
                "input_tokens": sum(c.prompt_tokens for c in calls), "output_tokens": sum(c.completion_tokens for c in calls),
                "reasoning_tokens": sum(c.reasoning_tokens for c in calls), "total_tokens": r.verification.total_tokens,
                "ms": r.total_ms, "sql": bool(getattr(r, "sql", "")), "answer": r.answer[:700]})
            print(f"{case:12} {r.status:10} {rows[-1]['input_tokens']:6} in {rows[-1]['output_tokens']:5} out {r.total_ms / 1000:5.1f}s {rows[-1]['tools']}", flush=True)
    return rows


def part_questions(repeat: int) -> dict[str, Any]:
    rows = in_thread(lambda: asyncio.run(ask_all(repeat)))
    good = [r for r in rows if "error" not in r]
    summary = {}
    for case, _ in CASES:
        mine = [r for r in good if r["case"] == case]
        if mine:
            summary[case] = {"runs": len(mine), "statuses": sorted({r["status"] for r in mine}), "tools": sorted({" > ".join(r["tools"]) for r in mine}),
                             "median_ms": statistics.median(r["ms"] for r in mine), "median_input_tokens": statistics.median(r["input_tokens"] for r in mine),
                             "median_output_tokens": statistics.median(r["output_tokens"] for r in mine)}
    overall = {"median_ms": statistics.median(r["ms"] for r in good), "median_input_tokens": statistics.median(r["input_tokens"] for r in good),
               "median_output_tokens": statistics.median(r["output_tokens"] for r in good)} if good else {}
    return {"errors": [r for r in rows if "error" in r], "summary": summary, "overall": overall,
            "cache_tokens": "not reported: the serving endpoints in use return no cache token counts", "runs": good}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--parts", default=",".join(PARTS))
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()
    root = Path(args.root)
    os.chdir(root)
    sys.path.insert(0, str(root))
    os.environ.update(app_env(root))
    os.environ["DATABRICKS_WAREHOUSE_ID"] = args.warehouse_id
    wanted = [p for p in args.parts.split(",") if p]
    unknown = sorted(set(wanted) - set(PARTS))
    if unknown:
        raise SystemExit(f"Unknown parts: {unknown}")
    steps = {"tests": part_tests, "static": lambda: part_static(root), "size": lambda: part_size(root),
             "start": lambda: part_start(root), "questions": lambda: part_questions(args.repeat)}
    result: dict[str, Any] = {"label": args.label, "python": sys.version.split()[0], "parts": wanted}
    crashed = []
    for name in wanted:
        print(f"== {name}", flush=True)
        began = time.perf_counter()
        try:
            result[name] = steps[name]()
        except Exception as exc:
            crashed.append(name)
            result[name] = {"crashed": f"{exc!r}\n{traceback.format_exc()[-2000:]}"}
        print(f"   {time.perf_counter() - began:.0f}s", flush=True)
    out = root / "optimize_out"
    out.mkdir(exist_ok=True)
    (out / f"{args.label}.json").write_text(json.dumps(result, indent=1, default=str))
    tests_ok = result.get("tests", {}).get("passed", True)
    print(f"written {out / (args.label + '.json')}; crashed parts: {crashed or 'none'}; tests passed: {tests_ok}")
    return 1 if crashed or not tests_ok else 0


if __name__ == "__main__":
    code = main()
    if code:
        raise SystemExit(code)
