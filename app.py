"""IEP Bridge. Run with streamlit run app.py."""
from html import escape
from pathlib import Path
import streamlit as st
import core
import reviews
import workspace_ui as U
import workspace_design as Design

st.set_page_config(page_title='IEP Bridge', page_icon='📘', layout='wide')
st.markdown('<style>'+Path(__file__).with_name('ui_style.css').read_text(encoding='utf-8')+'</style>', unsafe_allow_html=True)
if 'pending_student' in st.session_state:
    st.session_state['student']=st.session_state.pop('pending_student')
if 'pending_main' in st.session_state:
    st.session_state['main_navigation']=st.session_state.pop('pending_main')
if 'pending_student_section' in st.session_state:
    st.session_state['student_section']=st.session_state.pop('pending_student_section')

@st.dialog('Add a student', width='large')
def add_student():
    method=st.segmented_control('Start with', ['Import an IEP','Blank IEP'], default='Import an IEP', required=True)
    if method=='Import an IEP': U.import_controls(st.session_state.get('reviewer_name',''))
    else:
        with st.form('blank_student'):
            name=st.text_input('Student name')
            st.caption('Create a blank plan, then add details in the editor.')
            if st.form_submit_button('Create student',type='primary'):
                if not name.strip(): st.error('Enter the student’s name.')
                else:
                    sid=U.attempt(core.create_student,core.blank_iep(name.strip()))
                    if sid:
                        st.session_state['pending_student']=sid
                        st.session_state['pending_main']='Student workspace'
                        st.session_state['pending_student_section']='IEP'
                        st.session_state['pending_tool_'+sid]='Edit'
                        st.session_state.pop('active_import',None)
                        st.session_state.pop('setup_section',None)
                        U.notice('Student created. Use Edit draft to add plan details.')

@st.dialog('Workspace settings', width='small')
def settings():
    st.markdown('**Demonstration workspace**')
    st.caption('Students and integrations use local demo data. Reviewer names and roles are self-selected, not authenticated.')
    if st.button('Load example students',width='stretch'):
        for sample in sorted((core.APP_DIR/'samples').glob('*.json')): core.load_sample(sample)
        U.notice('Example students are ready. Existing plans were kept.')
    students=core.list_students()
    sid=st.session_state.get('student')
    if sid in students:
        with st.expander('Remove a student'):
            st.warning('This removes the student’s local record, reviews and course reports. Shared PDF files remain archived.')
            confirmed=st.checkbox('Remove '+students[sid])
            if st.button('Remove student',disabled=not confirmed):
                core.delete_student(sid)
                st.session_state.pop('student',None)
                U.notice('Student removed.')

with st.container(horizontal=True,vertical_alignment='center'):
    st.markdown('<div class="app-eyebrow">Student support</div><h1>IEP Bridge</h1>',unsafe_allow_html=True)
    with st.container(horizontal=True,horizontal_alignment='right'):
        st.markdown('<span class="status-pill">Local demo</span>',unsafe_allow_html=True)
        with st.popover('Tools & setup',icon=':material/settings:'):
            for area in ['Templates','Connections']:
                if st.button(area,width='stretch'):
                    st.session_state['setup_section']=area
                    st.session_state['pending_main']='Student workspace'
                    st.rerun()
            if st.button('Workspace settings',width='stretch'): settings()
if 'flash' in st.session_state: st.success(st.session_state.pop('flash'))

students=core.list_students()
if st.session_state.get('student') not in students: st.session_state.pop('student',None)
actor=st.session_state.get('reviewer_name','')
role=st.session_state.get('reviewer_role','Case manager')
caseload_tab,student_tab=st.tabs(['My caseload','Student workspace'],key='main_navigation',on_change='rerun')
if caseload_tab.open:
    with caseload_tab:
        with st.container(horizontal=True,vertical_alignment='center'):
            st.subheader('My caseload')
            if st.button('Add student',icon=':material/person_add:'): add_student()
        if students: Design.caseload(students)
        else:
            st.write('Import an existing IEP or explore an example student to get started.')
            with st.container(horizontal=True):
                if st.button('Import an IEP',type='primary'): add_student()
                if st.button('Explore example students'):
                    for sample in sorted((core.APP_DIR/'samples').glob('*.json')): core.load_sample(sample)
                    st.rerun()
        Design.import_queue()
if student_tab.open:
    with student_tab:
        active_import=st.session_state.get('active_import')
        setup=st.session_state.get('setup_section')
        if setup:
            if st.button('Back to student workspace',icon=':material/arrow_back:'):
                st.session_state.pop('setup_section',None);st.rerun()
            setup_student=st.session_state.get('student')
            if setup=='Connections' and students:
                setup_student=st.selectbox('Student',list(students),format_func=students.get,key='student',width=320,persist_state='session')
            Design.resources_workspace(setup_student,actor,setup)
        elif active_import:
            st.subheader('New student import')
            item=reviews.get(active_import)
            st.caption(item['candidate'].get('student_name') or item['title'])
            st.session_state['selected_review']=active_import
            Design.review_inbox(actor,role,imports_only=True,review_id=active_import)
            if st.button('Back to caseload'):
                st.session_state.pop('active_import',None)
                st.session_state['pending_main']='My caseload';st.rerun()
        elif students:
            with st.container(key='student-header'):
                identity,chooser=st.columns([3,1],vertical_alignment='center')
                with chooser:
                    sid=st.selectbox('Student',list(students),format_func=students.get,key='student',persist_state='session')
                record=core.get_iep(sid)
                with identity:
                    st.markdown('<div class="student-title">'+escape(record['student_name'])+'</div>',unsafe_allow_html=True)
                    meta=' · '.join(str(x) for x in [f"Grade {record['grade']}" if record['grade'] else '',record['meta']['school'],record['school_year']] if x)
                    st.markdown('<div class="student-meta">'+escape(meta or 'Add student details in Edit draft')+'</div>',unsafe_allow_html=True)
            section=st.segmented_control('Student record',['Overview','IEP','Documents','Progress & reports'],default='Overview',required=True,key='student_section',persist_state='session')
            if section=='Overview': Design.student_overview(sid,record)
            elif section=='IEP': Design.acrobat_workspace(sid,record,actor,role)
            elif section=='Documents': Design.student_documents(sid,actor)
            else: Design.resources_workspace(sid,actor,'Course reports')
        else:
            st.info('Choose a student from My caseload, or browse templates from Tools & setup.')
