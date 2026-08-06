# Native COAir forensic parity

> **Closed to project users** — see [delay-toolkit.md](delay-toolkit.md). The
> toolkit's own Streamlit app now serves programme forensics at `/toolkit/`.

The canonical calculation and reporting reference is the vendored Delay
Analysis Toolkit at the commit recorded in
`vendor/delay-analysis-toolkit.upstream.json`. Production does not run its
Streamlit shell. COAir calls the same pure Python engines and upstream export
builders, then renders typed view models in React.

## Safety and rollout

- Administrators can always validate the parity APIs. `FORENSIC_PARITY_UI_V1`
  records that an environment is in validation mode, but does not expose the
  workflow to project users. Only the separate, deliberate
  `FORENSIC_PARITY_PUBLIC_V1` cutover flag grants non-admin access; until then
  non-admin users receive 404.
- Existing `forensic_programmes`, workspaces, runs and artifacts remain
  readable. Schema changes are additive and never delete or rewrite them.
- Selecting an existing project source creates a content-hash-pinned hard-link
  snapshot when possible, otherwise a verified copy or an explicitly labelled
  text-only evidence pack. A snapshot is not charged to the user's storage
  quota a second time.
- A workspace source revision hashes immutable sources and scopes. Analyst
  decisions use a separate optimistic `state_version`; stale edits receive
  HTTP 409.
- Runs are immutable and record both source revision and state version. A retry
  is accepted only when both still match.

## Parity contracts

`backend/services/forensic_toolkit/parity.py` inventories controls, steps,
actions, views, submodules and artifacts for all 19 upstream screens.
`presentation.py` maps each engine result to an explicit metric, table and chart
contract. There is no recursive table discovery or generic chart fallback.

The current native boundary includes:

- all 19 deterministic engine entry points and their upstream workbooks;
- upstream Gantt and Path Studio HTML where the engine supplies it;
- upstream Report Assembler Word output using actual immutable runs and
  versioned analyst choices;
- OOS repaired-XER and TIA impacted-XER builders;
- project XER, PDF, Word, text, email, Excel and CSV selection without reupload;
- verified TIA event extraction, contract-clause mapping, fragnet and logic
  recommendations;
- sequence mapping review and module narratives through central Gemini 3.6
  Flash, with COAir ledger attribution and HTTP 402 credit enforcement.

AI output never bypasses the toolkit's parsers. Verbatim source quotations,
programme activity identifiers, stage names, fragnet links and network logic
are validated deterministically before versioned workspace state is updated.

## Upstream updates

The weekly sync workflow records both a whole-tree digest and an independent
upstream UI/workflow digest. Engine-only updates are tested and may merge after
all upstream, native, frontend and integrity tests pass. Any change to upstream
views, shared state or `test_ui.py` leaves a review PR open so production cannot
silently lose a new control or analyst decision step.

Run the relevant checks locally with:

```bash
python scripts/verify_forensic_vendor.py
(cd vendor/delay-analysis-toolkit && python test_engine.py && python test_qa.py)
(cd vendor/delay-analysis-toolkit && pytest -q test_programme.py test_rlpa.py test_ui.py)
PYTHONPATH=. pytest -q tests/test_forensic_engines.py tests/test_forensic_store.py \
  tests/test_forensic_programme_service.py tests/test_forensic_api_models.py \
  tests/test_forensic_actions.py
(cd frontend && npm run build)
```
