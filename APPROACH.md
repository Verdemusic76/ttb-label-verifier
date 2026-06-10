# Approach & architecture

A short account of how I read the brief and why the prototype is built the way
it is. The interview notes weren't background colour — they were the
requirements. Most of the real constraints are buried in what people said, not
in the "Technical Requirements" header.

## Reading the brief

What the team actually needs isn't "an AI that reviews labels." Sarah was
explicit: her agents are *capable* of judgment but are *drowning in matching*.
The job is to clear the routine volume so 47 people can spend their attention
where it belongs. That reframes the goal from "automate the decision" to
"triage the queue and route the judgment calls to a human." The whole design
follows from that.

## Constraints, and the decision each one forced

| What someone said | What it actually requires | Decision |
| --- | --- | --- |
| Sarah: the vendor pilot took 30–40s and agents abandoned it; "under ~5 seconds or nobody uses it" | A hard latency budget | One model call to *read*; all *judging* in fast local code. |
| Marcus: the network blocks outbound ML endpoints; the last vendor's features died at the firewall | Can't assume cloud AI in production | Extraction behind one interface, five readers (Anthropic / OpenAI / Gemini / Azure / on-box OCR), switched by env var. |
| Jenny: the warning must be exact — caps, verbatim; she's rejected title-case | Some checks must be exact | Warning matched verbatim to 27 CFR §16.21; uppercase heading enforced. |
| Dave: "STONE'S THROW" vs "Stone's Throw" is obviously the same — "you need judgment" | Other checks must be forgiving | Brand/class/producer matched fuzzily; near-misses flagged *for review*, not auto-rejected. |
| Sarah: the "73-year-old" benchmark; half the team is 50+ | UX is a first-class requirement | One obvious upload target, plain-language verdicts, color-coded, no hidden controls. |
| Sarah/Janet: importers dump 200–300 at once | Throughput matters | Batch endpoint reusing the identical per-label pipeline. |
| Marcus: PII, retention, "don't do anything crazy" for a POC | Don't over-build; store nothing | Stateless. No database, no retained images. |

## The architecture: read / judge / decide

```
  Label image ──► [ Extractor ]──► fields ──► [ Rules engine ]──► finding packet ──► [ Agent ]
                  AI · probabilistic        deterministic · auditable          records determination
                  (swappable)               (pure, unit-tested)                (the countersignature)
```

The seam between **reading** and **judging** is the whole idea. A vision model
is the right tool to pull text off a photo shot at an angle under bad lighting.
It is the wrong tool to *decide* whether a label is compliant, because a
regulatory rejection has to be explainable and reproducible — "the model
thought so" doesn't hold up. So extraction is AI and adjudication is fixed code.
That seam is also what keeps it fast and what makes the firewall a non-issue:
the only swappable, network-touching part is the reader.

The third stage is deliberate. The tool never *decides* — it recommends a stamp
and the agent records the determination. That keeps a human accountable for
every outcome and matches how the office already works; it also means a wrong
read degrades to "an agent looks closer," not "a label is wrongly rejected by a
machine."

## What I'd build next (in order)

1. **Pair batch with real application data** — ingest a manifest (CSV + images)
   so each label is checked against its own record, not one shared record.
2. **Pull the application side from COLA** instead of re-keying it, once the
   read-only integration is cleared.
3. **Train a custom Azure model on labels** so the firewall-friendly path gets
   full field attribution, not just the pattern-matchable fields.
4. **Confidence-driven routing** — auto-clear only high-confidence all-pass
   labels; send everything else to a person. Tune the thresholds on a labeled
   sample of real rejections.
5. **An audit log** of every recommendation and the agent's determination —
   the record a regulator would ask for.

## Honest limitations

- The AI readers are hosted models; production needs an approved in-boundary
  reader — the Azure reader (TTB is already on Azure/FedRAMP) or the on-box OCR
  path. The interface makes that a config change, but the in-boundary reader
  still has to be procured and accredited.
- Thresholds (0.90 pass / 0.72 review) are reasonable defaults, not calibrated
  on TTB data. They should be set against a real sample before anyone trusts
  the auto-clear.
- This is demonstration-grade. It proves the workflow and the latency story;
  it is not hardened for production traffic, and it deliberately stores nothing.
