# Student workspace design pass

This pass replaces a control-heavy PDF screen with a caseload and student workspace,
informed by a [comparison of existing IEP software](iep-software-comparison.md).
The original PDFs, review rules, AI services and integration adapters are unchanged.

## Main decisions

* Keep two primary tabs: **My caseload** and **Student workspace**.
* Start with a searchable caseload, a Needs review filter and direct links to
  student overviews, IEPs and pending drafts. Keep new imports in their own queue.
* Organize each student record into **Overview, IEP, Documents, Progress & reports**.
  Keep a student selector above these sections. Move templates, connections,
  example loading and removal into Tools & setup, away from routine work.
* Open the IEP in **View IEP**, with the PDF and a brief plan overview. Show
  **View IEP, Edit draft, Suggested modifications, Review drafts** as visible actions, including the
  number of pending reviews.
* Combine questions, accommodation options and AI draft changes in **Suggested
  modifications**, sharing one question/observation and candidate queue. History
  lives under Documents. Generate summary has been removed.
* Group editing fields into familiar IEP sections. Keep numerical coordinates,
  raw JSON, PDF replacement and template ontology controls in advanced disclosures.
* Preserve field-edit drafts across tool and student changes within the session.
  Drafts remain separate from approved records. The multi-section form asks users
  to submit a section before switching; its unsent edits are not durable drafts.
* Divide review into **Compare** and **Decide**. Put the reviewer name, role,
  confirmation and decision next to one another. Explain disabled approval buttons.
  Retain text labels, strike-through and insertion marks alongside red/green colors.
* Give classroom reports a dedicated student section. Keep document history and
  supporting files together. Put connection setup in its own view and describe
  ordinary actions as “Refresh course” and “Connect student.”
* Use a restrained light palette, system fonts, visible labels, generous control
  sizes and clear focus rings. Avoid remote font dependencies.
* Keep PDF and controls alongside one another on wide screens. Below 1100 px,
  stack controls at full width for active tasks; View IEP keeps the PDF first.
* Render only the active main tab, preventing hidden connection or template
  controls from doing work and distracting from the current task.

## Platform decision

Streamlit 1.66 supports the needed horizontal containers, stateful tabs and
session-persistent widgets. The dependency now requires 1.66 or newer (below 2).
This pass retains it and separates the presentation into `workspace_design.py`,
so a future frontend can still reuse `core.py`, `reviews.py`, `pdf_workspace.py`
and the integration adapters. A migration is not necessary for the revised flows.
Canvas editing remains field-based; it is not a full PDF object editor.

## Design references

The concrete choices above apply general guidance rather than claiming formal
accessibility certification or proven usability with educators:

* [USWDS forms](https://designsystem.digital.gov/components/form/): clear labels,
  related controls, useful instructions and understandable states.
* [CAST UDL Guidelines](https://udlguidelines.cast.org/): clear navigation,
  organized information and support for different ways of accessing information.
* [W3C labels and instructions](https://www.w3.org/WAI/WCAG22/Understanding/labels-or-instructions):
  persistent visible labels and instructions for user input.

The canvas has an equivalent structured form and field selector for users who
cannot point to a PDF region. A full assistive-technology audit and sessions with
teachers/case managers remain future validation work.

## Verification

The UI tests cover caseload search, student overviews, separate import context,
explicit student context in connection setup,
edit → compare → decide → approve, disabled approval gating,
empty-workspace onboarding, all retained tools and form sections, draft persistence,
student separation, and the course report → suggestion route. The service tests
continue to exercise import escalation, stale approval checks, original-PDF
preservation and integration isolation. Browser checks cover desktop and narrow
breakpoints, field selection, dialogs, reports and keyboard focus.
