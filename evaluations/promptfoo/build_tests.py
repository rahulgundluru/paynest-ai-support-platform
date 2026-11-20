"""Generates Promptfoo tests from the labelled G4 dataset so both stay in sync.

    python evaluations/promptfoo/build_tests.py   # writes evaluations/promptfoo/tests.yaml
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATASET = HERE.parent / "datasets" / "g4_injection_synthetic.jsonl"


def main() -> None:
    lines = ["# Generated from ../datasets/g4_injection_synthetic.jsonl by build_tests.py. Do not edit by hand.", ""]
    for raw in DATASET.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        case = json.loads(raw)
        expected = "true" if case["expected"] == "block" else "false"
        lines += [
            f"- description: {json.dumps(case['id'] + ' ' + case['technique'], ensure_ascii=False)}",
            "  vars:",
            f"    subject: {json.dumps(case['subject'], ensure_ascii=False)}",
            f"    body: {json.dumps(case['body'], ensure_ascii=False)}",
            "  assert:",
            "    - type: is-json",
            "    - type: javascript",
            f"      value: JSON.parse(output).is_injection === {expected}",
        ]
    (HERE / "tests.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote tests.yaml")


if __name__ == "__main__":
    main()
