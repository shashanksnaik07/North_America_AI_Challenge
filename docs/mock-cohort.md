# Practice IEP review cohort

The local cohort contains 384 fictional students: the 12 Hong Kong EDB example
types crossed with all 32 NASET catalog entries (26 states). IDD and ASD retain
separate tiered-support variants. Each student has a current baseline, a pending
three-field modification, two courses, four graded assignments with instructor
comments, and two direct student/family reports. There are 384 drafts, 1,536 LMS
results and 768 direct reports. Nothing is automatically approved.

## Source use

- Hong Kong EDB supplies example categories and planning structure. Scenario
  prose, identities, dates and observations are independently authored. Source
  identities, clinical narratives and achieved outcomes are not copied.
- Robworks supplies referenced accommodation IDs, names and revisions. Its
  editorial evidence ratings remain unverified provenance, not proof of benefit.
- IEP/UDL conversations inform question patterns only (zero-based rows 1, 2, 40).
  Source answers, identifiers and system prompts are not imported as student facts.
- NASET supplies original forms and section crosswalks. All source hashes are
  checked against the pinned local snapshots before use.

See the [dataset assessment](dataset-integration.md). Generated artifacts remain
in ignored `data/`; no dataset is published and no model is trained. Source
families stay linked so template variants are not mistaken for independent cases.

## Original PDF presentation

Each packet starts with **original NASET form pages**, populated in measured
response areas. `templates/mock_layouts.json` pins the areas to source PDF hashes.
Original headings, tables and page graphics are retained. A narrow student header
identifies each packet. Small response fields link to full wording on continuation
pages after the original form. Additional schema fields also appear there. This
is not a claim that every native box is filled or that a state approved the mapping.

Completed-example sources use selected planning pages cleared of previous answers:
Fresno 3/8/9, Fontana 5/13/23, Louisiana 2/3/12/14, Montana sample 3/6/10 and
Washington sample 6/8/11. The complete unchanged source remains separately available.
Consent, signatures, assessment decisions and eligibility are not adopted from
examples. Where a supplied form lacks a general annual-goal worksheet, goals use
continuation pages rather than an unrelated or restricted section.

Red/green comparisons highlight mapped original fields, with matching full text
on linked continuation pages and in Form view. Human review and stale-record checks
still gate approval. Migrated workspaces open the original present-levels page.
Age and grade are adapted for elementary, secondary and North Dakota age-band forms.
Hong Kong categories and support tiers are not treated as U.S. eligibility decisions.

## Grades and course feedback

Teacher observations primarily come from graded LMS line-item comments:
Mathematics (Emily Harper) and English language arts (Daniel Reed). Each course has
two assignments with points earned, maximum points, instructor identity and comments.
Direct student and caregiver reports remain separate. Grades and feedback appear
in **Progress & reports** and enter Suggested modifications context with citations
and course identity. They do not establish accommodation effectiveness or an official
course average; all values are authored practice data.

The `dataset-demo` roster uses OneRoster-shaped school, course, user and enrollment
records served by the local platform. Course refresh exercises signed LTI 1.3
launches, NRPS membership and AGS results. Standard AGS `scoringUserId` is resolved
against the exact course membership. Missing grader IDs remain unattributed.
`comment`, `resultScore` and `resultMaximum` provide feedback and grades. Grading dates
use an explicitly named mock provider extension because AGS results do not require
a grading date. Only line items shared with the tool are available; this does not
claim access to every LMS assignment. See the
[1EdTech AGS specification](https://www.imsglobal.org/spec/lti-ags/v2p0/).

Older generated teacher reports remain in audit storage but are superseded by
active gradebook snapshots. Drafts propose clearer support delivery, updated needs
and a four-week review interval instead of six weeks.

## Use and verification

In **My caseload**, filter by Mock profile, Template state or NASET form. Open
**Review draft** for seeded changes or **IEP > Suggested modifications** to discuss
evidence, explore accommodation options and prepare changes. Generate summary is
removed; questions, options and proposed edits share one persistent draft workflow.

```powershell
.venv\Scripts\python.exe tools/seed_mock_cohort.py
.venv\Scripts\python.exe tools/refresh_mock_cohort.py
.venv\Scripts\python.exe tools/seed_mock_cohort.py --verify-only
```

The seed supports repeated `--case` and `--template` filters. It preserves complete
pairs and human decisions on rerun. The refresh upgrades only untouched generated
fixtures, preserves stable student/review IDs, archives old packets and reports,
and skips human edits or completed reviews. All replacements are built and checked
before installation. Sources must already be in `data/reference_sources/` and
`data/reference/`; changed or missing sources fail validation.

Coverage lives in `data/mock_cohort/manifest.json`. Per-student provenance is
available under **View IEP > Case and template provenance**. Verification checks
schema, pairing identity, PDF rendering and bindings, form-field trees, course
scope and instructor attribution. Tests cover isolation, idempotency, unchanged
source PDFs, explicit review gates and grade/comment context in model prompts.
