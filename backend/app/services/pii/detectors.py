"""Deterministic PII detectors (regex + format validation).

Design rules (from Phase 0 discovery):
- Detection is on FORMAT. Checksums (Verhoeff, mod-97, Luhn) only set `checksum_valid`; a failed
  checksum never un-redacts a value. The case data's synthetic IDs ("0000 …", "AE00 …") fail them.
- Detectors run in priority order and claim spans; a later detector cannot match inside an earlier
  span. This stops the Aadhaar pattern from matching digit groups inside an IBAN.
- Person names are NOT detected yet (no NER model configured). This is a known gap; see docs.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Detector:
    entity_type: str
    pattern: re.Pattern[str]
    confidence: float
    group: int = 0
    validator: Callable[[str], bool] | None = None
    method: str = "regex"


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


_VERHOEFF_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_VERHOEFF_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


_VERHOEFF_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def verhoeff_valid(value: str) -> bool:
    digits = _digits(value)
    if len(digits) != 12 or digits[0] in "01":  # real Aadhaar numbers never start with 0 or 1
        return False
    check = 0
    for i, ch in enumerate(reversed(digits)):
        check = _VERHOEFF_D[check][_VERHOEFF_P[i % 8][int(ch)]]
    return check == 0


def iban_valid(value: str) -> bool:
    compact = re.sub(r"\s", "", value).upper()
    if len(compact) < 15:
        return False
    rearranged = compact[4:] + compact[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    return int(numeric) % 97 == 1


def luhn_valid(value: str) -> bool:
    digits = [int(d) for d in _digits(value)]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return bool(digits) and total % 10 == 0


def pan_structure_valid(value: str) -> bool:
    # 4th character encodes the holder type (P person, C company, H HUF, F firm, ...).
    return value[3] in "PCHFATBLJG"


# Order matters: earlier detectors claim their spans first.
DETECTORS: tuple[Detector, ...] = (
    Detector("IBAN", re.compile(r"\bAE\d{2}(?: ?\d{4}){4} ?\d{3}\b"), 0.99, validator=iban_valid),
    Detector(
        "IBAN",
        re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b"),
        0.9,
        validator=iban_valid,
        method="regex+checksum_required",
    ),
    Detector("EMIRATES_ID", re.compile(r"\b784[- ]?\d{4}[- ]?\d{7}[- ]?\d\b"), 0.99, validator=luhn_valid),
    Detector(
        "BANK_ACCOUNT",
        re.compile(r"(?i)\b(?:a/c|acct|account)(?:\s*(?:no\.?|number|#))?\s*[:\-]?\s*(\d{9,18})\b"),
        0.95,
        group=1,
        method="regex+context",
    ),
    Detector("IFSC", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b"), 0.95),
    Detector("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), 0.95, validator=pan_structure_valid),
    Detector("AADHAAR", re.compile(r"(?<![\d-])\d{4}[ -]?\d{4}[ -]?\d{4}(?![\d-])"), 0.9, validator=verhoeff_valid),
    Detector("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"), 0.99),
    Detector("PHONE", re.compile(r"(?<![\w+])(?:\+91|\+971)[ -]?\d[\d -]{7,12}\d\b"), 0.95),
    Detector("PHONE", re.compile(r"(?<!\d)[6-9]\d{9}(?!\d)"), 0.6, method="regex_low_confidence"),
)

ENTITY_TYPES = tuple(sorted({d.entity_type for d in DETECTORS}))
