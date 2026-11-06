# IEP software comparison and interface decisions

Reviewed November 5, 2026. This comparison uses public vendor documentation and
product descriptions. It is not a hands-on evaluation
of authenticated district deployments; configurations and terminology vary by
state and district. The interface adopts familiar workflow patterns without
copying vendor branding or implying equivalent functionality.

## Reference products

| Product | Publicly documented pattern | Applied in this prototype |
| --- | --- | --- |
| **PowerSchool Special Programs** | A My Students caseload links to student profiles, documents and services. Student information and documents have distinct navigation. | **My caseload** is the landing page, with student search, school, case manager, recorded plan dates and direct IEP/review actions. Student records have Overview, IEP, Documents and Progress & reports sections. |
| **SEIS** | Student records supply IEP information, with error checks during affirmation. | Maintain student context while moving between the current IEP, draft changes and prior versions. Imports enter a separate review queue before becoming student records. |
| **EmbraceIEP** | Caseload-based work, reporting dashboards, required-field checks and timeline monitoring are prominent in public product material. | Show pending draft counts on the caseload, a student overview and course-report summaries. Group field editing by recognizable IEP sections. Recorded plan end dates are explicitly distinguished from verified compliance deadlines. |
| **Frontline IEP & Special Education Management** | Public materials emphasize guided special education workflows and integration with general education systems. | Guide changes through **Compare → Decide**; keep supporting evidence near the draft, with school-system configuration under Tools & setup. |

Sources: [PowerSchool home page](https://sp-programs.powerschool-docs.com/special-programs-user/latest/home-page),
[PowerSchool student profiles and documents](https://sp-programs.powerschool-docs.com/special-programs-user/latest/access-student-profiles-documents-and-events),
[SEIS overview](https://seis.org/index.aspx),
[EmbraceIEP product overview](https://www.embraceeducation.com/iep-software/),
[Frontline product overview](https://www.frontlineeducation.com/iep-direct-is-now-part-of-frontline-special-ed-interventions/).
The implementation choices in the final column are our interpretation of these
patterns, not claims that the products use this exact layout.

## Resulting navigation

```
My caseload
  Search / Needs review filter
  Student overview / Open IEP / Review draft
  Add student / Imports awaiting review

Student workspace
  Overview             Student information, current plan, pending drafts
  IEP                  Original PDF + contextual tools
    View IEP / Edit draft / Suggested modifications / Review drafts
    Suggested modifications: discussion / accommodation options / draft queue
    PDF / Form, page selector, zoom, downloads
  Documents            Current IEP, supporting files, IEP history
  Progress & reports   Course evidence, stakeholder observations, draft updates

Tools & setup
  Templates / Connections / Workspace settings
```

The PDF remains the main working surface, as requested. Familiar record sections
surround it; a professional can find a student and open an IEP without learning
the AI tools first. AI assistance is an optional task within the student's record.
The edit selector uses Student details, Present levels (PLAAFP), Annual goals,
Services & accommodations, Transition and Additional information. A plain-language
description accompanies learning and support needs.

Drafts are visibly separate from the current IEP. Saving an edit stages a review;
approval is the action that updates the record. Red/green differences retain text
labels and insertion/deletion marks. New-student imports are reviewed in their own
context rather than under whichever student happened to be open.

## Scope and validation limits

This pass reorganizes existing capabilities. It does not add meeting scheduling,
parent consent/e-signatures, a state compliance engine, authenticated caseload
assignments, billing or district reporting. “My caseload” currently lists every
student in the local demonstration workspace and says so on screen. The Progress
& reports section contains course evidence and stakeholder reports; it does not
claim to implement a full longitudinal goal-progress measurement system.

Commercial products' functionality above is described by their publishers, not
independently certified here. Familiarity and usability still need validation with
special education teachers, related-service providers and case managers. A useful
next session would ask participants to locate a student, edit an accommodation,
compare a draft and submit a classroom report without coaching.

See [design-pass.md](design-pass.md) for implementation, accessibility considerations
and verification coverage.
