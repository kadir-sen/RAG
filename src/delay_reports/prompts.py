"""Prompt templates for the delay-report pipeline.

Both prompts operate ONLY on supplied structured input; the deterministic
guards (register containment, chronology guard) are the enforcement — these
instructions minimize rejects, they are not the safety mechanism.
"""

EXTRACTION_PROMPT = """\
You are extracting dated events for the delay event "{event_title}" from
construction-project correspondence evidence.

For EACH evidence item below, decide whether it contains a dated event
relevant to "{event_title}". If yes, emit one JSON object; if no, skip it.

Fields per object:
- "evidence_id": the [En] id of the item the event came from
- "event_date": the date the described action HAPPENED, copied in its
  ORIGINAL surface form from the text (e.g. "19 July 2023"). This is the
  correspondence/action date, NOT any publication or upload date.
- "document_date": the document's own date if separately stated, else null
- "actor": the acting/sending party exactly as written (e.g. "JAMED")
- "recipient": the receiving party if stated, else null
- "action_verb": one of stated | noted | informed | requested | raised |
  forwarded | proposed | reserved | notified | instructed | submitted
- "issue": one sentence — what the correspondence is about
- "impact": stated impact on works/programme, else null
- "requested_action": what was requested/proposed, else null
- "reservation_of_rights": true only if the text reserves rights to claim
  time/cost
- "quote": a verbatim excerpt (max 40 words) COPIED EXACTLY from the evidence
  text, containing the date and the actor where possible

Hard rules:
- NEVER infer or compute a date. If no explicit date is in the text, skip.
- NEVER paraphrase inside "quote" — copy characters exactly.
- One object per distinct dated event; an item may yield zero or one object.

Return a JSON array only.

EVIDENCE ITEMS:
{evidence}
"""

NARRATIVE_PROMPT = """\
You are drafting a claim-report chronology section for the delay event
"{event_title}" in the exact style of forensic delay narratives.

Write one numbered paragraph per row of the CHRONOLOGY ROWS below, in the
given order, using paragraph numbers exactly as given (e.g. {example_para}).

Paragraph pattern:
"{example_para} On <date>, <actor> <hedged verb> <recipient/subject> regarding
<issue>. <Context/impact sentence from the row>. <Requested action or
reservation sentence, only if present in the row>. (<file_name>, p.<page>)"

Hard rules:
- Date first, exactly as given in the row (format: '19 July 2023' style).
- Use hedged reporting verbs: stated / noted / raised concerns / requested /
  advised / reserved its rights. Statements are the party's CLAIMS, not
  established facts — never present them as proven.
- End EVERY paragraph with the source reference exactly as given in the row.
- Do not add any date, party, cause, amount or conclusion not present in the
  rows. No legal conclusions (never: entitled, liable, breach, culpable,
  proves).
- {cause_intro_rule}

CHRONOLOGY ROWS:
{rows}
"""
