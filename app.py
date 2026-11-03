"""
app.py - the web page. Run with:  streamlit run app.py
Then open http://localhost:8501 in your browser.
"""

import copy
from pathlib import Path

import pandas as pd
import streamlit as st

import core
import export_pdf
import iep_schema as S

st.set_page_config(page_title="IEP Assistant", page_icon="📘", layout="wide")
st.markdown("""<style>
.block-container {padding-top: 2rem;}
div[data-testid="stMetricValue"] {font-size: 1.0rem; white-space: normal;}
</style>""", unsafe_allow_html=True)
st.title("📘 IEP Assistant")
st.caption("Alabama IEP form (ALSDE, Feb. 2019) · runs on this computer with Ollama · "
           "use fake test data only, never real student files")


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


if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))

# ---------------------------------------------------------------------------
# Sidebar: add students and pick one
# ---------------------------------------------------------------------------
with st.sidebar:
    st.text_input("Your name (for the change log)", key="teacher")
    teacher = st.session_state.get("teacher", "")

    if st.button("⚡ Load sample students", width="stretch"):
        for f in sorted((core.APP_DIR / "samples").glob("*.json")):
            core.load_sample(f)
        st.rerun()

    with st.expander("➕ Import an IEP file"):
        st.caption("The AI copies the IEP into the Alabama form. Scanned PDFs are read with OCR. "
                   "Check every section afterwards.")
        up = st.file_uploader("IEP (PDF or TXT)", type=["pdf", "txt"], key="import_file")
        import_name = st.text_input("Student name (needed if it's blacked out in the file)", key="import_name")
        if st.button("Import", disabled=up is None):
            iep = None
            with st.spinner("Reading the file (scanned PDFs take about 2-5 seconds per page)..."):
                text = run_safely(core.extract_text, up.name, up.getvalue())
            if text:
                with st.spinner("Copying it into the Alabama form... (can take a few minutes)"):
                    iep = run_safely(core.import_iep, text, import_name)
            if iep:
                new_sid = run_safely(core.create_student, iep)
                if new_sid:
                    st.session_state["student"] = new_sid
                    flash(f"Imported {iep['student_name']}. Please check every section in 📄 IEP form.")
                    st.rerun()

    with st.expander("📝 Start a blank IEP"):
        new_name = st.text_input("Student name", key="blank_name")
        if st.button("Create", disabled=not new_name.strip()):
            new_sid = core.create_student(core.blank_iep(new_name.strip()))
            st.session_state["student"] = new_sid
            st.rerun()

    st.divider()
    students = core.list_students()
    if not students:
        st.info("Click **Load sample students** to start.")
        st.stop()
    if st.session_state.get("student") not in students:
        st.session_state.pop("student", None)
    sid = st.radio("Students", list(students), format_func=lambda s: students[s], key="student")

    with st.expander("📎 Add a supporting document"):
        st.caption("Evaluations, progress notes, emails. Used when answering questions.")
        doc = st.file_uploader("PDF or TXT", type=["pdf", "txt"], key=f"doc_{sid}")
        if st.button("Add document", disabled=doc is None):
            with st.spinner("Saving..."):
                text = run_safely(core.extract_text, doc.name, doc.getvalue())
                n = run_safely(core.add_supporting_doc, sid, doc.name, text) if text else None
            if n:
                flash(f"Added {doc.name} ({n} chunks).")
                st.rerun()
        for d in core.list_supporting_docs(sid):
            st.write(f"- {d}")

iep = core.get_iep(sid)
name = iep["student_name"]
first = name.split()[0] if name else "Student"
vcount = len(core.list_versions(sid))  # changes after every save, so forms reload
sug_key = f"suggestions_{sid}"
st.session_state.setdefault(sug_key, [])

# ---------------------------------------------------------------------------
# Student profile header
# ---------------------------------------------------------------------------
top_l, top_r = st.columns([4, 1])
top_l.header(f"👤 {name}")
top_r.download_button("⬇️ Download IEP (PDF)", export_pdf.build_pdf(iep),
                      file_name=f"IEP_{sid}.pdf", mime="application/pdf",
                      type="primary", width="stretch")
p = core.get_profile(sid)
c = st.columns(5)
c[0].metric("Grade", p["grade"] or "—")
c[1].metric("Eligibility", p["eligibility"] or "—")
c[2].metric("Annual goals", p["goals"])
c[3].metric("IEP dates", p["dates"] or "—")
c[4].metric("Case manager", p["case_manager"] or "—")
st.caption(f"DOB: {p['dob'] or '—'}  ·  School: {p['school'] or '—'}  ·  "
           f"Transition plan: {'yes' if p['transition'] else 'not required'}")

