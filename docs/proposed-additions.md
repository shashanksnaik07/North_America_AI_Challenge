# PDF-centered IEP workspace

Implemented on `rtwoo/proposed-additions`. This is a local prototype using synthetic
students, simulated integrations and self-identified reviewers.

## Navigation and workflow

There are two main tabs:

* **Document** keeps the original PDF in the center. Optional page thumbnails,
  page selection, zoom, field selection and region mapping surround the canvas.
  The collapsible tools panel contains **Edit, Ask, Suggest updates,
  Accommodations, History, Summary and Review**. The equivalent structured form
  is an alternate document view. It retains the existing Alabama fields and adds
  template-specific extensions.
* **Connections & templates** contains roster synchronization, explicit student
  identity links, course evidence, stakeholder reports and the template designer.

The sidebar contains student selection, import, supporting documents and the demo
reviewer name/role. PDFs uploaded through import are archived unchanged. Existing
JSON-only sample students receive a clearly labeled generated baseline PDF.

1. Import a PDF/TXT, edit a field, submit an AI suggestion, propose an accommodation,
   synchronize demographics or restore a version.
2. A persistent review draft is created. The active IEP remains unchanged.
3. Open **Document → Review**. Toggle the red source/current preview and green
   proposed preview. The tool panel shows escaped word-level insertions/deletions;
   **Equivalent form** shows all changed fields together. Original text, evidence,
   corrections and PDF binding controls remain available.
4. Missing key data, OCR, truncation or extraction failures automatically escalate
   imports to a Specialist. Any open review can also be assigned to another named
   reviewer with a reason. Assignment is local; it sends no notification or email.
5. A named reviewer confirms having inspected the source, differences, findings
   and unmapped fields before approving. Escalated assignments require the named
   reviewer and appropriate demo role (or Administrator). Rejection changes no IEP.
6. Approval saves the record, source/binding manifest, previous version and review
   events. Stale record, document and review revisions block approval.

Roles are selected in the UI: this demonstrates workflow rules, **not authenticated
authorization, identity verification, legal consent or a production audit system**.
SQLite review updates are transactional and individual JSON saves are atomic;
the combined SQLite/filesystem save is not a crash-atomic distributed transaction.

## Original PDF editing

Exact unambiguous text matches and matching text AcroForm fields suggest locations.
Select a highlighted field to open its editor, or use **Map region** to drag a field
location. Numerical coordinates provide a keyboard-accessible alternative. Locations
can also be defined during review or saved as a reusable template design.

Edits operate on a copy of the archived PDF. Text widgets retain logical values and
appearance streams. Plain/scanned pages use bounded replacement text, preserving
the rest of the source presentation. Rotated-page coordinates are supported.
Text that cannot fit at a readable minimum size blocks approval/export. Unbound
changed fields are disclosed and exported in an addendum instead of disappearing.
They can be placed on the source by mapping a region. Review marks are preview
overlays; current/proposed exports contain the edited text without those marks.

This is a semantic field editor over original pages, not Acrobat's unrestricted
paragraph, font, object, signature or page-reordering engine. Mapping arbitrary
scanned forms requires human review. Replacement text uses the built-in Helvetica
font; arbitrary scripts/font substitution need additional work. Long text is never
silently squeezed below the minimum font size.

## SIS: OneRoster mock adapters

