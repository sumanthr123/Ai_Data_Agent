"""Checks that run in Databricks (serverless job `ai-data-agent-checks`) against the source in the workspace: backend
unit tests, then the live evaluation and its gate (evals/gate.py). Runs in-process so the job's own Databricks credentials are used.

Job parameters: --root <workspace source folder> --warehouse-id <id> [--evals all|none|1,2,3]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any, Callable


def _in_thread(fn: Callable[[], Any]) -> Any:
    """Job tasks run inside a notebook kernel whose event loop is already running, so asyncio.run() is refused there.
    A plain thread has no loop of its own."""
    out: dict[str, Any] = {}

    def target() -> None:
        try:
            out["value"] = fn()
        except BaseException as exc:  # re-raised in the caller
            out["error"] = exc

    t = threading.Thread(target=target)
    t.start()
    t.join()
    if "error" in out:
        raise out["error"]
    return out.get("value")


def _frontend(root: Path) -> bool:
    """Types, lint, tests and build with Node from the nodejs-wheel package, in a temp copy (no node_modules on /Workspace).
    The built dist goes back to the source folder, so deploys use a UI built here."""
    import nodejs_wheel

    home = Path(nodejs_wheel.__file__).parent
    node, npm = str(home / "bin" / "node"), str(home / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js")
    work = Path(tempfile.mkdtemp()) / "frontend"
    shutil.copytree(root / "frontend", work, ignore=shutil.ignore_patterns("node_modules", "dist"))
    env = {**os.environ, "PATH": f"{home / 'bin'}:{work / 'node_modules' / '.bin'}:{os.environ['PATH']}"}
    steps = [("install", [node, npm, "ci", "--no-audit", "--no-fund"]), ("types", ["tsc", "-b", "--noEmit"]),
             ("lint", ["oxlint", "src", "--deny-warnings"]),
             ("tests", [node, "--test", "src/lib/markdown.test.ts", "src/assistant/format.test.ts", "src/assistant/followups.test.ts"]),
             ("build", [node, npm, "run", "build", "--silent"])]
    for name, cmd in steps:
        done = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True)
        print(f"{name}: {'ok' if done.returncode == 0 else 'FAILED'}", flush=True)
        if done.returncode:
            print((done.stdout + done.stderr)[-3000:])
            return False
    target = root / "frontend" / "dist"
    if target.exists():  # replace, not merge: old hashed bundles would otherwise ship with every deploy
        shutil.rmtree(target)
    shutil.copytree(work / "dist", target)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(globals().get("__file__", "scripts/x")).resolve().parents[1]))  # jobs run without __file__
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--evals", default="all", help="all, none, or comma-separated category numbers")
    parser.add_argument("--frontend", action="store_true", help="also run frontend types, lint, tests and build")
    parser.add_argument("--save-baseline", action="store_true", help="keep this gate's metrics as the release baseline")
    parser.add_argument("--env", action="append", default=[], help="KEY=VALUE set before settings are read")
    args = parser.parse_args()
    os.environ.update(e.split("=", 1) for e in args.env)
    root = Path(args.root)
    os.chdir(root)
    sys.path.insert(0, str(root))
    os.environ["DATABRICKS_WAREHOUSE_ID"] = args.warehouse_id

    print("== backend unit tests", flush=True)
    result = _in_thread(lambda: unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover("backend/tests", top_level_dir=".")))
    if not result.wasSuccessful():
        print("Unit tests failed; skipping the live evaluation.")
        return 1

    if args.frontend:
        print("\n== frontend", flush=True)
        if not _frontend(root):
            return 1

    if args.evals != "none":
        print("\n== live evaluation", flush=True)
        from evals import run_evals  # imported after the warehouse id is set: settings read it at import

        only = None if args.evals == "all" else {int(x) for x in args.evals.split(",")}
        _in_thread(lambda: asyncio.run(run_evals.main(only)))
        print(f"\nReport written to {root / 'evals' / 'REPORT.md'}")
        if args.evals == "all":  # thresholds need every category
            from evals import gate

            print("\n== eval gate", flush=True)
            if gate.main(["--save-baseline"] if args.save_baseline else []):
                return 1
    return 0


if __name__ == "__main__":
    if main():  # sys.exit(0) would show as an error in a job; only failures raise
        raise SystemExit(1)