tab_ask, tab_sum, tab_update, tab_form, tab_acc, tab_hist = st.tabs(
    ["💬 Ask", "📝 Summary", "✏️ Update IEP", "📄 IEP form", "🧩 Accommodations", "🕓 History"])

# --- Ask ----------------------------------------------------------------------
with tab_ask:
    hist_key = f"chat_{sid}"
    st.session_state.setdefault(hist_key, [])
    ai_key = f"ai_qs_{sid}"
    st.markdown("**Suggested questions**")
    clicked = None
    qcols = st.columns(2)
    for i, q in enumerate(st.session_state.get(ai_key) or core.suggested_questions(sid)):
        if qcols[i % 2].button(q, key=f"q_{sid}_{i}", width="stretch"):
            clicked = q
    if st.button("✨ Suggest questions with AI", key=f"aiq_{sid}"):
        with st.spinner("Reading the IEP..."):
            qs = run_safely(core.ai_questions, sid)
        if qs:
            st.session_state[ai_key] = qs
            st.rerun()
    with st.form(f"ask_{sid}", clear_on_submit=True):
        typed = st.text_input(f"Or ask your own question about {first}")
        if st.form_submit_button("Ask") and typed.strip():
            clicked = typed.strip()
    if clicked:
        with st.spinner("Reading the IEP..."):
            result = run_safely(core.answer, sid, clicked)
        if result:
            st.session_state[hist_key].insert(0, (clicked, *result))
    for question, reply, docs in st.session_state[hist_key]:
        with st.chat_message("user"):
            st.write(question)
        with st.chat_message("assistant"):
            st.markdown(reply)
            if docs:
                with st.expander("Supporting documents used"):
                    for i, (d, m) in enumerate(docs, 1):
                        st.markdown(f"**[D{i}] {m['source']}**")
                        st.text(d)

# --- Summary --------------------------------------------------------------------
with tab_sum:
    key = f"summary_{sid}_{vcount}"
    if st.button("Generate summary" if key not in st.session_state else "Regenerate summary"):
        with st.spinner("Summarizing... (can take a minute on a laptop)"):
            st.session_state[key] = run_safely(core.summarize, sid)
    if st.session_state.get(key):
        st.markdown(st.session_state[key])

# --- Update IEP with AI -------------------------------------------------------------
with tab_update:
    st.info("The AI **suggests** changes to specific boxes of the Alabama form. Approving one updates the "
            "IEP; the old version is kept in 🕓 History so you can undo it.")
    note = st.text_area("What have you noticed about this student?",
                        placeholder=f"e.g. {first} met the first reading benchmark and gets overwhelmed by long worksheets.")
    if st.button("Get suggestions", type="primary", disabled=not note.strip()):
        with st.spinner("Drafting suggestions..."):
            new = run_safely(core.suggest_updates, sid, note.strip()) or []
        st.session_state[sug_key] = new + st.session_state[sug_key]
        if not new:
            st.warning("No usable suggestions came back. Try a more specific note.")
    for i, s in enumerate(list(st.session_state[sug_key])):
        with st.container(border=True):
            st.markdown(f"**{s['section']}**  ·  _source: {s.get('source', '?')}_")
            c1, c2 = st.columns(2)
            c1.markdown("**Now on the form**")
            c1.write(s.get("current_text") or "(empty)")
            c2.markdown("**Suggested** (edit before approving if needed)")
            edited = c2.text_area("Suggested", s["suggested_text"], key=f"edit_{sid}_{i}_{len(st.session_state[sug_key])}",
                                  label_visibility="collapsed")
            if s["action"] == "add_service":
                r = s["payload"]
                st.caption(f"Row details: {r['frequency']} · {r['amount']} · {r['begin']} to {r['end']} · {r['location']}")
            if s["action"] == "add_goal":
                g = s["payload"]
                st.caption("Benchmarks: " + " | ".join(b["text"] for b in g["benchmarks"] if b["text"]))
            st.caption(f"Why: {s.get('reason', '')}")
            a, r_, _ = st.columns([1.3, 1, 3])
            if a.button("✅ Approve & update IEP", key=f"ok_{sid}_{i}"):
                msg = run_safely(core.apply_suggestion, sid, {**s, "suggested_text": edited}, teacher)
                if msg:
                    st.session_state[sug_key].pop(i)
                    flash(msg)
                    st.rerun()
            if r_.button("❌ Reject", key=f"no_{sid}_{i}"):
                core.log_decision(sid, s, "rejected", teacher)
                st.session_state[sug_key].pop(i)
                st.rerun()


# --- IEP form: edit any box directly ------------------------------------------------------
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


