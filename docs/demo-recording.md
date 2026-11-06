# IEP Bridge recording guide

Open http://127.0.0.1:8501. The prepared **Demo start** snapshot contains the following recording students in the populated original Alabama NASET form. Search their full names in **My caseload**, or use the shortcuts in **Tools & setup → Demo & reset**.

| Student | Starting drafts | Best demonstration |
| --- | ---: | --- |
| Ellis Brook, grade 6 | 0 | LMS grades and instructor comments → suggested modifications → combined review → approval |
| Gray Marlow, grade 8 | 0 | A precise PDF edit, with a reliable workflow that does not require the model |
| Logan Sage, grade 8 | 1 | Prepared proposal → specialist escalation → human decision |

These are practice records. Assignment results and comments are mock LMS data; family and student observations remain separately attributed.

## Before each recording

1. Open **Tools & setup → Demo & reset**.
2. Select **Demo start**. Check **Reset all application data to this snapshot**, then choose **Reset for next take**. Wait for the restored confirmation before recording.
3. Reset restores the whole local application's saved data, including plans, PDF mappings, history, reviews, reports, assignment grades, rosters, links and supporting-document context. It clears temporary draft queues, reviewer names/confirmations and PDF navigation in the current session. Other open sessions clear their state on their next interaction.
4. Every reset first saves **Before reset · Demo start**. To recover a previous take, select its timestamped snapshot and restore it the same way. **Before demo preparation** preserves the data from before the two generated drafts were archived.
5. Leave **Demo start** intact. **Save another starting point** creates a separate snapshot if you want a different opening scene.

The first snapshot/reset may take longer because it verifies the archived PDFs. Models, source reference datasets and runtime configuration are not reset. Previously archived PDF files remain on disk but are unlinked when their records are restored. Screenshots, model response exports and other QA files are not application data and are not reset.

## Main sequence: Ellis Brook

1. Open Ellis, then **Progress & reports**. Show the course filter, grades and named instructors. Mathematics / Emily Harper has **72/100** for *Multi-step problem solving* and **80/100** for *Independent practice review*. English language arts / Daniel Reed has **70/100** for *Reading response* and **74/100** for *Written explanation*. Select each assignment row to read its full instructor comment below the table: mathematics had segmented work, a checkpoint and a break; English had extra time without segmentation. These are assignment results, not course averages or proof of a support's effect.
2. Optional family-report entry: click **Add report** to open the dialog and enter the values below. **Parent / caregiver** and **Alex Brook** are preselected; names remain editable. Choose **Save report**. Use **Team reports** to browse family/student observations or their accommodation summary. **Refresh LMS** opens a separate course refresh dialog. Teacher feedback in this sequence remains sourced from graded LMS assignments.

   | Field | Mock input |
   | --- | --- |
   | Course | English language arts |
   | Your name | Alex Brook |
   | Your role | Parent / caregiver |
   | Accommodation used | Short work segments and a return-to-task cue |
   | How often was it used? | Most opportunities |
   | What did you observe? | Mixed |
   | Reporting period starts | 2026-10-19 |
   | Reporting period ends | 2026-10-30 |
   | Examples and observations | During four homework sessions, Ellis restarted after a planned break when the next step was written down. On one session without the written cue, Ellis needed repeated reminders. Please compare these observations with course assignment comments before changing the plan. |

3. Click **Draft from reports**. In **Question or observation**, paste:

   > Using the Mathematics and English language arts assignment comments, clarify the existing Planning and self-monitoring annual goal (goals.0.goal) by naming a written return-to-task cue after the planned break. Keep the plan review date, three work segments, four of five sessions criterion, and current mastery date. Do not change service/accommodation rows or add a new goal. Also change progress_report_weeks from six to four weeks. Do not infer that supports caused the grades.

4. Click **Draft modifications**. Timing and wording can vary. Review the reason and proposed wording for each option. The intended fields are `progress_report_weeks` and `goals.0.goal`. The existing annual-goal box on original PDF page **5** gives this concise clarification more room than the supplementary-aids table and retains the measurable goal criteria. For consistent narration, use **4** and:

   > By the plan review date, Ellis will use a short task plan, a planned break and a written return-to-task cue to complete and check three work segments in four of five sessions.

   If the model offers unrelated options, discard them. For a deterministic fallback, open **Edit draft → Annual goals**, choose the existing goal's wording field (`goals.0.goal`), paste the text above, and **Save for review**. Leave the mastery date unchanged.

