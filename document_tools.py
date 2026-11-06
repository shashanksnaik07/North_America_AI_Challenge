"""Document side-panel tools extracted from the original app."""
import copy
import json
import time
from functools import partial
from uuid import uuid4
import pandas as pd
import streamlit as st
import core
import export_pdf
import iep_schema as S
import workspace_ui as U
import reviews
import drafting

SUBMITTED_NOTICE_SECONDS=3.0


@st.fragment(run_every=.5)
def submitted_option(sid, draft_id):
    """Expire just the receipt, keeping other editable options and the current tool."""
    queue='suggestions_'+sid
    item=next((item for item in st.session_state.get(queue,[]) if item.get('_draft_id')==draft_id),None)
    if item is None: return
    if time.monotonic()-item['_submitted_at']>=SUBMITTED_NOTICE_SECONDS:
        st.session_state[queue]=[item for item in st.session_state[queue] if item.get('_draft_id')!=draft_id]
        return
    with st.container(border=True):
        st.success('Added to draft',icon=':material/check_circle:')
        st.caption(item['section'])


def mark_submitted(items):
    for item in items: item['_submitted_at']=time.monotonic()
    st.rerun()


def run_safely(fn, *args, **kwargs):
    """Show a clear message instead of crashing."""
    try:
        return fn(*args, **kwargs)
    except ValueError as e:  # problems with the file or the data - not Ollama
        st.error(str(e))
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        hint = ""
        if any(w in msg.lower() for w in ("connect", "refused", "not found", "pull", "ollama")):
            hint = (f"\n\nCheck that Ollama is running (`ollama serve`) and that you pulled the models: "
                    f"`ollama pull {core.CHAT_MODEL}` and `ollama pull {core.EMBED_MODEL}`")
        st.error(f"Something went wrong: {msg}{hint}")
    return None


def flash(msg: str) -> None:
    st.session_state["flash"] = msg


def tri(label: str, value, key: str):
    opts = ["YES", "NO", "—"]
    idx = 0 if value is True else 1 if value is False else 2
    pick = st.radio(label, opts, index=idx, key=key, horizontal=True)
    return True if pick == "YES" else False if pick == "NO" else None


def rows_editor(rows: list[dict], columns: list[str], key: str) -> list[dict]:
    df = pd.DataFrame(rows or [], columns=columns)
    out = st.data_editor(df, num_rows="dynamic", width="stretch", key=key)
    clean = []
    for rec in out.fillna("").to_dict("records"):
        rec = {k: str(v) for k, v in rec.items()}
        if any(v.strip() for v in rec.values()):
            clean.append(rec)
    return clean


def save_form(new_iep: dict, section: str, sid: str, teacher: str, draft_revision=0) -> None:
    if run_safely(reviews.stage_change, sid, new_iep, f"Form edit: {section}", teacher,expected_draft_revision=draft_revision):
        flash(f"Saved to the working draft: {section}")
        st.rerun()








