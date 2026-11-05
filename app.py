"""
app.py - the web page. Run with:  streamlit run app.py
Then open http://localhost:8501 in your browser.
"""

import copy
import urllib.parse
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

    # --- Class Dashboard ---
    dash_rows = core.get_dashboard()
    if len(dash_rows) > 1:
        with st.expander("📊 Class dashboard", expanded=False):
            for row in dash_rows:
                active = row["sid"] == st.session_state.get("student")
                border_style = "border-left: 3px solid #3b82d4; padding-left: 6px;" if active else ""
                st.markdown(
                    f"<div style='{border_style}'>"
                    f"<b>{row['name']}</b> · Gr {row['grade'] or '—'} · "
                    f"{row['urgency']} until IEP expires<br/>"
                    f"<small style='color:#57606a'>Next benchmark: {row['next_benchmark']}"
                    + (f" — {row['next_bm_text']}" if row['next_bm_text'] else "")
                    + f"</small></div>",
                    unsafe_allow_html=True,
                )
                if st.button("Open", key=f"dash_{row['sid']}", use_container_width=True):
                    st.session_state["student"] = row["sid"]
                    st.rerun()

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

# Load pre-cached demo responses (generated by precache_demo.py) into session state
# so AI tabs show results instantly without waiting for Ollama.
_cache_dir = Path(core.DATA_DIR / "demo_cache")
_sum_key = f"summary_{sid}_{vcount}"
_pwn_key = f"pwn_{sid}_{vcount}"
_act_key = f"activities_{sid}_{vcount}"
_ai_q_key = f"ai_qs_{sid}"
for _ck, _fname in [(_sum_key, f"{sid}_summary.json"),
                    (_pwn_key, f"{sid}_pwn.json"),
                    (_act_key, f"{sid}_activities.json"),
                    (_ai_q_key, f"{sid}_ai_questions.json")]:
    if _ck not in st.session_state:
        _cf = _cache_dir / _fname
        if _cf.exists():
            import json as _json
            st.session_state[_ck] = _json.loads(_cf.read_text()).get("value")

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

tab_ask, tab_sum, tab_update, tab_form, tab_acc, tab_pwn, tab_contact, tab_act, tab_hist = st.tabs(
    ["💬 Ask", "📝 Summary", "✏️ Update IEP", "📄 IEP form",
     "🧩 Accommodations", "📋 PWN", "📧 Contact", "🎯 Activities", "🕓 History"])

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
    if st.session_state.get(key):
        st.caption("✅ Loaded from cache — click Regenerate to refresh with AI.")
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

    with st.expander("➕ Supplemental – Medicaid (MCAID), ADL, Safety monitoring"):
        st.caption("These fields are NOT part of the Alabama ALSDE form. They are stored separately "
                   "and included as a supplemental page when you download the PDF.")
        with st.form(f"fext_{k}"):
            n = copy.deepcopy(iep)
            ext = n.get("extended", {})
            mc = ext.get("mcaid", {})
            adl_d = ext.get("adl", {})
            safety_d = ext.get("safety", {})

            st.markdown("**Medicaid (MCAID)**")
            mc["consent_on_file"] = tri("Parental consent for Medicaid billing on file?",
                                        mc.get("consent_on_file"), f"mc_c_{k}")
            mc["billing_number"] = st.text_input("Medicaid billing number", mc.get("billing_number", ""))
            mc["services_billed"] = st.text_input(
                "Services billed to Medicaid (e.g. Speech, OT, PT)",
                mc.get("services_billed", ""))
            mc["notes"] = st.text_area("Medicaid notes", mc.get("notes", ""), key=f"mc_n_{k}")

            st.divider()
            st.markdown("**Activities of Daily Living (ADL)**")
            adl_d["applicable"] = st.checkbox("ADL support is applicable to this student",
                                              adl_d.get("applicable", False), key=f"adl_app_{k}")
            if adl_d["applicable"]:
                adl_skills = adl_d.get("skills", {})
                for skill in S.ADL_SKILLS:
                    sv = adl_skills.get(skill, {})
                    if not isinstance(sv, dict):
                        sv = {}
                    ca, cb = st.columns([1, 2])
                    sv["level"] = ca.text_input(f"{skill} – current level",
                                                sv.get("level", ""), key=f"adl_l_{skill}_{k}")
                    sv["goal"] = cb.text_input(f"Goal / target",
                                               sv.get("goal", ""), key=f"adl_g_{skill}_{k}")
                    adl_skills[skill] = sv
                adl_d["skills"] = adl_skills
            adl_d["notes"] = st.text_area("ADL notes", adl_d.get("notes", ""), key=f"adl_n_{k}")

            st.divider()
            st.markdown("**Safety Monitoring**")
            safety_d["applicable"] = st.checkbox("Safety monitoring plan is applicable",
                                                  safety_d.get("applicable", False), key=f"sf_app_{k}")
            if safety_d["applicable"]:
                safety_d["risk_level"] = st.selectbox(
                    "Overall risk level", [""] + S.SAFETY_RISK_LEVELS,
                    index=([""] + S.SAFETY_RISK_LEVELS).index(safety_d.get("risk_level", ""))
                    if safety_d.get("risk_level") in S.SAFETY_RISK_LEVELS else 0,
                    key=f"sf_rl_{k}")
                safety_d["elopement_risk"] = st.checkbox(
                    "Elopement / wandering risk", safety_d.get("elopement_risk", False),
                    key=f"sf_el_{k}")
                safety_d["medical_alerts"] = st.text_area(
                    "Medical alerts (allergies, seizures, medications, etc.)",
                    safety_d.get("medical_alerts", ""), key=f"sf_ma_{k}")
                safety_d["emergency_protocol"] = st.text_area(
                    "Emergency protocol",
                    safety_d.get("emergency_protocol", ""), key=f"sf_ep_{k}")
                safety_d["monitoring_notes"] = st.text_area(
                    "Monitoring notes",
                    safety_d.get("monitoring_notes", ""), key=f"sf_mn_{k}")

            ext["mcaid"] = mc
            ext["adl"] = adl_d
            ext["safety"] = safety_d
            n["extended"] = ext
            if st.form_submit_button("💾 Save supplemental"):
                save_form(n, "Supplemental – Medicaid / ADL / Safety")

