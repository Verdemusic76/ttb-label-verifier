"""Deterministic adjudication.

This module contains no I/O and no AI. Given an application record and the
fields read off a label, it decides — by fixed, inspectable rules — whether
each field matches. It is fast (microseconds), reproducible, and unit-tested.

Design split: AI *reads* the label (fuzzy, probabilistic); these rules *judge*
it (exact, auditable). The government warning is checked verbatim against the
statute, never fuzzily.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .models import (
    ApplicationRecord,
    ExtractedLabel,
    Finding,
    FindingPacket,
    Status,
    Verdict,
)

# 27 CFR §16.21 — the mandatory Government Health Warning, verbatim.
STATUTORY_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should "
    "not drink alcoholic beverages during pregnancy because of the risk of "
    "birth defects. (2) Consumption of alcoholic beverages impairs your "
    "ability to drive a car or operate machinery, and may cause health "
    "problems."
)

# Tunable thresholds for fuzzy text fields.
PASS_THRESHOLD = 0.90
REVIEW_THRESHOLD = 0.72


def _normalize(s: str | None) -> str:
    """Lowercase, drop punctuation, collapse whitespace. This is what makes
    'STONE'S THROW' and 'Stone's Throw' the same string."""
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r"[^\w\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _similarity(a: str | None, b: str | None) -> float:
    x, y = _normalize(a), _normalize(b)
    if not x and not y:
        return 1.0
    if not x or not y:
        return 0.0
    return SequenceMatcher(None, x, y, autojunk=False).ratio()


def _check_fuzzy(field: str, expected: str, found: str | None) -> Finding:
    if not found:
        return Finding(field=field, expected=expected, found="—",
                       status=Status.REVIEW, note="Couldn't read this field — needs an agent",
                       confidence=0.0)
    score = _similarity(expected, found)
    if score >= PASS_THRESHOLD:
        status, note = Status.PASS, "Matches application"
    elif score >= REVIEW_THRESHOLD:
        status, note = Status.REVIEW, "Close — needs an agent's eye"
    else:
        status, note = Status.FAIL, "Does not match application"
    return Finding(field=field, expected=expected, found=found,
                   status=status, note=note, confidence=round(score, 2))


def _parse_abv(s: str | None) -> tuple[float | None, float | None]:
    s = s or ""
    pct = re.search(r"(\d+(?:\.\d+)?)\s*%", s)
    proof = re.search(r"(\d+(?:\.\d+)?)\s*proof", s, re.IGNORECASE)
    return (float(pct.group(1)) if pct else None,
            float(proof.group(1)) if proof else None)


def _check_abv(expected: str, found: str | None) -> Finding:
    field = "Alcohol content"
    if not found:
        return Finding(field=field, expected=expected, found="—",
                       status=Status.REVIEW, note="Couldn't read this field — needs an agent",
                       confidence=0.0)
    e_abv, _ = _parse_abv(expected)
    f_abv, f_proof = _parse_abv(found)
    if e_abv is None or f_abv is None:
        return Finding(field=field, expected=expected, found=found,
                       status=Status.REVIEW, note="Could not read a numeric ABV", confidence=0.5)
    diff = abs(e_abv - f_abv)
    if diff < 0.05:
        status, note, conf = Status.PASS, "ABV matches application", 1.0
    elif diff <= 0.5:
        status, note, conf = Status.REVIEW, f"ABV off by {diff:.1f}% — within tolerance, confirm", 0.6
    else:
        status, note, conf = Status.FAIL, f"ABV differs by {diff:.1f}%", 0.0
    # Proof should equal 2x ABV; flag inconsistency.
    if f_proof is not None and abs(f_proof - f_abv * 2) > 0.5:
        note += f"; stated proof ({f_proof:g}) ≠ 2× ABV"
        if status is Status.PASS:
            status, conf = Status.REVIEW, 0.6
    return Finding(field=field, expected=expected, found=found,
                   status=status, note=note, confidence=conf)


def _check_warning(found: str | None) -> Finding:
    field = "Government warning"
    if not found:
        return Finding(field=field, expected=STATUTORY_WARNING, found="—",
                       status=Status.FAIL, note="Mandatory warning is missing", confidence=0.0)

    def ws(x: str) -> str:
        return re.sub(r"\s+", " ", x).strip()

    if ws(found) == ws(STATUTORY_WARNING):
        return Finding(field=field, expected=STATUTORY_WARNING, found=found,
                       status=Status.PASS, note="Verbatim match to 27 CFR §16.21", confidence=1.0)

    # Diagnose the most actionable reason it failed.
    if "GOVERNMENT WARNING:" not in found and re.search(r"government warning:", found, re.IGNORECASE):
        return Finding(field=field, expected=STATUTORY_WARNING, found=found,
                       status=Status.FAIL,
                       note='"GOVERNMENT WARNING:" must appear in capital letters', confidence=0.0)
    if not re.search(r"government warning", found, re.IGNORECASE):
        return Finding(field=field, expected=STATUTORY_WARNING, found=found,
                       status=Status.FAIL,
                       note='Required "GOVERNMENT WARNING:" heading is absent', confidence=0.0)

    # Heading is present and correctly capitalized, but not a byte-exact capture.
    # A near-match is almost always OCR noise on a compliant label, so confirm
    # with a human rather than auto-rejecting; a real alteration scores low and
    # still fails.
    score = _similarity(found, STATUTORY_WARNING)
    if score >= 0.92:
        return Finding(field=field, expected=STATUTORY_WARNING, found=found,
                       status=Status.REVIEW,
                       note="Reads as the statutory warning but the capture isn't byte-exact — agent confirms wording",
                       confidence=round(score, 2))
    return Finding(field=field, expected=STATUTORY_WARNING, found=found,
                   status=Status.FAIL, note="Wording does not match the statute exactly", confidence=0.0)


def verify(record: ApplicationRecord, label: ExtractedLabel) -> tuple[list[Finding], Verdict]:
    """Run every rule and roll the findings up into a recommended verdict."""
    findings = [
        _check_fuzzy("Brand name", record.brand_name, label.brand_name),
        _check_fuzzy("Class / type", record.class_type, label.class_type),
        _check_abv(record.alcohol_content, label.alcohol_content),
        _check_fuzzy("Net contents", record.net_contents, label.net_contents),
        _check_fuzzy("Producer name / address", record.producer_name_address, label.producer_name_address),
    ]
    if record.country_of_origin.strip():
        findings.append(_check_fuzzy("Country of origin", record.country_of_origin, label.country_of_origin))
    findings.append(_check_warning(label.government_warning_text))

    if any(f.status is Status.FAIL for f in findings):
        verdict = Verdict.REJECT
    elif any(f.status is Status.REVIEW for f in findings):
        verdict = Verdict.REVIEW
    else:
        verdict = Verdict.APPROVE
    return findings, verdict


def build_packet(record: ApplicationRecord, label: ExtractedLabel,
                 elapsed: float, extractor: str) -> FindingPacket:
    findings, verdict = verify(record, label)
    return FindingPacket(verdict=verdict, findings=findings,
                         elapsed_seconds=round(elapsed, 2), extractor=extractor)
