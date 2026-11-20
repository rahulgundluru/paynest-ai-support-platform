"""Runs the G1-G7 evaluation gates and writes the report.

    python evaluations/run_evaluations.py                 # all gates, report to docs/evaluation/report.md
    python evaluations/run_evaluations.py --gates G1,G4   # selected gates
    python evaluations/run_evaluations.py --fail-on-critical

Needs DATABASE_URL (with ingested data), JWT_SECRET, PII_VAULT_KEY and DATA_SOURCE_DIR, exactly like the API.
This is a thin wrapper around `python -m app.cli evaluate` run from the backend directory.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    args = sys.argv[1:]
    if "--report" not in args:
        args += ["--report", str(ROOT / "docs" / "evaluation" / "report.md")]
    return subprocess.call([sys.executable, "-m", "app.cli", "evaluate", *args], cwd=ROOT / "backend")


if __name__ == "__main__":
    sys.exit(main())