# --- Accommodations from the dataset -------------------------------------------------------
with tab_acc:
    st.caption("From the public K-12 special education accommodations dataset (Hugging Face, CC0). "
               "A reference list, not advice. The IEP team decides.")
    st.info("💡 **OT, Speech-Language, Counseling, and other related services** are recorded in the "
            "**📄 IEP form → Page 6** under *Related Services*. Use ✏️ Update IEP to let the AI suggest "
            "adding them, or add them directly in the form.")
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

# --- Prior Written Notice -------------------------------------------------------------------
with tab_pwn:
    st.info(
        "A **Prior Written Notice (PWN)** is required by IDEA each time the IEP team proposes or "
        "refuses to change a student's identification, evaluation, placement, or services. "
        "This AI draft must be reviewed by the team before sending to parents."
    )
    pwn_key = f"pwn_{sid}_{vcount}"
    if st.button("📋 Generate PWN draft" if pwn_key not in st.session_state else "🔄 Regenerate PWN draft",
                 type="primary"):
        with st.spinner("Drafting the Prior Written Notice… (may take a minute)"):
            st.session_state[pwn_key] = run_safely(core.generate_pwn, sid)
    if st.session_state.get(pwn_key):
        pwn_text = st.session_state[pwn_key]
        st.markdown(pwn_text)
        st.divider()
        col_copy, col_pdf, col_txt = st.columns([2, 1, 1])
        col_copy.text_area("Copy-paste version", pwn_text, height=200, key=f"pwn_copy_{sid}")
        col_pdf.download_button(
            "⬇️ Download PWN (PDF)",
            data=export_pdf.build_pwn_pdf(name, pwn_text),
            file_name=f"PWN_{sid}.pdf",
            mime="application/pdf",
        )
        col_txt.download_button(
            "⬇️ Download PWN (.txt)",
            data=pwn_text,
            file_name=f"PWN_{sid}.txt",
            mime="text/plain",
        )