def modifications(sid, teacher=''):
    """Evidence-first drafting, optional discussion, and one human-review queue."""
    import integrations as I
    queue='suggestions_'+sid
    st.session_state.setdefault(queue,[])
    st.caption('Review suggested changes based on the current IEP, course feedback and team reports.')
    pending=reviews.working_draft(sid)
    if pending and (pending['kind']=='import' or pending.get('merge_conflicts')):
        st.info('Open Review draft to complete the pending import or resolve conflicting changes before adding suggestions.');return
    if pending:
        st.info('A working draft is open. Selected suggestions join that draft; review and approve all its changes together.')
    evidence=I.evidence(sid)
    files=core.list_supporting_docs(sid)
    st.caption(f'{len(evidence)} reports & assignment results · {len(files)} supporting files')
    requested=st.session_state.pop('draft_from_reports_'+sid,False)
    area=st.selectbox('Review focus',list(core.REVIEW_AREAS),key='modification_review_area_'+sid,persist_state='session',
                      help='Review the whole IEP or narrow suggestions to one section. All available student evidence is considered.')
    if not evidence and not files: st.info('Add a team report, refresh LMS feedback, or attach a supporting document before drafting.')
    draft=st.button('Draft modifications',type='primary',disabled=not (evidence or files),width='stretch',icon=':material/auto_fix_high:')
    if st.button('View or add reports',width='stretch',icon=':material/comment:'):
        st.session_state['pending_student_section']='Progress & reports';st.rerun()
    with st.expander('Evidence used'):
        if evidence: D.evidence_cards(evidence)
        for name in files: st.caption(name)
        if not evidence and not files: st.caption('No reports or supporting documents yet.')
    if (draft or requested) and (evidence or files):
        context=drafting.basis(sid)
        with st.spinner('Drafting changes from the plan and evidence...'):
            new=run_safely(core.suggest_updates,sid,review_area=area)
        if new:
            # Capture before the model call; never stamp a late response as fresh.
            new=[item if '_generation' in item else {**item,**context} for item in new]
            st.session_state[queue]=drafting.merge(st.session_state[queue],new)
        elif new==[]: st.info('No supported changes were identified in this section. The current IEP is unchanged.')
    with st.expander('Discuss the evidence (optional)'):
        question=st.text_area('Question',key='modification_question_'+sid,persist_state='session',height=85,
                              placeholder='For example: how does participation differ between courses?')
        if st.button('Discuss options',disabled=not question.strip(),width='stretch',icon=':material/forum:'):
            with st.spinner('Reading the plan and supporting context...'):
                result=run_safely(core.answer,sid,question.strip())
            if result: st.session_state.setdefault('modification_discussion_'+sid,[]).insert(0,(question,*result))
        st.caption('Questions help interpret the evidence. Record new observations in Progress & reports.')
        for question,answer,docs in st.session_state.get('modification_discussion_'+sid,[]):
            st.markdown('**'+question+'**');st.write(answer)
            if docs:
                with st.expander('Sources: '+question[:60]):
                    for text,metadata in docs: st.caption(metadata.get('source','Document'));st.text(text)
    with st.expander('Explore accommodation options'):
        st.caption('Reference options for this student. Catalog evidence ratings are not independently verified.')
        if st.button('Find relevant options',width='stretch',icon=':material/search:'):
            st.session_state['modification_options_'+sid]=run_safely(core.recommend_accommodations,sid,'' if area=='Whole IEP' else area,k=15) or []
        options=st.session_state.get('modification_options_'+sid,[])
        if options:
            chosen=st.selectbox('Accommodation option',options,format_func=lambda a:a['name'],key='modification_catalog_'+sid)
            st.write(chosen.get('description',''))
            st.caption('Specify how this option would be used before adding it to the draft.')
            frequency=st.text_input('When / how often',key='modification_frequency_'+sid,persist_state='session')
            amount=st.text_input('Amount or duration',key='modification_amount_'+sid,persist_state='session')
            location=st.text_input('Course or setting',key='modification_location_'+sid,persist_state='session')
            if st.button('Add option to draft',disabled=not all(v.strip() for v in [frequency,amount,location]),width='stretch',icon=':material/add_circle:'):
                suggestion=core.accommodation_to_suggestion(sid,chosen)
                suggestion['payload'].update(frequency=frequency.strip(),amount=amount.strip(),location=location.strip())
                suggestion['reason']='Reference option selected for team review. '+chosen.get('description','')
                suggestion['evidence']=I.evidence(sid)+[{'source':'Accommodation catalog','text':chosen.get('description',''),'catalog_id':chosen.get('id'),'evidence_verified':False}]
                st.session_state[queue]=drafting.merge(st.session_state[queue],[suggestion])
                st.success('Option added below. Edit its wording and send it for review.')
    if st.session_state[queue]: st.markdown('**Draft changes**')
    for i,suggestion in enumerate(list(st.session_state[queue])):
        draft_id=suggestion.setdefault('_draft_id',uuid4().hex)
        if '_submitted_at' in suggestion:
            submitted_option(sid,draft_id)
            continue
        with st.container(border=True):
            st.markdown('**'+suggestion['section']+'**')
            st.caption('Current wording');st.write(suggestion.get('current_text') or 'New plan item')
            wording=st.text_area('Proposed wording',suggestion['suggested_text'],key=f'modification_candidate_{sid}_{draft_id}',persist_state='session')
            suggestion['suggested_text']=wording
            st.caption('Reason: '+suggestion.get('reason',''))
            if suggestion['action']=='add_service':
                row=suggestion['payload']
                for field,label in [('frequency','Service: when / how often'),('amount','Service: amount or duration'),('location','Service: course or setting')]:
                    row[field]=st.text_input(label,row.get(field,''),key=f'modification_{field}_{sid}_{draft_id}',persist_state='session')
            if suggestion['action']=='add_goal':
                suggestion['payload']['area']=st.text_input('Goal area',suggestion['payload'].get('area',''),key=f'modification_area_{sid}_{draft_id}',persist_state='session')
            if st.button('Add to draft',key=f'modification_submit_{sid}_{draft_id}',type='primary',disabled=not wording.strip(),width='stretch',icon=':material/add:'):
                result=run_safely(core.apply_suggestion,sid,{**suggestion,'suggested_text':wording},teacher)
                if result:
                    mark_submitted([suggestion])
            if st.button('Discard option',key=f'modification_discard_{sid}_{draft_id}',icon=':material/close:'):
                st.session_state[queue].pop(i);st.rerun()
    active=[item for item in st.session_state[queue] if '_submitted_at' not in item]
    if len(active)>1:
        st.caption('Add selected suggestions to the same working draft as your direct edits.')
        if st.button('Add all to draft',icon=':material/playlist_add_check:',type='primary',width='stretch'):
            result=run_safely(drafting.submit,sid,active,teacher)
            if result:
                mark_submitted(active)


