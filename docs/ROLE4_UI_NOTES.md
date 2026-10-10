# Role 4: PM workbench (frontend)

## Run

```bash
pip install -r ui/requirements.txt

# against the configured API (API_BASE_URL, else localhost:API_PORT)
streamlit run pipeline/08_streamlit_ui.py

# real pipeline results, read-only (output/requirements_full.json), no API or Neo4j needed
streamlit run pipeline/08_streamlit_ui.py -- --snapshot

# labelled SYNTHETIC preview, no API needed
streamlit run pipeline/08_streamlit_ui.py -- --fixtures

# Role 3's own contract examples (contracts/fixture_case.json), synthetic, decisions simulated in memory
streamlit run pipeline/08_streamlit_ui.py -- --mock

# tests
python -m pytest tests/frontend -q
```

After editing a file in `ui/`, restart Streamlit: it reloads `pipeline/08_streamlit_ui.py` on change but keeps the `ui` modules it already imported.

The snapshot mode reads `output/requirements_full.json` (the pipeline's export step); without that file it says so and the other sources still work.

## Files

| File | Purpose |
|---|---|
| `pipeline/08_streamlit_ui.py` | Pages, sheets (dialogs) and routing. No scoring, no guards, no DB or model calls. |
| `ui/client.py` | The only HTTP adapter. Speaks the planned `/api` contract and falls back to the legacy step 07 routes. Normalises `gate`/`gate_color`, maps `CONFLICTED` to `PM_REVIEW` + conflict flag, keeps failures (`ApiError`) separate from empty results. |
| `ui/overview.py` | Portfolio overview: KPI tiles, priority vs evidence scatter, topic volume, review progress, top priorities per vehicle. Counts and plots only. |
| `ui/snapshot.py` | Read-only client over the pipeline's own export, for demos when the API is down. Legacy 0–10 scale, all writes refused. |
| `ui/forms.py` | Turns what the PM entered into exactly one request (decision payload, edit patch). |
| `ui/fixtures.py` | Synthetic data and an in-memory client with the same interface. Used for demos and tests only, always labelled. |
| `ui/contract_mock.py` | "Backend contract mock (synthetic)": serves `contracts/fixture_case.json` through the live client's normalisers; simulates decisions and freezes (revision +1, 409 stale, 422 blank rationale / incomplete review). |
| `contracts/` | `openapi.json` and `fixture_case.json`, checked out from `origin/backend`. Source of truth for data types; do not edit here. |
| `ui/theme.py`, `ui/components.py` | Apple HIG-inspired styling and escaped HTML helpers. |
| `.streamlit/config.toml` | Base theme colours. |
| `tests/frontend/` | Client, fixture and AppTest checks. |

## Repair checklist coverage

| Item | Where |
|---|---|
| R09 API origin from config | `resolve_base_url()` reads `config.API_BASE_URL`, then `API_PORT` |
| R01/R03 decision form | `decision_sheet`: reviewed targets, reviewed sources, accepted assumptions, rationale, explicit override toggle (0 is sent as 0, off sends nothing) |
| Only allowed actions | buttons come from the server's `allowed_actions`; v1 does not send it yet, so all five are shown and the server's 409/422 decides |
| R16 range wording | "sensitivity / provisional range, not a statistical confidence interval" |
| R17 evidence gap | REQ-FIX-002 fixture; "No customer comments support this requirement", "gap means no data, not zero demand" |
| R19 full export | `client.download()` asks the server; legacy mode refuses instead of rebuilding a 200-row file |
| R07/R15/R18 | quotes open their source record; AI/PM provenance and review pills; empty history shown as "not proof" |
| 409 / 422 | 409 keeps the draft or rationale and offers reload; 422 lists each problem |
| Apply vs approve | separate requests; apply sheet states that it does not approve |

## Backend contract mapping (origin/backend)

`ui/client.py` maps the v1 `RequirementDetail` into the shape the pages render. It renames and reshapes only.

| Backend | UI |
|---|---|
| `score.calculated_score` / `effective_score` | `score.calculated` / `effective` |
| `score.scale` `[min, max]` | `{policy, min, max, label}` |
| `score.factors` (dict) | list of `{key, label, value, weight, contribution, provisional, reason, lower, upper}`; a factor range is shown only when the server sends `lower`/`upper` that differ |
| `score.range` | `{low, high, kind, label}`, always worded as not a statistical confidence interval |
| `evidence.value` | `evidence.eci` (plus `level`, `components`, `distinct_support_comments`, `range`, `warnings`) |
| `evidence_links` + `source_snapshots` | quote rows (text only from the server's snapshot) |
| `smart.metrics[]` + `smart.milestone` | `smart.targets[]`, one row each; `review_state: pending` shows as "Not reviewed" |
| `assumptions[].description` / `review_state` | `text` / `state` (`pending` shows as "Open") |
| history `{revisions, events}` | `events` only; `timestamp` → `time`, `actor_role` → `actor_kind` |
| list `{items, total, offset, ranking_id}` | `ranking_id` is kept and sent as `expected_ranking_id` when freezing |
| `/sources` (list of `SourceFile` nodes) | `{files: [{file, kind, version, …}]}` for the Sources page |
| `SourceRecord` / `DocumentChunk` (`SR-…` / `DOC-…`) | `{id, file, locator, values}`; spreadsheet `raw_payload.columns` become header → value |
| `PATCH` edit | RequirementDraft fields only: `smart` is sent whole with the edited metric targets set to `PMEntered` / `pending`; `target_scope` whole |

Requests sent: `DecisionRequest` with `actor_role: "PM_USER"`, `reviewed_target_ids`, `accepted_assumption_ids`, `reviewed_source_ids` and `score_override` as a plain number (absent when the PM did not override). `FreezeRequest` as `{selections: {id: revision}, expected_ranking_id, actor_id, actor_role, rationale}`. Review threads: `GET /api/review-threads/{id}`, challenges via `POST /api/requirements/{rid}/challenges` (the question is also sent as the required rationale), proposals via `/api/requirements/{rid}/proposals`.

## Requests to Role 3 (API)

1. Add `API_BASE_URL` to `config.py` / `CONFIGURATION.md`. The UI already reads it.
2. **Please return `allowed_actions` in `RequirementDetail`.** It is missing from the v1 contract, so the UI shows all five actions and relies on the server's 409/422 to refuse invalid ones (TODO in `normalize_detail`).
3. Please add `GET /api/requirements/{rid}/review-threads`. Today a thread is found only through a pending proposal or a challenge made in the same session, so read-only answers from other sessions cannot be listed.
4. Please include the field's previous value in a turn's `change_preview` (e.g. `old_content`). The UI currently shows the loaded requirement's value as "before".

## Verified against the real backend

The UI's `ApiClient` was run against `services/api.py` from `origin/backend` (39e9a25), built like `tests/backend/generate_contracts.py` (memory repository, fake evidence and engine), on Python 3.12: list and filters, detail, evidence, history, challenge → thread, v1 edit, stale edit (409), incomplete approval (422), approval with a 0 override, freeze, stale ranking (409), every export, analysis run, proposal discard, and every page and tab rendered. Not covered: the Neo4j source provider (Sources page tested with Role 1's node shapes in `tests/frontend/test_live_shapes.py`).

The shapes the UI renders are what `ui/fixtures.py` returns; `ui/contract_mock.py` checks the real contract against them.

The data source can also be switched in the sidebar (Live API, Pipeline snapshot, Backend contract mock (synthetic), Synthetic preview). Nothing falls back silently: if the API is unreachable the UI says so and offers the other sources as buttons.
