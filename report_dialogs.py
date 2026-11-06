"""On-demand report tools, keeping the assignment page focused on evidence."""
import datetime as dt
import streamlit as st
import integrations as I
import student_team as Team
import workspace_state as W
import workspace_ui as U


def course_index(courses, selected):
    return next((i for i,c in enumerate(courses) if c['title']==selected),0)


@st.dialog('Add a report',width='large')
def add_report(sid,courses,selected,generation):
    left,right=st.columns(2)
    course=left.selectbox('Course',courses,index=course_index(courses,selected),format_func=lambda c:c['title'],key='report_course_'+sid)
    role=right.selectbox('Your role',Team.REPORT_ROLES,key='report_role_'+sid)
    reporter=U.name_choice('Your name',Team.names(sid,role,course['sourcedId']),f'report_name_{sid}_{role}_{course["sourcedId"]}')
    with st.form('course_report_'+sid):
        accommodation=st.text_input('Accommodation used',placeholder='For example, extended time')
        left,right=st.columns(2)
        usage=left.selectbox('How often was it used?',['Every opportunity','Most opportunities','Sometimes','Not used'])
        effectiveness=right.selectbox('What did you observe?',['Helpful','Mixed','Not helpful','Insufficient evidence'])
        left,right=st.columns(2)
        start=left.date_input('Reporting period starts',value=dt.date.today().replace(day=1))
        end=right.date_input('Reporting period ends',value=dt.date.today())
        observation=st.text_area('Examples and observations',placeholder='Describe the task, how the accommodation was used, and what you noticed.')
        if st.form_submit_button('Save report',type='primary',icon=':material/save:'):
            try:
                with W.guard():
                    W.check_generation(generation)
                    I.submit_report(sid,course['sourcedId'],reporter,accommodation,usage,effectiveness,observation,start,end,role)
                U.notice('Report saved. It is now available to Suggested modifications.')
            except Exception as exc: st.error(str(exc))


@st.dialog('Team reports',width='large')
def team_reports(sid,visible):
    from workspace_design import evidence_cards
    reports,summary=st.tabs(['Individual reports','Accommodation summary'])
    with reports:
        direct=[r for r in visible if r['kind']=='report']
        if direct:
            selected=st.selectbox('Report',range(len(direct)),format_func=lambda i:
                ' · '.join(str(v) for v in [direct[i].get('reporter'),direct[i].get('reporter_role'),direct[i].get('course'),direct[i].get('period_end'),(direct[i].get('observation') or '')[:55]] if v))
            evidence_cards([direct[selected]])
        else: st.info('No team reports for this course selection yet.')
    with summary:
        aggregation=I.aggregate_reports(sid,records=visible)
        if not aggregation: st.info('No accommodation observations for this course selection yet.')
        for group in aggregation:
            with st.container(border=True):
                st.markdown('**'+group['Accommodation']+'**')
                st.caption(f"{group['Reports']} reports · {group['Courses']}")
                st.write('Observed outcomes: '+group['Outcomes'])
                if group['Mixed observations']: st.caption('Observations differ across courses. Review the examples before drawing conclusions.')


@st.dialog('Refresh LMS information')
def refresh(sid,courses,selected,generation):
    course=st.selectbox('Course to refresh',courses,index=course_index(courses,selected),format_func=lambda c:c['title'])
    st.caption('Retrieves grades, assignment comments and course membership shared by the connected LMS.')
    if st.button('Refresh course',type='primary',icon=':material/sync:'):
        try:
            W.check_generation(generation)
            records=I.sync_lms(sid,course['sourcedId'])
            U.notice(f'Course refreshed. {len(records)} results available.')
        except Exception as exc: st.error(str(exc))