[OneRoster 1.2](https://www.imsglobal.org/spec/oneroster/v1p2/) provides the common
roster exchange model selected here. The local HTTP server exposes paginated REST
subsets for organizations, academic sessions, users, courses, classes and enrollments.
OAuth bearer tokens, explicit source IDs, reference validation and idempotent snapshot
replacement exercise a realistic integration boundary.

PowerSchool-style, Infinite Campus-style and Skyward-style profiles each expose
synthetic rosters with provider-specific IDs. These names label fixtures; they are
not vendor-specific APIs, vendor affiliations or certified implementations. No live
SIS credentials or network connections to those vendors are used. A student is linked
explicitly by sourced ID, never automatically by a similar name. A SIS demographic
update is another review proposal.

[Ed-Fi](https://docs.ed-fi.org/reference/data-exchange/data-standards/) is a broader
education data model worth considering for production SIS data beyond rostering.
This branch does not implement Ed-Fi or treat OneRoster as an IEP exchange standard.

## LMS: LTI launch and permitted evidence

The mock validates signed [LTI 1.3](https://www.imsglobal.org/spec/lti/v1p3/) resource
launch claims: signature, issuer, audience, expiry, nonce, state, deployment,
message/version, role and course/resource context. Private-key client assertions
obtain scoped service tokens. Replay, cross-origin pagination and cross-course
access checks are included.

* [NRPS](https://www.imsglobal.org/spec/lti-nrps/v2p0/) retrieves course membership;
  the learner is matched to the explicitly linked SIS sourced ID.
* [AGS](https://www.imsglobal.org/spec/lti-ags/v2p0/) reads this tool deployment's
  line items and permitted results/comments for that learner.

Base LTI does not offer arbitrary course-content retrieval. These services do not
grant every grade, assignment attachment, discussion, announcement or course page.
Those would need additional LMS APIs/scopes. No grade-write scope is requested.
The local `/mock/launch` endpoint simulates the platform response instead of a full
browser OIDC login/launch. Shared local keys, the synthetic roster secret and the
`demo_context` assertion claim are test scaffolding, not production registration.

Teachers and other self-identified stakeholders can submit app-owned course reports:
author, course, accommodation, usage, observed effectiveness, reporting period and
supporting observations. Reports aggregate across courses by accommodation and retain
mixed outcomes. The reports are an app feature, not a claim about an LTI reporting API.

Suggestions receive relevant linked-course reports/results with evidence IDs,
course/source/date provenance and explicit omitted-evidence IDs when the context
budget is exceeded. The draft retains the supplied evidence snapshot. Prompts ask
the model to preserve conflicting observations and avoid inferring causation from
scores or comments. Human reviewers still evaluate the proposed wording and sources.

## Template catalog and upper ontology

The catalog covers **32 PDFs from 26 states** linked from
[NASET's IEP collection](https://www.naset.com/ieps-from-around-the-country/), retrieved
November 5, 2026. It retains source URL, form date, type, page count and SHA-256.
Twenty-nine PDFs yielded native text; three required OCR (Fresno, Northwest Kansas
ESC, New York). The catalog contains **403 candidate concept-to-section crosswalks**.
These locate headings by page and do not assert validated field coordinates or
current state requirements. The dated examples remain references, not legal rules.

Following the [upper ontology](https://en.wikipedia.org/wiki/Upper_ontology) idea,
the shared model begins with Entity, Agent, InformationArtifact, Activity,
TimeInterval and Location, then specializes into Student, IEP, Goal, Service,
Accommodation, Observation, CourseReport, SourceDocument, FieldBinding and
ReviewDecision. It is an application ontology, not formal alignment with BFO/SUMO
or a jurisdiction-compliance engine.

Tracked artifacts in `templates/`:

* `catalog.json`: source provenance and candidate semantic crosswalks.
* `upper-ontology.ttl`: OWL/RDFS class hierarchy and relationships.
* `canonical.schema.json`: JSON Schema for the canonical graph.
* `iep-record.schema.json`: JSON Schema for the editable IEP projection.

The template designer previews source pages, defines typed extension fields with
ontology concepts and saves reusable PDF locations. Bindings apply only to the
exact source-PDF hash. It exports per-template JSON Schema/design/crosswalk and can
start a review draft on a reference PDF. Inspect whether a reference is blank or
contains sample content. Canonical JSON-LD exports include source and field-binding
provenance plus connected evidence. The legacy Alabama schema remains a projection;
unmodeled content survives in `extensions`, requiring review for semantic accuracy.

## Run locally

Use Python 3.12, Ollama and Tesseract OCR. In PowerShell at the repository root:

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements-dev.txt
ollama pull qwen3:8b
ollama pull nomic-embed-text
.venv\Scripts\python.exe prepare_dataset.py
.\start-local.ps1 -Background
.venv\Scripts\python.exe tools/seed_demo.py
```

The startup script finds common Windows Ollama/Tesseract installations, starts
Ollama if needed, starts the mock platform on `127.0.0.1:8502`, then Streamlit on
`http://127.0.0.1:8501`. Omit `-Background` for a foreground Streamlit process.
Logs/PIDs are in `data/runtime/`; the mock platform and Ollama run separately from
Streamlit. The seed script preserves active sample records, links Jordan to the
synthetic roster, fetches two courses, adds two differing accommodation reports and
leaves one pending comparison proposal for exploration.

On other platforms, install equivalent Ollama/Tesseract packages and start the
services explicitly:

```sh
python mock_platform.py --port 8502
python -m streamlit run app.py --server.address=127.0.0.1 --server.port=8501 --browser.gatherUsageStats=false
```

Run these in separate terminals after starting Ollama. Pull the same models first.
Qwen inference remains local; no cloud AI API key is required. Model constants and
context limits remain in `core.py`. Reference PDF downloads and the public
accommodations dataset require internet access.

To rebuild the catalog (Tesseract must be on PATH):

```powershell
.venv\Scripts\python.exe tools/build_template_catalog.py
```

Original PDFs, OCR caches, RSA test keys, SQLite records, student JSON, historical
versions, supporting documents and Chroma data stay in ignored `data/`.
`IEP_DATA_DIR` selects a separate local workspace. Deleting a student removes its
records, reviews and linked reports, while shared archived PDFs remain retained.
The prototype has no production tenancy, authentication or retention policy; use
synthetic data.

## Validation

```powershell
.venv\Scripts\python.exe -m pytest -q
uv pip check --python .venv\Scripts\python.exe
```

Tests isolate student/review/vector storage and start the mock service on an
ephemeral port. They cover review gating, escalation, stale revisions, Unicode,
source preservation, PDF layout/overflow/widgets/rotation, template reuse,
OneRoster pagination, LTI identity/replay, course isolation, report aggregation,
ontology parsing/schema and the complete edit → review → confirm UI flow.
Browser verification additionally checks the canvas and red/green source preview;
the test suite cannot establish AI extraction accuracy or educational suitability.
