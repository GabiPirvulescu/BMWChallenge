# Role 01: data conversion and evidence provenance

This layer converts explicitly supplied Excel/PDF inputs into immutable, hash-versioned records, loads those records into Neo4j, and exposes bounded evidence queries. The converter never edits or deletes input files. It does not infer source-channel meaning, customer prevalence, survey sample size, a BEV share, or a study-to-topic relationship.

## Install and run

Install the data-layer dependencies:

```powershell
python -m pip install -r pipeline/requirements-data.txt
```

Choose the raw and processed directories explicitly. The processed destination must be outside the raw directory.

```powershell
python pipeline/00_preprocess.py --raw-data-dir "<your raw source directory>" --output-dir "<your processed output directory>"
```

The converter requires at least one feedback workbook, survey workbook, sales workbook, option-catalog PDF, and corporate-report PDF. It prints the manifest status and returns a nonzero exit code for failed or incomplete conversions. Use repeated `--required-document-kind` flags to specify a different reviewed document set. Add `--check-known-feedback-counts` when validating the complete three-model export against the documented source-row and distinct-comment targets.

Set `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD`, then load a successful bundle:

```powershell
python pipeline/01_load_neo4j.py --processed-dir "<your processed output directory>"
```

To add reviewed survey relations later, provide a populated copy of `pipeline/study_topic_mappings.example.json`:

```powershell
python pipeline/01_load_neo4j.py --processed-dir "<your processed output directory>" --study-mappings "<reviewed mapping file>"
```

For an intentionally partial import, inspect `manifest.json` and then pass `--allow-partial`. The import is idempotent by source hash and stable record ID. All source, comment, annotation, fact, chunk, import-run, and injected audit-sink writes occur in the same Neo4j write transaction.

After import, run the distinct-count summary and descriptive relationship builder:

```powershell
python pipeline/03_vfc_analysis.py
python pipeline/02_build_kg.py
```

The scripts require a reachable Neo4j instance. They do not start Neo4j or fabricate empty success when the database is unavailable.

## Input recognition and intermediate format

- `.xlsx` and `.xlsm` are supported through `openpyxl`; `.pdf` is supported through `pypdf`. Excel's transient `~$` lock files are excluded from source discovery.
- Feedback workbook names should include `feedback`, `explorer`, or `hackathon`. The parser finds a sheet/header containing both an original feedback ID and text. It resolves fields by header names and preserves every nonempty source row plus its sheet/row locator.
- Survey workbook names should include `study`, `studies`, `survey`, or `customer`. All numeric cells are preserved as native facts with per-column model/market scope. Explicit `1..7` categories and seven-row percentage blocks are also represented as native distributions with exact cell locators; the sample base is not treated as respondent N, and topic mappings remain unreviewed until explicitly approved.
- Sales workbook names should include `sales`, `volume`, or `forecast`. A sales fact is emitted only when vehicle line, region, year, and source value are identifiable. Zero is retained; missing values are not converted to zero. `G60_G68` remains one sales line and no powertrain split is synthesized.
- Every PDF page is recorded, including empty/unextractable pages. Text chunks stay within their physical page, preserve exact extracted text spans, and cite 1-based physical pages. Printed page labels remain null unless later supplied from a reviewed source. Required document subtypes default to option catalogs and corporate reports so a catalog-only input set is reported as partial.
- Other workbook layouts remain available in `source_records.jsonl`; unmatched numeric cells are not silently promoted to scoped business facts.

The output has `source_files.jsonl`, `source_records.jsonl`, `feedback_comments.jsonl`, `feedback_annotations.jsonl`, `facts.jsonl`, `document_chunks.jsonl`, and `manifest.json`. IDs are derived from source-file SHA-256 and source locators/business IDs. A repeated feedback ID with conflicting text or scope is flagged and kept as separate row-backed comments. Multiple annotations on a consistent comment stay separate. `BEVE` is normalized to `BEV` while its original value remains stored. A missing label stays missing.