def save_form(new_iep: dict, section: str) -> None:
    if run_safely(core.save_iep, sid, new_iep, note=f"Edited by hand: {section}"):
        core.log_decision(sid, {"section": f"Manual edit – {section}", "suggested_text": ""}, "edited", teacher)
        flash(f"Saved: {section}")
        st.rerun()


with tab_form:
    st.caption("Each section matches a page of the Alabama IEP form. Edit, then click Save in that section.")
    k = f"{sid}_{vcount}"

    with st.expander("Page 1 – Student information and Student Profile", expanded=True):
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
            if st.form_submit_button("💾 Save page 1"):
                save_form(n, "Student information and profile")

    with st.expander("Page 2 – Special factors, transportation, activities, progress reports"):
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
            if st.form_submit_button("💾 Save page 2"):
                save_form(n, "Special factors and transportation")

    with st.expander("Pages 3-4 – Transition (age 14+ or 9th grade)"):
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
            if st.form_submit_button("💾 Save transition"):
                save_form(n, "Transition")

    with st.expander(f"Page 5 – Annual goals ({len(iep['goals'])})"):
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
            if st.form_submit_button("💾 Save goals"):
                n["goals"] = keep + ([S.empty_goal() | {"mastery_date": iep["iep_to"]}] if add else [])
                save_form(n, "Annual goals")

    with st.expander("Page 6 – Special education and related services"):
        with st.form(f"f6_{k}"):
            n = copy.deepcopy(iep)
            cols = ["service", "frequency", "amount", "begin", "end", "location"]
            for ck, label in S.SERVICE_CATEGORIES:
                st.markdown(f"**{label}**")
                if ck != "special_education":
                    n["services"][ck]["needed"] = st.checkbox("Needed", iep["services"][ck]["needed"], key=f"sn_{ck}_{k}")
                n["services"][ck]["rows"] = rows_editor(iep["services"][ck]["rows"], cols, f"sr_{ck}_{k}")
            if st.form_submit_button("💾 Save services"):
                save_form(n, "Services")

    with st.expander("Page 7 – Transfer of rights, ESY, LRE, copies, team"):
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
            if st.form_submit_button("💾 Save page 7"):
                save_form(n, "Rights, ESY, LRE and team")

# --- Accommodations from the dataset -------------------------------------------------------
with tab_acc:
    st.caption("From the public K-12 special education accommodations dataset (Hugging Face, CC0). "
               "A reference list, not advice. The IEP team decides.")
    try:
        with st.spinner("Loading the accommodations dataset..."):
            recs = core.recommend_accommodations(sid, k=10)
    except Exception as e:  # noqa: BLE001
        recs = None
        st.error(f"Couldn't load the dataset: {e}\n\nRun `python prepare_dataset.py` once while online.")
    if recs is not None and not recs:
        st.info("No matching accommodations. Is the Eligibility filled in on page 1?")
    for i, a in enumerate(recs or []):
        with st.container(border=True):
            badge = "✅ already in IEP" if a["already_in_iep"] else ""
            st.markdown(f"**{a.get('name', '')}**  ·  evidence: *{a.get('evidence_level', '?')}*  {badge}")
            st.write(a.get("description", ""))
            st.caption(f"Matched on: {', '.join(a['matched_on'])}")
            if not a["already_in_iep"] and st.button("Propose for IEP", key=f"acc_{sid}_{i}"):
                sug = core.accommodation_to_suggestion(sid, a)
                if sug:
                    st.session_state[sug_key].insert(0, sug)
                    flash(f"Added '{a.get('name')}' as a suggestion. Review it in ✏️ Update IEP.")
                    st.rerun()

# --- History: versions + change log ---------------------------------------------------------
with tab_hist:
    left, right = st.columns(2)
    with left:
        st.markdown(f"**Saved versions** ({vcount} older)")
        for j, v in enumerate(core.list_versions(sid)):
            with st.expander(f"{v['when']} — before: {v['note'] or 'change'}"):
                st.download_button("⬇️ PDF of this version", export_pdf.build_pdf(v["iep"]),
                                   file_name=f"IEP_{sid}_v{j}.pdf", key=f"vpdf_{sid}_{j}")
                if st.button("↩️ Restore this version", key=f"restore_{sid}_{j}"):
                    core.save_iep(sid, v["iep"], note=f"Restored version from {v['when']}")
                    core.log_decision(sid, {"section": "Restore", "suggested_text": f"Restored version from {v['when']}"},
                                      "edited", teacher)
                    flash("Version restored.")
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

with st.sidebar:
    st.divider()
    if st.button(f"🗑️ Delete {first}", width="stretch"):
        core.delete_student(sid)
        for key_ in [x for x in st.session_state if str(x).endswith(sid)]:
            st.session_state.pop(key_)
        st.session_state.pop("student", None)
        st.rerun()