"""PII gate: the first processing stage. Replaces every detected value with a stable token.

Tokens look like `<IBAN_1>`. The same value inside one record always gets the same token, so a
redacted ticket still reads coherently ("IBAN <IBAN_1> ... please re-check <IBAN_1>").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.pii.detectors import DETECTORS, Detector


@dataclass(frozen=True)
class Detection:
    field: str
    entity_type: str
    token: str
    start: int
    end: int
    method: str
    confidence: float
    checksum_valid: bool | None


@dataclass
class RedactionResult:
    fields: dict[str, str | None]
    detections: list[Detection] = field(default_factory=list)
    # token -> (entity_type, original value); handed to the vault, never logged or returned by APIs
    vault: dict[str, tuple[str, str]] = field(default_factory=dict)

    @property
    def entity_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for d in self.detections:
            counts[d.entity_type] = counts.get(d.entity_type, 0) + 1
        return counts


def _find(text: str, detectors: tuple[Detector, ...]) -> list[tuple[int, int, Detector, str]]:
    claimed: list[tuple[int, int, Detector, str]] = []
    for detector in detectors:
        for match in detector.pattern.finditer(text):
            start, end = match.span(detector.group)
            value = match.group(detector.group)
            if detector.method == "regex+checksum_required" and not (detector.validator and detector.validator(value)):
                continue
            if any(start < c_end and end > c_start for c_start, c_end, _, _ in claimed):
                continue
            claimed.append((start, end, detector, value))
    return sorted(claimed, key=lambda c: c[0])


class PiiGate:
    """Stateful per record: shares token numbering across all fields of one source record."""

    def __init__(self, detectors: tuple[Detector, ...] = DETECTORS) -> None:
        self._detectors = detectors

    def redact(self, fields: dict[str, str | None]) -> RedactionResult:
        result = RedactionResult(fields={})
        value_to_token: dict[tuple[str, str], str] = {}
        counters: dict[str, int] = {}
        for name, text in fields.items():
            if not text:
                result.fields[name] = text
                continue
            pieces: list[str] = []
            cursor = 0
            for start, end, detector, value in _find(text, self._detectors):
                key = (detector.entity_type, value)
                token = value_to_token.get(key)
                if token is None:
                    counters[detector.entity_type] = counters.get(detector.entity_type, 0) + 1
                    token = f"<{detector.entity_type}_{counters[detector.entity_type]}>"
                    value_to_token[key] = token
                    result.vault[token] = (detector.entity_type, value)
                pieces.append(text[cursor:start])
                pieces.append(token)
                cursor = end
                result.detections.append(
                    Detection(
                        field=name,
                        entity_type=detector.entity_type,
                        token=token,
                        start=start,
                        end=end,
                        method=detector.method,
                        confidence=detector.confidence,
                        checksum_valid=detector.validator(value) if detector.validator else None,
                    )
                )
            pieces.append(text[cursor:])
            result.fields[name] = "".join(pieces)
        return result


def contains_pii(text: str | None) -> bool:
    """True if any detector still matches. Used by tests and the G1 gate on everything we persist."""
    return bool(text) and bool(_find(text or "", DETECTORS))
