"""PDF-centered IEP workspace. Run with streamlit run app.py."""
import json
import streamlit as st
import core
import ontology
import integrations
import reviews
import workspace_ui as U

st.set_page_config(page_title="IEP Assistant", page_icon="📘", layout="wide")
st.markdown("""<style>
.block-container {padding-top:.8rem; max-width:1800px;}
h1 {font-size:1.8rem !important; padding-bottom:.3rem !important;}
h3 {font-size:1.2rem !important;}
div[data-testid="stMetricValue"] {font-size:1rem;white-space:normal;}
</style>""", unsafe_allow_html=True)
st.title("📘 IEP Assistant")
st.caption("Original documents · Human review · Synthetic local integrations")
if "flash" in st.session_state: st.success(st.session_state.pop("flash"))
if 'pending_student' in st.session_state: st.session_state['student']=st.session_state.pop('pending_student')

with st.sidebar:
    teacher=st.text_input("Your name (for the change log)",key="teacher")
    role=st.selectbox("Reviewer role (local demo)",reviews.ROLES)
    if st.button("⚡ Load sample students",width="stretch"):
        for sample in sorted((core.APP_DIR/"samples").glob("*.json")): core.load_sample(sample)
        st.rerun()
    with st.expander("➕ Import an IEP file"): U.import_controls(teacher)
    with st.expander("📝 Start a blank IEP"):
        name=st.text_input("Student name",key="blank_name")
        if st.button("Create",disabled=not name.strip()):
            sid=U.attempt(core.create_student,core.blank_iep(name.strip()))
            if sid: st.session_state['student']=sid;st.rerun()
    students=core.list_students()
    if st.session_state.get('student') not in students: st.session_state.pop('student',None)
    sid=st.radio('Students',list(students),format_func=students.get,key='student') if students else None
    if sid:
        with st.expander('📎 Supporting documents'):
            upload=st.file_uploader('PDF or TXT',type=['pdf','txt'],key='support_'+sid)
            if st.button('Add document',disabled=upload is None):
                text=U.attempt(core.extract_text,upload.name,upload.getvalue())
                if text and U.attempt(core.add_supporting_doc,sid,upload.name,text): U.notice('Supporting document indexed.')
            for filename in core.list_supporting_docs(sid): st.write(filename)
        with st.expander('Student details'):
            profile=core.get_profile(sid)
            st.write({key:value for key,value in profile.items() if key!='name'})
        with st.expander('Student management'):
            delete_confirm=st.checkbox('Delete student records, reviews and course reports (shared PDF archive retained)',key='delete_confirm_'+sid)
            if st.button('Delete student',disabled=not delete_confirm,key='delete_'+sid):
                core.delete_student(sid);st.session_state.pop('student',None);st.rerun()

main_document,main_connections=st.tabs(['Document','Connections & templates'])
with main_document:
    if sid:
        record=core.get_iep(sid)
        st.subheader(record['student_name'])
        U.acrobat_workspace(sid,record,teacher,role)
    else:
        st.info('Load a sample, create a blank record, or submit an import. Pending imports can be confirmed below.')
        U.review_inbox(teacher,role)
with main_connections:
    section=st.radio('Connection workspace',['Courses & reports','Template designer'],horizontal=True)
    if section=='Template designer': U.templates_workspace(teacher)
    elif sid:
        U.connected_courses(sid,teacher)
        with st.expander('Canonical IEP data'):
            record=core.get_iep(sid)
            st.download_button('Download canonical IEP graph',json.dumps(ontology.canonical(record,sid,evidence=integrations.evidence(sid)),indent=2),sid+'-canonical.json','application/json')
    else: st.info('Select a student to connect SIS and course evidence.')
