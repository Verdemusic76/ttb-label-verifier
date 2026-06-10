#!/usr/bin/env python3
"""Air-gapped reader demo.

Runs the on-box (Tesseract) reader and the deterministic rules engine on a
single label image. No API key, no network — proves the firewall-friendly path
works with the cable pulled.

Usage (from the repo root):
    python scripts/airgap_demo.py path/to/label.png

Prerequisite (install once, with the network ON):
    macOS:  brew install tesseract
    Ubuntu: sudo apt-get install tesseract-ocr
    Python: pip install pytesseract Pillow
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.extraction import LocalOcrExtractor          # noqa: E402
from app.models import ApplicationRecord               # noqa: E402
from app import rules_engine as rules                  # noqa: E402

# The application record we're checking the label against.
RECORD = ApplicationRecord(
    brand_name="OLD TOM DISTILLERY",
    class_type="Kentucky Straight Bourbon Whiskey",
    alcohol_content="45% Alc./Vol. (90 Proof)",
    net_contents="750 mL",
    producer_name_address="Old Tom Distillery, Bardstown, KY",
)

MARK = {"pass": "PASS  ", "review": "REVIEW", "fail": "FAIL  "}


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python scripts/airgap_demo.py path/to/label.png")
        return 2
    image_path = Path(sys.argv[1])
    if not image_path.exists():
        print(f"No such file: {image_path}")
        return 2

    print("=" * 60)
    print(" READER: local-ocr (on-box Tesseract)   OUTBOUND CALLS: none")
    print("=" * 60)

    try:
        label = LocalOcrExtractor().extract(image_path.read_bytes(), "image/png")
    except Exception as e:  # noqa: BLE001
        print(f"\nReader unavailable: {e}")
        print("Install Tesseract first (see the header of this file).")
        return 1

    findings, verdict = rules.verify(RECORD, label)
    print()
    for f in findings:
        print(f"  [{MARK[f.status.value]}] {f.field:<26} {f.note}")
    print()
    print(f"  RECOMMENDED VERDICT: {verdict.value.upper()}")
    print("  (the agent records the final determination)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
