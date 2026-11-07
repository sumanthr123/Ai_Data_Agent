"""Checks that run in Databricks (serverless job `ai-data-agent-checks`) against the source in the workspace: backend
unit tests, then the live evaluation and its gate (evals/gate.py). Runs in-process so the job's own Databricks credentials are used.

Job parameters: --root <workspace source folder> --warehouse-id <id> [--evals all|none|1,2,3]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(globals().get("__file__", "scripts/x")).resolve().parents[1]))  # jobs run without __file__
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--evals", default="all", help="all, none, or comma-separated category numbers")
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

    if args.evals != "none":
        print("\n== live evaluation", flush=True)
        from evals import run_evals  # imported after the warehouse id is set: settings read it at import

        only = None if args.evals == "all" else {int(x) for x in args.evals.split(",")}
        _in_thread(lambda: asyncio.run(run_evals.main(only)))
        print(f"\nReport written to {root / 'evals' / 'REPORT.md'}")
        if args.evals == "all":  # thresholds need every category
            from evals import gate

            print("\n== eval gate", flush=True)
            if gate.main([]):
                return 1
    return 0


if __name__ == "__main__":
    if main():  # sys.exit(0) would show as an error in a job; only failures raise
        raise SystemExit(1)