5. Click **Send all changes to review**. This creates one review for the related changes; the current plan is still unchanged. Each submitted option shows **Submitted for review** for about three seconds and then clears. You stay on **Suggested modifications**. Individual **Send change to review** buttons behave the same way and leave other options editable. When ready, open **Review drafts** yourself. In **Compare**, select each changed field and click **Show this field on PDF**. Show the red strike-through and green additions in the annual-goal box on page **5**. **View → Form** shows the equivalent record differences. Scroll the PDF or use its page controls to inspect the reporting interval too.
6. Choose **Continue to decision**. Keep **Case manager** and the preselected **Sarah Patel** as **Reviewer name**, and add this optional decision note:

   > Compared both courses' graded assignment comments and the student/family observations. Clarified the return-to-task cue while retaining the goal's measurable criteria, and approved four-week progress monitoring. The team will review implementation across courses.

7. Check **I checked the source, changes, findings and any added pages.** Click **Approve changes**. Show the approval message, then **View IEP** and **Documents → IEP history**. There should be one additional earlier version for this combined approval; earlier template-preparation versions are retained. Downloading **Current IEP** exports the plan; the red/green markup is the review visualization.

## Short reliable sequence: Gray Marlow

1. Open Gray. Confirm there are no saved drafts. Show **Progress & reports**: mathematics has accessible text and an organizer; English comments say accessible text arrived late. Those differences motivate clearer implementation and monitoring.
2. Open **IEP → Edit draft**. Select **Additional information** and choose the progress-report interval field (`progress_report_weeks`). Replace **6** with **4**. In the full Form editor, this field is under **Special factors**.
3. Click **Save for review**, then **Show this field on PDF**. Compare the red **6** and green **4**; switch **View → Form** to show the same change.
4. Continue to decision using the preselected associated **Case manager** name, check the review confirmation, and approve. This route is useful if the model is unavailable or you need a short, predictable take.

Optional accommodation-library clip: in **Suggested modifications**, enter **Make a graphic organizer available at the start of English writing tasks**, expand **Explore accommodation options**, and choose **Find relevant options**. Select **Graphic Organizers for Writing** if offered. Enter **At the start of each independent writing task**, **One organizer and a two-minute planning check**, and **English language arts**, then **Add option to draft**. Edit/review the delivery details before submitting. Explain that this is an alternative draft, and discard it if it duplicates Gray's existing support. Do not approve a redundant service merely for the recording.

## Human escalation: Logan Sage

1. Open Logan's existing **Review: Challenge with access** draft. Compare the changed needs, support wording and reporting interval. Use **Information behind this change** to show the course and family/student evidence.
2. Choose **Continue to decision**. Keep the associated **Case manager** name.
3. Expand **Request another reviewer**. Keep **Specialist** and **Jamie Chen** in **Reviewer to assign**, and paste this reason:

   > Verify that the proposed project-planning support preserves advanced content and addresses the missed checkpoints when collaboration roles were unclear. Compare the Mathematics and English language arts assignment comments before a decision.

4. Click **Assign review**. Show **Specialist review needed**. Return to **Decide** if needed. The case manager cannot approve this assigned specialist review.
5. To demonstrate completion, select **Specialist**; the assigned **Jamie Chen** name is preselected. Inspect the differences and added pages, check the review confirmation and approve. Alternatively choose **Reject this draft** to demonstrate retaining the current plan. Assignment is recorded in the local inbox; it does not send email. Prefilled names do not bypass the explicit review confirmation.

## Technical setup and recovery

The prepared snapshot and student data live in the ignored `data/` directory; they are not uploaded with source code. On another checkout, populate the mock cohort first, then run:

```powershell
.\.venv\Scripts\python.exe tools/demo_data.py --prepare
```

Preparation runs once. It archives only untouched generator-created drafts for Ellis and Gray, retains Logan's draft, and refuses to erase human-reviewed activity. Running it again does not reset a take. Use the UI reset or the explicit CLI restore:

```powershell
.\.venv\Scripts\python.exe tools/demo_data.py --list
.\.venv\Scripts\python.exe tools/demo_data.py --save "Alternate opening"
.\.venv\Scripts\python.exe tools/demo_data.py --restore SNAPSHOT_ID
```

Prefer the in-app reset while the app is running. Stop the app before a CLI restore if supporting-document embeddings were changed, then restart it so the embedded vector database reopens cleanly. Snapshot restoration verifies content before modifying records, backs up the current take, and attempts rollback if installation fails.
