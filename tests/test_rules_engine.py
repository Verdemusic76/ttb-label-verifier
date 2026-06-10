"""Rules-engine tests.

These pin down the behaviors the stakeholders actually called out:
Dave's "STONE'S THROW" punctuation/case case, Jenny's title-case warning
rejection, and the basics of each field check.
"""
from app.models import ApplicationRecord, ExtractedLabel, Status, Verdict
from app.rules_engine import STATUTORY_WARNING, verify


def _record(**kw) -> ApplicationRecord:
    base = dict(
        brand_name="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol. (90 Proof)",
        net_contents="750 mL",
        producer_name_address="Old Tom Distillery, Bardstown, KY",
    )
    base.update(kw)
    return ApplicationRecord(**base)


def _clean_label(**kw) -> ExtractedLabel:
    base = dict(
        brand_name="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol. (90 Proof)",
        net_contents="750 mL",
        producer_name_address="Old Tom Distillery, Bardstown, KY",
        government_warning_text=STATUTORY_WARNING,
    )
    base.update(kw)
    return ExtractedLabel(**base)


def _find(findings, field):
    return next(f for f in findings if f.field == field)


def test_clean_label_approves():
    findings, verdict = verify(_record(), _clean_label())
    assert verdict is Verdict.APPROVE
    assert all(f.status is Status.PASS for f in findings)


def test_stones_throw_case_and_punctuation_matches():
    # Dave's example: same brand, different case/punctuation -> still a match.
    findings, _ = verify(
        _record(brand_name="STONE'S THROW"),
        _clean_label(brand_name="Stone's Throw"),
    )
    assert _find(findings, "Brand name").status is Status.PASS


def test_warning_must_be_uppercase():
    # Jenny's catch: title-case "Government Warning:" is a rejection.
    bad = STATUTORY_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:")
    findings, verdict = verify(_record(), _clean_label(government_warning_text=bad))
    w = _find(findings, "Government warning")
    assert w.status is Status.FAIL
    assert "capital letters" in w.note
    assert verdict is Verdict.REJECT


def test_missing_warning_rejects():
    findings, verdict = verify(_record(), _clean_label(government_warning_text=None))
    assert _find(findings, "Government warning").status is Status.FAIL
    assert verdict is Verdict.REJECT


def test_abv_mismatch_rejects():
    findings, verdict = verify(_record(), _clean_label(alcohol_content="40% Alc./Vol. (80 Proof)"))
    assert _find(findings, "Alcohol content").status is Status.FAIL
    assert verdict is Verdict.REJECT


def test_abv_small_tolerance_flags_for_review():
    findings, verdict = verify(_record(), _clean_label(alcohol_content="45.3% Alc./Vol."))
    assert _find(findings, "Alcohol content").status is Status.REVIEW
    assert verdict is Verdict.REVIEW


def test_proof_inconsistency_flags_for_review():
    findings, _ = verify(_record(), _clean_label(alcohol_content="45% Alc./Vol. (100 Proof)"))
    assert _find(findings, "Alcohol content").status is Status.REVIEW


def test_country_of_origin_only_checked_when_required():
    # Domestic record (blank country) -> no country finding emitted.
    findings, _ = verify(_record(), _clean_label())
    assert all(f.field != "Country of origin" for f in findings)
    # Import record -> country is checked.
    findings, _ = verify(
        _record(country_of_origin="Product of Scotland"),
        _clean_label(country_of_origin="Product of Scotland"),
    )
    assert _find(findings, "Country of origin").status is Status.PASS


def test_garbled_brand_fails():
    findings, verdict = verify(_record(), _clean_label(brand_name="Acme Vodka Co"))
    assert _find(findings, "Brand name").status is Status.FAIL
    assert verdict is Verdict.REJECT


def test_ocr_near_match_warning_routes_to_review():
    # Correct caps heading, one OCR-style typo in the body -> review, not fail.
    noisy = STATUTORY_WARNING.replace("operate machinery", "operate machlnery")
    findings, verdict = verify(_record(), _clean_label(government_warning_text=noisy))
    w = _find(findings, "Government warning")
    assert w.status is Status.REVIEW
    assert verdict is Verdict.REVIEW


def test_materially_altered_warning_still_fails():
    # Dropping the second clause is a real alteration -> fail.
    altered = "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink during pregnancy."
    findings, verdict = verify(_record(), _clean_label(government_warning_text=altered))
    assert _find(findings, "Government warning").status is Status.FAIL
    assert verdict is Verdict.REJECT