def form(student_id, teacher=""):
    sid = student_id
    working=reviews.working_draft(sid)
    if working and working['kind']=='import':
        st.info('Review the pending import before editing this IEP.');return
    if working and working.get('merge_conflicts'):
        st.info('Open Review draft to resolve the conflicting changes before editing.');return
    iep = copy.deepcopy(working['candidate'] if working else core.get_iep(sid))
    name = iep['student_name']
    first = name.split()[0] if name else 'Student'
    vcount = len(core.list_versions(sid))
    sug_key = f'suggestions_{sid}'
    st.session_state.setdefault(sug_key, [])
    revision=working['revision'] if working else 0
    save_form = partial(globals()['save_form'], sid=sid, teacher=teacher,draft_revision=revision)
    section=st.selectbox('Form section',['Student information & present levels','Special factors','Transition','Annual goals','Services & accommodations','Placement & team','Additional fields'],key='form_section_'+sid,persist_state='session')
    if section=='Additional fields' and iep.get('extensions'):
        with st.expander('Template-specific information'):
            with st.form(f'template_extensions_{sid}_{revision}'):
                proposed=copy.deepcopy(iep)
                for field,value in iep['extensions'].items():
                    proposed['extensions'][field]=U.typed_value(field.replace('_',' ').title(),value,f'ext_form_{sid}_{revision}_{field}')
                if st.form_submit_button('Save template fields to draft',icon=':material/crop_free:'): save_form(proposed,'Template-specific information')
    elif section=='Additional fields': st.info('This plan has no template-specific fields yet.')
    st.caption("Editing the working draft. Save each section here; Review draft approves the combined changes as the next IEP version.")
    k = f"{sid}_{vcount}_{revision}"

    if section=='Student information & present levels':
        with st.form(f"f1_{k}"):
            n = copy.deepcopy(iep)
            a, b, c3 = st.columns(3)
            n["student_name"] = a.text_input("Student's name", iep["student_name"])
            n["dob"] = b.text_input("DOB", iep["dob"])
            n["grade"] = c3.text_input("Grade", iep["grade"])
            a, b, c3 = st.columns(3)
            n["school_year"] = a.text_input("School year", iep["school_year"])
            n["iep_from"] = b.text_input("IEP from", iep["iep_from"])
            n["iep_to"] = c3.text_input("IEP to", iep["iep_to"])
            a, b, c3 = st.columns(3)
            n["meta"]["eligibility"] = a.text_input("Eligibility (not printed on the form)", iep["meta"]["eligibility"])
            n["meta"]["school"] = b.text_input("School (not printed)", iep["meta"]["school"])
            n["meta"]["case_manager"] = c3.text_input("Case manager (not printed)", iep["meta"]["case_manager"])
            for fk, label in S.PROFILE_FIELDS:
                n["profile"][fk] = st.text_area(label, iep["profile"][fk])
            if st.form_submit_button("Save student details to draft",icon=':material/person:'):
                save_form(n, "Student information and profile")

    if section=='Special factors':
        with st.form(f"f2_{k}"):
            n = copy.deepcopy(iep)
            for fk, q in S.SPECIAL_FACTORS:
                n["special_factors"][fk] = tri(q, iep["special_factors"][fk], f"sf_{fk}_{k}")
            t = iep["transportation"]
            n["transportation"]["mode"] = st.selectbox("Mode of transportation", S.TRANSPORT_MODES,
                                                       index=S.TRANSPORT_MODES.index(t["mode"]) if t["mode"] in S.TRANSPORT_MODES else 0)
            n["transportation"]["mode_other"] = st.text_input("If Other, describe", t["mode_other"])
            n["transportation"]["related_service"] = st.checkbox("Transportation is a related service", t["related_service"])
            n["transportation"]["needs"] = st.multiselect("Transportation needs", S.TRANSPORT_NEEDS,
                                                          [x for x in t["needs"] if x in S.TRANSPORT_NEEDS])
            n["transportation"]["needs_details"] = st.text_input("Transportation details", t["needs_details"])
            na = iep["nonacademic"]
            n["nonacademic"]["participation"] = st.radio(
                "Participates in nonacademic/extracurricular activities with nondisabled peers?",
                S.NONACADEMIC_OPTIONS, horizontal=True,
                index=S.NONACADEMIC_OPTIONS.index(na["participation"]) if na["participation"] in S.NONACADEMIC_OPTIONS else 0)
            n["nonacademic"]["description"] = st.text_input("Describe supports / explanation", na["description"])
            n["progress_report_weeks"] = st.text_input("Progress reports every ___ weeks", iep["progress_report_weeks"])
            if st.form_submit_button("Save special factors to draft",icon=':material/rate_review:'):
                save_form(n, "Special factors and transportation")

    if section=='Transition':
        with st.form(f"f3_{k}"):
            n = copy.deepcopy(iep)
            tr, tg = iep["transition"], iep["transition_goals"]
            n["transition"]["applicable"] = st.checkbox("Transition applies to this student", tr["applicable"])
            a, b = st.columns(2)
            n["transition"]["student_invited_date"] = a.text_input("Student invited on", tr["student_invited_date"])
            n["transition"]["student_invited_via"] = b.text_input("Invited via", tr["student_invited_via"])
            n["transition"]["assessments"] = st.multiselect("Transition assessments used", S.TRANSITION_ASSESSMENTS,
                                                            [x for x in tr["assessments"] if x in S.TRANSITION_ASSESSMENTS])
            for ak, label in S.POSTSECONDARY_AREAS:
                n["transition"]["postsecondary"][ak]["long_term_goal"] = st.text_area(
                    f"Long-term {label}", tr["postsecondary"][ak]["long_term_goal"], key=f"lt_{ak}_{k}")
            a, b, c3 = st.columns(3)
            n["transition"]["exit_month"] = a.text_input("Exit month", tr["exit_month"])
            n["transition"]["exit_year"] = b.text_input("Exit year", tr["exit_year"])
            n["transition"]["pathway"] = c3.selectbox("Diploma pathway", [""] + S.PATHWAYS,
                                                      index=([""] + S.PATHWAYS).index(tr["pathway"]) if tr["pathway"] in S.PATHWAYS else 0)
            st.markdown("**Annual transition goals**")
            n["transition_goals"]["present_level"] = st.text_area("Present level (transition)", tg["present_level"])
            for ak, label in S.POSTSECONDARY_AREAS:
                g = tg[ak]
                st.markdown(f"_{label}_")
                n["transition_goals"][ak]["goal"] = st.text_area("Goal", g["goal"], key=f"tg_{ak}_{k}")
                a, b = st.columns(2)
                n["transition_goals"][ak]["mastery_date"] = a.text_input("Date of completion/mastery", g["mastery_date"], key=f"tm_{ak}_{k}")
                n["transition_goals"][ak]["services"] = b.text_input("Transition service(s)", g["services"], key=f"ts_{ak}_{k}")
                acts = st.text_area("Transition activities (one per line)", "\n".join(g["activities"]), key=f"ta_{ak}_{k}")
                n["transition_goals"][ak]["activities"] = [x.strip() for x in acts.splitlines() if x.strip()]
                n["transition_goals"][ak]["people"] = st.text_input("Person(s)/agency involved", g["people"], key=f"tp_{ak}_{k}")
            if st.form_submit_button("Save transition changes to draft",icon=':material/rate_review:'):
                save_form(n, "Transition")

    if section=='Annual goals':
        with st.form(f"f5_{k}"):
            n = copy.deepcopy(iep)
            keep = []
            for gi, g in enumerate(iep["goals"]):
                st.markdown(f"**Annual Goal {gi + 1}**")
                ng = n["goals"][gi]
                a, b = st.columns([3, 1])
                ng["area"] = a.text_input("Area", g["area"], key=f"ga_{gi}_{k}")
                ng["mastery_date"] = b.text_input("Date of mastery", g["mastery_date"], key=f"gm_{gi}_{k}")
                ng["present_level"] = st.text_area("Present level", g["present_level"], key=f"gp_{gi}_{k}")
                ng["goal"] = st.text_area("Measurable annual goal", g["goal"], key=f"gg_{gi}_{k}")
                ng["evaluation"] = st.multiselect("Type(s) of evaluation", S.EVALUATION_TYPES,
                                                  [e for e in g["evaluation"] if e in S.EVALUATION_TYPES], key=f"ge_{gi}_{k}")
                bm = st.text_area("Benchmarks (one per line: text | date of mastery)",
                                  "\n".join(f"{x['text']} | {x['date']}" for x in g["benchmarks"] if x["text"]),
                                  key=f"gb_{gi}_{k}")
                ng["benchmarks"] = [{"text": ln.split("|")[0].strip(), "date": ln.split("|")[1].strip() if "|" in ln else ""}
                                    for ln in bm.splitlines() if ln.strip()]
                if not st.checkbox("Delete this goal", key=f"gd_{gi}_{k}"):
                    keep.append(ng)
                st.divider()
            add = st.checkbox("Add a new empty goal")
            if st.form_submit_button("Save goal changes to draft",icon=':material/rate_review:'):
                n["goals"] = keep + ([S.empty_goal() | {"mastery_date": iep["iep_to"]}] if add else [])
                save_form(n, "Annual goals")

    if section=='Services & accommodations':
        with st.form(f"f6_{k}"):
            n = copy.deepcopy(iep)
            cols = ["service", "frequency", "amount", "begin", "end", "location"]
            for ck, label in S.SERVICE_CATEGORIES:
                st.markdown(f"**{label}**")
                if ck != "special_education":
                    n["services"][ck]["needed"] = st.checkbox("Needed", iep["services"][ck]["needed"], key=f"sn_{ck}_{k}")
                n["services"][ck]["rows"] = rows_editor(iep["services"][ck]["rows"], cols, f"sr_{ck}_{k}")
            if st.form_submit_button("Save service changes to draft",icon=':material/rate_review:'):
                save_form(n, "Services")

    if section=='Placement & team':
        with st.form(f"f7_{k}"):
            n = copy.deepcopy(iep)
            lre = iep["lre"]
            n["transfer_of_rights_date"] = st.text_input("Date informed of transfer of rights", iep["transfer_of_rights_date"])
            n["esy_considered"] = tri("IEP Team considered extended school year services", iep["esy_considered"], f"esy_{k}")
            n["lre"]["attends_home_school"] = tri("Attends the school he/she would attend if nondisabled?",
                                                  lre["attends_home_school"], f"lh_{k}")
            n["lre"]["home_school_explain"] = st.text_input("If no, explain", lre["home_school_explain"], key=f"lhe_{k}")
            n["lre"]["all_with_nondisabled"] = tri("Receives all special education services with nondisabled peers?",
                                                   lre["all_with_nondisabled"], f"ln_{k}")
            n["lre"]["nondisabled_explain"] = st.text_area("If no, explain", lre["nondisabled_explain"], key=f"lne_{k}")
            n["lre"]["age_group"] = st.radio("Age group", ["6-21", "3-5"], horizontal=True,
                                             index=0 if lre["age_group"] != "3-5" else 1)
            n["lre"]["setting"] = st.text_input("Least restrictive environment", lre["setting"])
            n["copies"]["iep_given"] = tri("Copy of IEP given at the meeting?", iep["copies"]["iep_given"], f"ci_{k}")
            n["copies"]["rights_given"] = tri("Copy of Special Education Rights given?", iep["copies"]["rights_given"], f"cr_{k}")
            n["copies"]["amended_sent_date"] = st.text_input("Date amended IEP sent to parent", iep["copies"]["amended_sent_date"])
            st.markdown("**People who attended**")
            n["participants"] = rows_editor(iep["participants"], ["position", "name", "date"], f"pp_{k}")
            st.markdown("**Information from people not in attendance**")
            n["not_in_attendance"] = rows_editor(iep["not_in_attendance"], ["position", "name", "date"], f"pn_{k}")
            if st.form_submit_button("Save placement & team changes to draft",icon=':material/rate_review:'):
                save_form(n, "Rights, ESY, LRE and team")