The manifest records converted source hashes, parser counts, per-file failures, missing required kinds, known feedback count checks, and overall `succeeded`/`partial`/`failed` state. A missing or unreadable required input cannot appear as an empty successful conversion.

## Validation

Run the synthetic parser/provider checks and, when the private `BMW-Data` folder
is present at the repository root, the real-corpus count and citation checks:

```powershell
python -m unittest discover -s tests/data -v
```

The real-corpus test checks the documented per-model feedback counts, source
discovery, sales facts, and that every PDF chunk is an exact substring of its
page record. It skips when the private source directory is absent. To produce
an inspectable bundle and manifest, run `00_preprocess.py` with explicit raw
and output directories as shown above.

## Neo4j entities and evidence queries

- `SourceFile` stores filename, content hash, kind, and conversion version.
- `SourceRecord` stores the exact workbook row or extracted PDF page payload plus a JSON locator. Facts, comments, annotations, and document chunks resolve back to these records.
- `CustomerFeedback` stores canonical comment text and original/normalized scope values. `FeedbackAnnotation` stores imported type and VFC2/VFC3 labels separately, so a comment can carry positive and negative annotations at distinct topics.
- `Fact` stores native survey cells/distributions and sourced sales values. Nested values and locators are JSON strings, while scope and measure fields remain scalar Neo4j properties.
- `DocumentChunk` stores exact page text and a physical page number.
- `StudyTopicMapping` is created only from a supplied, reviewed mapping file. Start from `pipeline/study_topic_mappings.example.json`, add exact `fact_ids`, relation (`direct`, `broad`, `contradictory`, or `unmapped`), reason, reviewer, and review time, then load with `--study-mappings <file>`. Mappings to a fact from another converted bundle are rejected.

`services.evidence` exports `EvidenceScope`, typed DTOs, and the `search_feedback`, `get_source_record`, `get_survey_facts`, `get_sales_facts`, `search_document_chunks`, and `get_comment_cohort_counts` providers. Construct `Neo4jEvidenceProvider(driver)` or configure the application-scoped provider. Search results include stable IDs, source hash/version, original text/value, exact row/cell/page locator, applicable scope, and unknowns. Provider/database failures raise `EvidenceProviderError`; they are not returned as empty evidence.

Example service usage from the backend (the backend owns driver lifecycle):

```python
from services.evidence import EvidenceScope, Neo4jEvidenceProvider

provider = Neo4jEvidenceProvider(driver)
quotes = provider.search_feedback(
    "seat ventilation", EvidenceScope(model="G70", region="US"), limit=10
)
study = provider.get_survey_facts(
    "seat ventilation", EvidenceScope(model="G70", region="US")
)
```

Until the second call has a reviewed mapping, it returns an explicit `unmapped` state instead of treating a keyword match as corroboration. Use the quote's `source_records` locator or `get_source_record(id)` to resolve the original workbook row.

Counts distinguish unique canonical comments from annotations. Topic and issue counts are separate; broad bucket counts must not be reused as narrow issue support. Source A–D values stay opaque. `pipeline/02_build_kg.py` stores source-rate differences as descriptive records and same-VFC3 mixed polarity as a review candidate. It deliberately creates no formal preference-conflict edge: that requires a reviewed preference metric, not just a source-rate gap or opposing broad feedback labels.

## Acceptance targets and current limits

For the complete export, the documented feedback targets are F70 4,076 source rows/2,128 distinct IDs; G60 5,005/4,000; G70 4,690/4,000. Run the optional count check against the supplied sources before treating those counts as reproduced. The source workbooks and PDFs are not bundled in this code branch, so no actual count, source citation, parser output, or live Neo4j import has been claimed here.

The generic workbook adapters intentionally preserve uncertain layouts instead of claiming they have fully decoded every BMW workbook. In particular, native survey cells that lack recognizable seven-category headers remain raw cell facts; sales cells lacking an explicit line/region/year remain source rows. Such data must be inspected and mapped before it can support a specific requirement. Full corpus conversion and a Neo4j import/query review remain necessary when the private source files and database are available.
