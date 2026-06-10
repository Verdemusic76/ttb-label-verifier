# TTB Label Verification — prototype

Reads an alcohol beverage label, checks it against the application record, and
emits a recommended verdict for a compliance agent to act on. Built as a
standalone proof-of-concept — no COLA integration, no stored PII.

## What it does

- Upload a label image (or a batch of them).
- A **reader** pulls the fields off the label.
- A deterministic **rules engine** compares each field to the application record.
- The mandatory government warning is checked **verbatim** against 27 CFR §16.21.
- You get a per-field finding packet and a recommended stamp — **Approved /
  For review / Rejected** — and the agent records the final determination.

## The one design decision that matters

**AI reads; rules judge; a human decides.** The label is read by a probabilistic
process, but every accept/reject call is made by fixed, inspectable code that
runs in microseconds. Three consequences fall out of that split: it stays well
under the 5-second floor; why a label passed or failed is a line of code, not a
model's opinion; and the reader is the *only* swappable part.

## Pluggable readers

Reading sits behind one interface (`app/extraction.py`). Pick a reader with the
`EXTRACTOR` environment variable. This is what makes the firewall a non-issue
and lets one prototype speak to several procurement paths.

| `EXTRACTOR` | Reader | Fields | Needs | Why you'd pick it |
| --- | --- | --- | --- | --- |
| `vision` *(default)* | Anthropic vision | all | `ANTHROPIC_API_KEY` | Fastest to stand up; robust on bad photos. |
| `openai` | OpenAI vision | all | `OPENAI_API_KEY` | Already hold an OpenAI key. |
| `gemini` | Gemini (OpenAI-compat) | all | `GEMINI_API_KEY` | Already in Google's ecosystem. |
| `azure` | Azure AI Document Intelligence | warning, ABV, volume | `AZURE_DI_ENDPOINT`, `AZURE_DI_KEY` | TTB is already on Azure/FedRAMP — reads inside the existing boundary. |
| `local-ocr` | On-box Tesseract | warning, ABV, volume | nothing | Air-gapped / firewalled. No key, no outbound calls. |

The AI readers attribute every field. The **text readers** (`azure`,
`local-ocr`) reliably recover the compliance-critical, pattern-matchable fields
— ABV, net contents, and the government warning. A high-fidelity reader
confirms the warning verbatim (pass); when a noisy OCR pass can't capture it
byte-for-byte, the warning is flagged for an agent to confirm rather than
falsely rejected, while a materially altered warning still fails. Everything a
text reader can't attribute is routed to an agent, never guessed. Optional
override env vars: `VISION_MODEL`, `OPENAI_MODEL`, `GEMINI_MODEL`. Model names
move; confirm the current one for your provider at deploy time.

## Run locally

```bash
pip install -r requirements.txt          # core + Anthropic reader + Tesseract
export ANTHROPIC_API_KEY=sk-...
uvicorn app.main:app --reload
# open http://localhost:8000
```

Each non-default reader pulls one extra package (imported only when selected):

```bash
pip install openai                       # EXTRACTOR=openai  or  =gemini
pip install azure-ai-documentintelligence   # EXTRACTOR=azure
# local-ocr needs the system package: apt-get install tesseract-ocr
```

## Tests

```bash
python -m pytest
```

The suite pins the stakeholder-named behaviors — the punctuation/case brand
match, the uppercase-warning rejection, a missing warning, ABV mismatch vs.
tolerance, import-only country checks — plus the OCR text parser and the rule
that an unread field goes to *review*, never an automatic reject.

## Deploy

One container, one URL. The container binds to the platform-assigned `$PORT`.

```bash
docker build -t ttb-label-verifier .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=sk-... ttb-label-verifier
```

Pushes cleanly to any container host (Cloud Run, Render, Railway, Fly, Azure
Container Apps). Set `EXTRACTOR` and the matching credentials for whichever
reader you want live.

## Air-gapped demo

Prove the firewall-friendly path with no network. Install Tesseract once
(`brew install tesseract` on macOS, `apt-get install tesseract-ocr` on Ubuntu),
then — even with wifi off:

```bash
python scripts/airgap_demo.py scripts/sample_label.png
```

It reads the bundled sample label with on-box OCR and prints the finding packet.
No API key, no outbound calls. `scripts/sample_label.png` is a ready-made test
label; swap in your own.

## Layout

```
app/
  models.py         data contracts (ApplicationRecord, Finding, FindingPacket)
  rules_engine.py   deterministic checks — pure, no I/O, unit-tested
  extraction.py     five readers behind one interface + shared OCR text parser
  main.py           FastAPI: /verify, /verify-batch, serves the UI
  static/index.html the agent-facing UI
scripts/
  airgap_demo.py    on-box, no-network demo
  sample_label.png  ready-made test label
tests/              rules-engine + parser tests
Dockerfile          single-container deploy
```

## Assumptions & trade-offs

- **Batch** runs each label against the current record; production pairs each
  label with its own application (e.g., a CSV + image set). The per-label
  pipeline is identical.
- **Text readers** (`azure`, `local-ocr`) recover the pattern-matchable fields
  today. Full field attribution from a flat OCR pass needs layout; the
  production Azure path is a **custom model trained on labels**, which returns
  field-level key/values directly. That's the next increment for the
  firewall-friendly path.
- **No persistence.** Nothing is stored — deliberate, given the PII and
  retention notes from IT.
- The warning text is current as of this build; source it from the CFR at
  deploy time rather than hard-coding it long-term.
