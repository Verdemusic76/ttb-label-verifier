"""Data contracts for the verification service.

Everything the API accepts or returns is defined here so the shape of a
"finding packet" is explicit and stable — that packet is the unit a human
agent acts on.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ApplicationRecord(BaseModel):
    """The values the applicant submitted — the source of truth we check against."""
    brand_name: str = ""
    class_type: str = ""
    alcohol_content: str = ""
    net_contents: str = ""
    producer_name_address: str = ""
    country_of_origin: str = ""  # blank for domestic products


class ExtractedLabel(BaseModel):
    """What the extraction layer read off the label image."""
    brand_name: Optional[str] = None
    class_type: Optional[str] = None
    alcohol_content: Optional[str] = None
    net_contents: Optional[str] = None
    producer_name_address: Optional[str] = None
    country_of_origin: Optional[str] = None
    government_warning_text: Optional[str] = None


class Status(str, Enum):
    PASS = "pass"
    REVIEW = "review"
    FAIL = "fail"


class Verdict(str, Enum):
    APPROVE = "approve"
    REVIEW = "review"
    REJECT = "reject"


class Finding(BaseModel):
    field: str
    expected: str
    found: str
    status: Status
    note: str
    confidence: float = Field(ge=0.0, le=1.0)


class FindingPacket(BaseModel):
    """The complete, routable result. A recommendation — never a decision."""
    verdict: Verdict
    findings: list[Finding]
    elapsed_seconds: float
    extractor: str