# --- Parent Contact / Meeting Invitation ----------------------------------------------------
with tab_contact:
    st.markdown("### 📧 Meeting Invitation")
    st.caption("Fill in the details below. Copy the invitation text or open your email client with it pre-filled.")

    # iep and p are already loaded above (line ~109 and ~124)
    default_email = ""
    default_date = ""
    default_time = "3:30 PM"
    default_location = p.get("school") or "School"

    with st.form("contact_form"):
        c1, c2 = st.columns(2)
        parent_email = c1.text_input("Parent / guardian email", value=default_email, placeholder="parent@email.com")
        meeting_date = c2.text_input("Meeting date", value=default_date, placeholder="e.g. Nov 12, 2026")
        c3, c4 = st.columns(2)
        meeting_time = c3.text_input("Meeting time", value=default_time)
        meeting_location = c4.text_input("Location / link", value=default_location)
        extra_note = st.text_area("Additional note to parents (optional)",
                                  placeholder="e.g. Please bring any recent reports or progress notes.")
        submitted = st.form_submit_button("✉️ Build invitation")

    if submitted or st.session_state.get(f"contact_built_{sid}"):
        if submitted:
            st.session_state[f"contact_built_{sid}"] = {
                "parent_email": parent_email, "meeting_date": meeting_date,
                "meeting_time": meeting_time, "meeting_location": meeting_location,
                "extra_note": extra_note,
            }
        saved = st.session_state[f"contact_built_{sid}"]
        pe, md, mt, ml, en = (saved["parent_email"], saved["meeting_date"],
                               saved["meeting_time"], saved["meeting_location"], saved["extra_note"])

        inv_subject = f"IEP Meeting Invitation – {name}"
        extra_note_line = ("\n" + en + "\n") if en else ""
        inv_body = f"""Dear Parent/Guardian of {name},

We would like to invite you to {name}'s Annual IEP (Individualized Education Program) Team Meeting.

  Date:     {md or '[DATE]'}
  Time:     {mt}
  Location: {ml}

The purpose of this meeting is to review {first}'s progress, update annual goals, and discuss the services and supports for the coming year.

Please confirm your attendance by replying to this email or calling the school office.
{extra_note_line}
You have the right to bring anyone you feel can assist you, including an advocate.
A copy of your procedural safeguards is available upon request.

Thank you for your partnership in {first}'s education.

{p.get('case_manager') or 'The IEP Team'}
{p.get('school') or ''}""".strip()

        st.markdown("#### Invitation preview")
        st.text_area("", inv_body, height=300, key=f"inv_preview_{sid}")

        mailto_href = (
            f"mailto:{pe}?subject={urllib.parse.quote(inv_subject)}"
            f"&body={urllib.parse.quote(inv_body)}"
        )
        st.markdown(f"[📨 Open in your email client]({mailto_href})")
        st.download_button("⬇️ Download invitation (.txt)", data=inv_body,
                           file_name=f"Invitation_{sid}.txt", mime="text/plain")

    st.divider()
    st.markdown("### 📝 Conference / Meeting Summary")
    st.caption("A short summary you can copy into an email or parent portal after the meeting.")
    conf_key = f"conf_{sid}_{vcount}"
    if st.button("Generate meeting summary", key=f"conf_btn_{sid}"):
        with st.spinner("Writing summary…"):
            iep_text = iep_schema_text = core._context(sid)[0]
            summary = run_safely(
                core._chat,
                "You help special education teachers communicate with parents. "
                "Write a brief, warm, jargon-free meeting summary a teacher could email to a parent "
                "after an IEP meeting. Use ONLY the IEP information given. "
                "Never invent facts.",
                f"""Write a 3-paragraph meeting summary email for the parent of {name}.
Paragraph 1: What the team discussed and decided (goals, services, placement).
Paragraph 2: Next steps and key dates.
Paragraph 3: A warm closing with contact info placeholder.

IEP:
{iep_schema_text}""",
            )
            st.session_state[conf_key] = summary
    if st.session_state.get(conf_key):
        st.text_area("Copy and send to parents", st.session_state[conf_key], height=250,
                     key=f"conf_text_{sid}")


# --- Goal-based Activities & Worksheets -----------------------------------------------------
with tab_act:
    st.markdown("### 🎯 Activities & Worksheets by Goal")
    st.caption(
        "The AI generates practical classroom activity ideas and a worksheet prompt for each "
        "annual goal. These are starting points — the teacher always adapts them for the student."
    )
    act_key = f"activities_{sid}_{vcount}"
    if not iep["goals"]:
        st.info("No annual goals yet. Add goals in 📄 IEP form → Page 5, then come back here.")
    else:
        if st.button("✨ Generate activities & worksheets", type="primary",
                     key=f"act_btn_{sid}",
                     disabled=act_key in st.session_state):
            with st.spinner("Generating ideas for each goal… (may take a minute)"):
                result = run_safely(core.generate_activities, sid)
            if result is not None:
                st.session_state[act_key] = result
        if act_key in st.session_state and st.button("🔄 Regenerate", key=f"act_regen_{sid}"):
            with st.spinner("Regenerating…"):
                result = run_safely(core.generate_activities, sid)
            if result is not None:
                st.session_state[act_key] = result

        for i, item in enumerate(st.session_state.get(act_key) or []):
            with st.expander(f"**Goal {i + 1}: {item.get('goal_area', '')}**", expanded=True):
                st.markdown(f"*Goal:* {item.get('goal_text', '')}")
                st.markdown("**Classroom Activities**")
                for j, act in enumerate(item.get("activities", []), 1):
                    st.markdown(f"{j}. {act}")
                st.markdown("**Worksheet / Printable Idea**")
                st.info(item.get("worksheet_prompt", ""))

        if not st.session_state.get(act_key):
            st.markdown("Click **Generate activities & worksheets** above to get started.")


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