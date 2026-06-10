"""The extraction layer — the only part that touches a model or external service.

Every reader sits behind one interface, `Extractor`, so the adjudication code
never knows or cares how the label was read. Swapping readers is one
environment variable; nothing downstream changes. That is the whole answer to
the firewall question, and it lets the same prototype demonstrate several
procurement paths.

Readers (set EXTRACTOR=...):
  vision     Anthropic vision model. Full field read. Needs ANTHROPIC_API_KEY.   [default]
  openai     OpenAI-compatible vision model. Full field read. Needs OPENAI_API_KEY.
  gemini     Google Gemini via its OpenAI-compatible endpoint. Needs GEMINI_API_KEY.
  azure      Azure AI Document Intelligence (read). On Treasury's existing stack.
  local-ocr  On-box Tesseract. No key, no outbound calls — the air-gapped path.

Capability note: the AI readers (vision / openai / gemini) attribute every
field. The text readers (azure / local-ocr) reliably recover the
compliance-critical, pattern-matchable fields — the government warning (checked
exactly), ABV, and net contents — and leave the rest for an agent. A
production Azure path would use a custom model trained on labels for full
field attribution; see README.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
from abc import ABC, abstractmethod

from .models import ExtractedLabel

_PROMPT = (
    "You are reading a single alcohol beverage label image. Extract these "
    "fields and respond with ONLY a JSON object — no prose, no markdown "
    "fences. Keys: brand_name, class_type, alcohol_content, net_contents, "
    "producer_name_address, country_of_origin, government_warning_text. Use "
    "null for anything not visible. Transcribe government_warning_text EXACTLY "
    "as printed, preserving capitalization and punctuation. Do not correct or "
    "normalize anything."
)


# --- shared helpers ----------------------------------------------------------

def _coerce(raw: dict) -> ExtractedLabel:
    """Keep only known keys; tolerate extra fields the model may invent."""
    allowed = ExtractedLabel.model_fields.keys()
    return ExtractedLabel(**{k: raw.get(k) for k in allowed})


def _parse_json_response(text: str) -> ExtractedLabel:
    text = text.replace("```json", "").replace("```", "").strip()
    return _coerce(json.loads(text))


def parse_label_text(text: str) -> ExtractedLabel:
    """Best-effort field recovery from flat OCR text (no layout).

    Reliably recovers the pattern-matchable fields. The government warning is
    a fixed string, so it is found directly — which is the field that matters
    most for compliance. Brand / class / producer need layout or a model and
    are left to an agent (the rules engine routes unread fields to review).
    """
    warning = None
    m = re.search(r"GOVERNMENT WARNING.*", text, re.IGNORECASE | re.DOTALL)
    if m:
        # Take the whole block to end-of-text and collapse OCR line breaks;
        # the warning is bottom-of-label by regulation, so over-capture is rare.
        warning = re.sub(r"\s+", " ", m.group(0)).strip()

    abv = None
    m = re.search(r"\d+(?:\.\d+)?\s*%\s*(?:alc|abv)?[^,\n]*", text, re.IGNORECASE)
    if m:
        abv = m.group(0).strip()

    net = None
    m = re.search(r"\d+(?:\.\d+)?\s*(?:ml|l|fl\.?\s*oz|oz|liter|litre)\b", text, re.IGNORECASE)
    if m:
        net = m.group(0).strip()

    return ExtractedLabel(
        alcohol_content=abv,
        net_contents=net,
        government_warning_text=warning,
    )


# --- interface ---------------------------------------------------------------

class Extractor(ABC):
    name: str

    @abstractmethod
    def extract(self, image_bytes: bytes, media_type: str) -> ExtractedLabel:
        ...


# --- AI readers (full field attribution) -------------------------------------

class VisionExtractor(Extractor):
    """Anthropic vision. Robust to angle/glare/typography. Needs outbound access."""
    name = "vision"

    def __init__(self) -> None:
        import anthropic
        self._client = anthropic.Anthropic()
        # Current model; override with VISION_MODEL (e.g. claude-haiku-4-5-20251001
        # for lower cost, or claude-sonnet-4-6 for more robustness on poor photos).
        self._model = os.environ.get("VISION_MODEL", "claude-sonnet-4-6")

    def extract(self, image_bytes: bytes, media_type: str) -> ExtractedLabel:
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": media_type,
                        "data": base64.standard_b64encode(image_bytes).decode(),
                    }},
                    {"type": "text", "text": _PROMPT},
                ],
            }],
        )
        text = "".join(b.text for b in msg.content if b.type == "text")
        return _parse_json_response(text)


class OpenAICompatExtractor(Extractor):
    """Any OpenAI-compatible vision endpoint.

    Covers OpenAI directly and Google Gemini via its OpenAI-compatible base URL,
    so 'use a different provider' is a config change, not new code.
    """

    def __init__(self, name: str, api_key_env: str, default_model: str,
                 model_env: str, base_url: str | None = None) -> None:
        from openai import OpenAI
        self.name = name
        self._client = OpenAI(api_key=os.environ.get(api_key_env), base_url=base_url)
        self._model = os.environ.get(model_env, default_model)

    def extract(self, image_bytes: bytes, media_type: str) -> ExtractedLabel:
        data_url = f"data:{media_type};base64,{base64.standard_b64encode(image_bytes).decode()}"
        resp = self._client.chat.completions.create(
            model=self._model,
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": _PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
        )
        return _parse_json_response(resp.choices[0].message.content or "")


# --- text readers (compliance-core fields; firewall-friendly) ----------------

class AzureExtractor(Extractor):
    """Azure AI Document Intelligence (prebuilt 'read').

    Strategic fit: TTB is already on Azure and FedRAMP'd, so this reads labels
    inside the existing authorization boundary instead of via a new third party.
    Free tier (F0) covers 500 pages/month — ample for evaluation. Needs
    AZURE_DI_ENDPOINT and AZURE_DI_KEY.
    """
    name = "azure"

    def __init__(self) -> None:
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.core.credentials import AzureKeyCredential
        endpoint = os.environ["AZURE_DI_ENDPOINT"]
        key = os.environ["AZURE_DI_KEY"]
        self._client = DocumentIntelligenceClient(endpoint, AzureKeyCredential(key))

    def extract(self, image_bytes: bytes, media_type: str) -> ExtractedLabel:
        # SDK: azure-ai-documentintelligence (>=1.0.0). 'prebuilt-read' returns
        # full text in result.content, which we hand to the shared parser.
        poller = self._client.begin_analyze_document(
            "prebuilt-read", body=image_bytes, content_type="application/octet-stream",
        )
        result = poller.result()
        return parse_label_text(getattr(result, "content", "") or "")


class LocalOcrExtractor(Extractor):
    """On-box Tesseract OCR. No key, no outbound calls — the air-gapped path.
    Requires the system package `tesseract-ocr`."""
    name = "local-ocr"

    def extract(self, image_bytes: bytes, media_type: str) -> ExtractedLabel:
        import pytesseract
        from PIL import Image
        text = pytesseract.image_to_string(Image.open(io.BytesIO(image_bytes)))
        return parse_label_text(text)


# --- selection ---------------------------------------------------------------

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"


def get_extractor() -> Extractor:
    """Choose the reader from EXTRACTOR. Defaults to the Anthropic vision reader."""
    choice = os.environ.get("EXTRACTOR", "vision").lower()
    if choice == "openai":
        return OpenAICompatExtractor("openai", "OPENAI_API_KEY", "gpt-4o", "OPENAI_MODEL")
    if choice == "gemini":
        return OpenAICompatExtractor("gemini", "GEMINI_API_KEY", "gemini-2.5-flash",
                                     "GEMINI_MODEL", base_url=_GEMINI_BASE)
    if choice == "azure":
        return AzureExtractor()
    if choice == "local-ocr":
        return LocalOcrExtractor()
    return VisionExtractor()