def history(student_id, teacher=""):
    sid = student_id
    iep = core.get_iep(sid)
    name = iep['student_name']
    first = name.split()[0] if name else 'Student'
    vcount = len(core.list_versions(sid))
    sug_key = f'suggestions_{sid}'
    st.session_state.setdefault(sug_key, [])
    save_form = partial(globals()['save_form'], sid=sid, teacher=teacher)
    left, right = st.container(), st.container()
    with left:
        st.markdown(f"**Saved versions** ({vcount} older)")
        for j, v in enumerate(core.list_versions(sid)):
            with st.expander(f"{v['when']} — before: {v['note'] or 'change'}"):
                version_pdf = U.P.render_document(v['document'], v['iep'])[0] if v.get('document') else export_pdf.build_pdf(v['iep'])
                st.download_button("PDF of this version", version_pdf,
                                   file_name=f"IEP_{sid}_v{j}.pdf", key=f"vpdf_{sid}_{j}",icon=':material/download:')
                if st.button("Restore this version", key=f"restore_{sid}_{j}",icon=':material/restore:'):
                    if run_safely(reviews.stage_change, sid, v['iep'], f"Restore version from {v['when']}", teacher, document=v.get('document')):
                        st.session_state['pending_student_section']='IEP'
                        st.session_state['pending_tool_'+sid]='Review'
                        flash("Restoration submitted for review.")
                        st.rerun()
    with right:
        st.markdown("**Change log**")
        icons = {"approved": "✅", "rejected": "❌", "edited": "✏️"}
        entries = core.get_log(sid)
        if not entries:
            st.info("No changes yet.")
        for e in entries:
            st.markdown(f"{icons.get(e['decision'], '•')} **{e['decision'].title()}** by {e['teacher']} · "
                        f"{e['time']} — *{e.get('section', '')}*")
            if e.get("suggested_text"):
                st.caption(e["suggested_text"])
