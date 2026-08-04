# Construction chronology generation

## Why the old pipeline failed intermittently

The first AI implementation retrieved up to 120 passages and asked one model
call to plan, interpret and write the complete structured chronology.  A
response that stopped at the model's output limit could end in the middle of a
JSON string.  That text was cached before JSON parsing, so retrying the same
topic could replay the same invalid response.

Chronology V2 never treats malformed text as a result.  Provider finish reason,
JSON syntax, schema, source IDs, numbers and quotations are checked before any
response cache or report record is marked ready.

## The manual reference workflow

The successful manual method used for the canonical Edinburgh reports was:

1. Identify the issue and isolate the PDFs likely to contain its record.
2. Convert those documents to readable Markdown with page boundaries.
3. Give the evidence and the required chronology format to the authoring model.
4. Review dates, statements and footnotes against the original record.

V2 automates the same sequence without re-running OCR for every report:

1. Jargon-aware research questions cover contract, programme, change, party
   positions, delay, dispute resolution and missing evidence.
2. Dense and lexical retrieval propose source documents for user review.
3. Existing page text becomes a job-scoped Markdown evidence pack.
4. The pack is extracted in bounded batches.  Successful batches are durable
   checkpoints and survive retry.
5. Candidates are deduplicated, sorted by event date, synthesised and checked
   against their exact source excerpts.
6. The deterministic Word renderer applies numbering and real footnotes.

## Canonical style contract

The six files under `content/chronologies` are golden fixtures.  Across those
reports the authored record contains 9–18 events, normally 44–64 words per
event, and roughly one or two footnotes per event.  Those values guide style;
they are not quotas.  Sparse evidence produces a sparse report, never invented
events.

The first numbered paragraph frames the contract/work package, parties,
intended arrangement, issue and period.  Later paragraphs normally follow this
shape:

> On [event date], [actor] issued or recorded [document/action], stating
> [attributed position], with [source-supported immediate consequence].

Facts, party positions and inferences remain distinct.  A document date is not
silently substituted for the event date described inside it.  Entitlement,
critical path, prolongation and root cause are included only when the cited
record supports that proposition.

## Source-to-paragraph examples

- An SDS Scope of Services supplies the obligation and document date.  The
  output may state that the scope was issued and describe the obligation, but
  it cannot state that the obligation caused delay without a second source that
  establishes that link.
- A contractor notice and an employer response become two attributed positions
  within one event or two events on their respective dates.  Neither position
  is promoted to an established fact.
- A mediation record supplies the date and agreed outcome.  It does not prove
  the duration of critical delay unless the same or another cited record states
  that duration.

## Operations and troubleshooting

Run a targeted legacy cache audit before deploying V2:

```bash
python scripts/cleanup_chronology_cache.py
python scripts/cleanup_chronology_cache.py --apply
```

Only chronology response namespaces are selected.  OCR, embedding and chat
caches are not removed.

Failed jobs expose a stable user-facing error code and keep their sequence
number.  Retrying resumes validated extraction checkpoints.  Admin diagnostics
show the technical error and step attempts without exposing them to normal
users.
