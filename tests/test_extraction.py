"""Tests for the text-reader parser and unread-field handling.

`parse_label_text` is a pure function (no SDK, no network), so the text-reader
path is testable without Azure or Tesseract installed.
"""
from app.extraction import parse_label_text
from app.models import ApplicationRecord, ExtractedLabel, Status, Verdict
from app.rules_engine import STATUTORY_WARNING, verify


def test_parser_recovers_warning_abv_and_volume():
    ocr = (
        "OLD TOM DISTILLERY\nKentucky Straight Bourbon Whiskey\n"
        "45% Alc./Vol. (90 Proof)\n750 mL\n\n" + STATUTORY_WARNING
    )
    label = parse_label_text(ocr)
    assert label.government_warning_text.startswith("GOVERNMENT WARNING:")
    assert "45%" in label.alcohol_content
    assert "750" in label.net_contents.lower() or "ml" in label.net_contents.lower()


def test_parser_warning_exact_match_passes_rules():
    label = parse_label_text("noise\n" + STATUTORY_WARNING + "\n")
    findings, _ = verify(ApplicationRecord(), label)
    warning = next(f for f in findings if f.field == "Government warning")
    assert warning.status is Status.PASS


def test_unread_field_routes_to_review_not_reject():
    # A text reader that returns nothing for brand should NOT auto-reject it.
    record = ApplicationRecord(brand_name="OLD TOM DISTILLERY",
                               government_warning_text="")  # type: ignore[call-arg]
    label = ExtractedLabel(government_warning_text=STATUTORY_WARNING)  # brand is None
    findings, verdict = verify(
        ApplicationRecord(brand_name="OLD TOM DISTILLERY"),
        label,
    )
    brand = next(f for f in findings if f.field == "Brand name")
    assert brand.status is Status.REVIEW
    assert verdict is Verdict.REVIEW  # not REJECT
