"""Checks that run in Databricks (serverless job `ai-data-agent-checks`) against the source in the workspace: backend
unit tests, then the live evaluation. Runs in-process so the job's own Databricks credentials are used.

Job parameters: --warehouse-id <id> [--evals all|none|1,2,3]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--evals", default="all", help="all, none, or comma-separated category numbers")
    args = parser.parse_args()
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    os.environ["DATABRICKS_WAREHOUSE_ID"] = args.warehouse_id

    print("== backend unit tests", flush=True)
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover("backend/tests", top_level_dir="."))
    if not result.wasSuccessful():
        print("Unit tests failed; skipping the live evaluation.")
        return 1

    if args.evals != "none":
        print("\n== live evaluation", flush=True)
        from evals import run_evals  # imported after the warehouse id is set: settings read it at import

        only = None if args.evals == "all" else {int(x) for x in args.evals.split(",")}
        asyncio.run(run_evals.main(only))
        print(f"\nReport written to {ROOT / 'evals' / 'REPORT.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
