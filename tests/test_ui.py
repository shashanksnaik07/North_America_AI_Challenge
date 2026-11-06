from pathlib import Path
import core
import reviews
import pdf_workspace as P
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1]/'app.py'


def click(app, label):
    label={'Read':'View IEP','Edit':'Edit draft'}.get(label,label)
    next(b for b in app.button if b.label == label).click().run()
    assert not app.exception, app.exception
    assert not app.error, app.error
    return app


def select(app, label, value):
    next(s for s in app.selectbox if s.label == label).set_value(value).run()
    assert not app.exception, app.exception


def ready(record, original_pdf):
    sid=core.create_student(record)
    P.save_document(sid,P.archive_source(original_pdf,record,'source.pdf'))
    app=AppTest.from_file(str(APP),default_timeout=60).run()
    assert not app.exception, app.exception
    next(b for b in app.button if b.key=='open_iep_'+sid).click().run()
    return sid, app


def test_pdf_edit_review_confirmation_workflow(workspace, record, original_pdf):
    sid,app=ready(record,original_pdf)
    assert not app.text_area  # reading view does not start with an edit form
    click(app,'Edit')
    select(app,'Field','student_name')
    next(t for t in app.text_area if t.label=='Proposed wording').set_value('Jordan Test').run()
    click(app,'Save for review')
    assert core.get_iep(sid)['student_name']=='Jordan Ellis'
    assert len(reviews.list_reviews(sid,open_only=True))==1
    click(app,'Continue to decision')
    assert next(b for b in app.button if b.label=='Approve changes').disabled
    next(t for t in app.text_input if t.label=='Reviewer name').set_value('UI Reviewer').run()
    assert next(b for b in app.button if b.label=='Approve changes').disabled
    next(c for c in app.checkbox if c.label.startswith('I checked the source')).check().run()
    click(app,'Approve changes')
    assert core.get_iep(sid)['student_name']=='Jordan Test'
    assert reviews.list_reviews(sid)[0]['status']=='approved'
    assert P.source_bytes(P.student_document(sid))==original_pdf


def test_onboarding_and_templates_without_students(workspace):
    app=AppTest.from_file(str(APP),default_timeout=60).run()
    assert [t.label for t in app.tabs]==['My caseload','Student workspace']
    assert any(b.label=='Import an IEP' for b in app.button)
    assert not app.exception
    app.session_state['main_navigation']='Student workspace'
    app.session_state['setup_section']='Templates'
    app.run()
    assert not app.exception,app.exception
    assert len(next(s for s in app.selectbox if s.label=='Template').options)==32


def test_tools_and_form_sections_remain_available(workspace,record,original_pdf):
    sid,app=ready(record,original_pdf)
    for tool in ['Suggested modifications','Edit','Read']:
        click(app,tool)
        assert [t.label for t in app.tabs]==['My caseload','Student workspace']
        assert any(s.label=='Zoom' for s in app.selectbox)
    next(s for s in app.segmented_control if s.label=='View').set_value('Form').run()
    for section in ['Student information & present levels','Special factors','Transition','Annual goals','Services & accommodations','Placement & team','Additional fields']:
        select(app,'Form section',section)
    assert not app.error


def test_draft_persists_across_tools_and_is_student_specific(workspace,record,original_pdf):
    sid,app=ready(record,original_pdf)
    click(app,'Edit')
    select(app,'Field','student_name')
    next(t for t in app.text_area if t.label=='Proposed wording').set_value('Unsaved draft name').run()
    click(app,'Suggested modifications'); click(app,'Edit')
    assert next(t for t in app.text_area if t.label=='Proposed wording').value=='Unsaved draft name'
    other=core.create_student(core.blank_iep('Other Student'))
    app.run()
    select(app,'Student',other)
    click(app,'Edit')
    select(app,'Field','student_name')
    assert next(t for t in app.text_area if t.label=='Proposed wording').value=='Other Student'
    select(app,'Student',sid)
    assert next(t for t in app.text_area if t.label=='Proposed wording').value=='Unsaved draft name'
    assert core.get_iep(sid)['student_name']=='Jordan Ellis'


def test_report_to_suggestion_navigation(platform,record,original_pdf):
    import integrations as I
    sid,app=ready(record,original_pdf)
    I.sync_sis('powerschool',platform.base)
    I.link_student(sid,'powerschool','powerschool:stu-001')
    I.submit_report(sid,'powerschool:math-9','Demo Teacher','Extended time','Sometimes','Mixed','Observed completion varies.','2026-10-01','2026-10-31')
    app.session_state['main_navigation']='Student workspace'
    app.session_state['student_section']='Progress & reports';app.run()
    click(app,'Use these reports to draft an update')
    assert app.session_state['main_navigation']=='Student workspace'
    assert app.session_state['active_tool_'+sid]=='Modifications'
    assert any(b.label=='Draft modifications' for b in app.button)


def test_caseload_search_and_student_overview(workspace,record,original_pdf):
    sid=core.create_student(record)
    app=AppTest.from_file(str(APP),default_timeout=60).run()
    assert app.session_state['main_navigation']=='My caseload'
    next(t for t in app.text_input if t.label=='Find a student').set_value('no match').run()
    assert not any(b.label=='Open IEP' for b in app.button)
    next(t for t in app.text_input if t.label=='Find a student').set_value('Jordan').run()
    next(b for b in app.button if b.key=='profile_'+sid).click().run()
    assert app.session_state['student_section']=='Overview'
    assert any(b.label=='Open current IEP' for b in app.button)


def test_new_import_review_has_its_own_student_context(workspace,record,original_pdf):
    import copy
    sid=core.create_student(record)
    imported=copy.deepcopy(record);imported['student_name']='New Import Student'
    rid=reviews.stage_import(imported,'new.pdf',original_pdf,'custom','Importer')
    reviews.stage_import(record,'another.pdf',original_pdf,'custom','Importer')
    app=AppTest.from_file(str(APP),default_timeout=60).run()
    next(b for b in app.button if b.key=='open_import_'+rid).click().run()
    assert not app.exception,app.exception
    assert any(x.value=='New student import' for x in app.subheader)
    assert not any(s.label=='Student' for s in app.selectbox)
    assert next(s for s in app.selectbox if s.label=='Change to review').value==rid
    assert len(next(s for s in app.selectbox if s.label=='Change to review').options)==1
    assert core.get_iep(sid)['student_name']=='Jordan Ellis'


def test_escalated_review_explains_disabled_decision(workspace,record,original_pdf):
    import copy
    sid,app=ready(record,original_pdf)
    candidate=copy.deepcopy(record);candidate['grade']='10'
    rid=reviews.stage_change(sid,candidate,'Grade change','Teacher')
    reviews.escalate(rid,'Teacher','Check source','Assigned Specialist','Specialist')
    app.run()
    click(app,'Review drafts (1)');click(app,'Continue to decision')
    next(t for t in app.text_input if t.label=='Reviewer name').set_value('Assigned Specialist').run()
    next(c for c in app.checkbox if c.label.startswith('I checked the source')).check().run()
    assert next(b for b in app.button if b.label=='Approve changes').disabled
    select(app,'Reviewer role','Specialist')
    assert not next(b for b in app.button if b.label=='Approve changes').disabled
    assert reviews.get(rid)['status']=='escalated'


def test_connections_from_caseload_identify_the_target_student(workspace,record):
    sid=core.create_student(record)
    app=AppTest.from_file(str(APP),default_timeout=60).run()
    click(app,'Connections')
    assert next(s for s in app.selectbox if s.label=='Student').value==sid
    assert any(b.label=='Refresh roster' for b in app.button)
    click(app,'Back to student workspace')
    assert next(s for s in app.selectbox if s.label=='Student').value==sid


def test_single_modification_workflow_discussion_to_review(workspace,record,original_pdf,monkeypatch):
    sid,app=ready(record,original_pdf)
    monkeypatch.setattr(core,'answer',lambda student,question:('Consider course-specific evidence before changing the plan.',[]))
    monkeypatch.setattr(core,'suggest_updates',lambda student,note:[{
        'action':'change','field':'profile.needs','section':'Learning and support needs','source':'test observation',
        'current_text':record['profile']['needs'],'suggested_text':'Proposed classroom support wording.',
        'reason':'Compare observations across courses.','teacher_note':note,'evidence':[]}])
    click(app,'Suggested modifications')
    assert not any(b.label in ['Ask','Suggest updates','Accommodations','Generate summary','Summary'] for b in app.button)
    next(t for t in app.text_area if t.label=='Question or observation').set_value('How should task chunking change?').run()
    click(app,'Discuss options')
    assert app.session_state['modification_discussion_'+sid]
    click(app,'Draft modifications')
    assert core.get_iep(sid)==record
    next(t for t in app.text_area if t.label=='Proposed wording').set_value('Edited support wording retained for review.').run()
    click(app,'View IEP');click(app,'Suggested modifications')
    assert next(t for t in app.text_area if t.label=='Proposed wording').value=='Edited support wording retained for review.'
    click(app,'Send change to review')
    assert len(reviews.list_reviews(sid,open_only=True))==1
    assert reviews.list_reviews(sid)[0]['candidate']['profile']['needs']=='Edited support wording retained for review.'
    assert core.get_iep(sid)==record


def test_mock_caseload_filters_and_pagination(workspace,record):
    import copy
    for index in range(24):
        r=copy.deepcopy(record);r['student_name']=f'Demo filter {index:02d}'
        r['extensions']={'mock_cohort':'test','mock_profile_type':'Profile A' if index<12 else 'Profile B',
                         'mock_template_state':'Alabama' if index%2==0 else 'Montana',
                         'mock_template_id':'alabama-state-iep-template' if index%2==0 else 'montana-office-of-public-instruction-iep-blank'}
        core.create_student(r)
    app=AppTest.from_file(str(APP),default_timeout=60).run()
    assert len([b for b in app.button if b.label=='Open IEP'])==20
    select(app,'Mock profile','Profile B');select(app,'Template state','Montana')
    assert len([b for b in app.button if b.label=='Open IEP'])==6
    assert not any(b.label=='Demo filter 00' for b in app.button)


def test_catalog_option_joins_the_same_draft_queue(workspace,record,original_pdf,monkeypatch):
    sid,app=ready(record,original_pdf)
    option={'id':'time_001','name':'Planned breaks','category':'timing','description':'Agree on a short break and return cue.',
            'matched_on':['task'],'assessment_use':False,'instructional_use':True,'evidence_level':'unverified'}
    monkeypatch.setattr(core,'recommend_accommodations',lambda *args,**kwargs:[option])
    click(app,'Suggested modifications');click(app,'Find relevant options')
    assert next(b for b in app.button if b.label=='Add option to draft').disabled
    for label,value in [('When / how often','During long independent tasks'),('Amount or duration','Three minutes'),('Course or setting','Communication course')]:
        next(t for t in app.text_input if t.label==label).set_value(value).run()
    click(app,'Add option to draft')
    suggestion=app.session_state['suggestions_'+sid][0]
    assert suggestion['payload']['frequency']=='During long independent tasks'
    assert suggestion['payload']['amount']=='Three minutes'
    click(app,'Add option to draft')
    assert len(app.session_state['suggestions_'+sid])==1  # duplicate clicks do not add duplicate services
    next(t for t in app.text_input if t.label=='Amount or duration').set_value('Five minutes').run()
    click(app,'Add option to draft')
    [t for t in app.text_area if t.label=='Proposed wording'][1].set_value('Keep this edited break plan.').run()
    next(b for b in app.button if b.label=='Discard option').click().run()
    assert next(t for t in app.text_area if t.label=='Proposed wording').value=='Keep this edited break plan.'
    assert core.get_iep(sid)==record
    click(app,'Send change to review')
    review=reviews.list_reviews(sid)[0]
    assert review['status']=='pending'
    assert review['candidate']['services']['supplementary_aids']['rows'][-1]['location']=='Communication course'
    assert review['candidate']['services']['supplementary_aids']['rows'][-1]['service']=='Keep this edited break plan.'
    assert any(e.get('catalog_id')=='time_001' for e in review['evidence'])


def test_grades_show_assignment_instructor_course_and_filter(platform,record,original_pdf):
    import integrations as I
    sid,app=ready(record,original_pdf)
    I.sync_sis('powerschool',platform.base)
    I.link_student(sid,'powerschool','powerschool:stu-001')
    for course in ['math-9','english-9']:I.sync_lms(sid,'powerschool:'+course,platform.base)
    next(s for s in app.segmented_control if s.label=='Student record').set_value('Progress & reports').run()
    assert not app.exception,app.exception
    grades=next(d.value for d in app.dataframe if 'Assignment' in d.value.columns)
    assert set(grades['Course'])=={'Algebra I','English 9'}
    assert set(grades['Grade'])=={'78 / 100','86 / 100'}
    assert set(grades['Date'])=={'Not supplied'}
    assert not grades['Instructor'].str.contains('Author not provided').any()
    assert 'Comment' not in grades.columns
    comments=[r['observation'] for r in I.evidence(sid) if r['kind']=='lti_result']
    page_text=[m.value for m in app.markdown]
    assert sum(page_text.count(comment) for comment in set(comments))==1
    assert not any(e.label.startswith('All reports & course evidence') for e in app.expander)
    select(app,'Filter by course','Algebra I')
    grades=next(d.value for d in app.dataframe if 'Assignment' in d.value.columns)
    assert len(grades)==1 and grades.iloc[0]['Course']=='Algebra I'
    math_comment=next(r['observation'] for r in I.evidence(sid) if r['course']=='Algebra I')
    assert [m.value for m in app.markdown].count(math_comment)==1
    click(app,'Use these reports to draft an update')
    assert app.session_state['active_tool_'+sid]=='Modifications'


def test_batch_draft_submits_once_and_removes_queue(workspace,record,original_pdf,monkeypatch):
    sid,app=ready(record,original_pdf)
    monkeypatch.setattr(core,'suggest_updates',lambda student,note:[
        core._make_change(record,'grade','10','Course evidence','teacher note'),
        core._make_change(record,'profile.needs','A private checkpoint during independent tasks.','Course evidence','teacher note')])
    click(app,'Suggested modifications')
    next(t for t in app.text_area if t.label=='Question or observation').set_value('Review the plan').run()
    click(app,'Draft modifications');click(app,'Draft modifications')
    assert len(app.session_state['suggestions_'+sid])==2
    click(app,'Send all changes to review')
    assert len(reviews.list_reviews(sid))==1
    assert not app.session_state['suggestions_'+sid]
    assert core.get_iep(sid)==record


def test_workspace_reset_clears_take_data_and_session_confirmations(workspace,record,original_pdf):
    import demo_snapshots as snapshots
    sid,app=ready(record,original_pdf)
    saved=snapshots.capture('Demo start')
    changed=core.get_iep(sid);changed['grade']='10';core.save_iep(sid,changed)
    added=core.create_student(core.blank_iep('Student from take one'))
    app.session_state['suggestions_'+sid]=[{'suggested_text':'Unsaved take-one draft'}]
    app.session_state['reviewer_name']='Take-one reviewer'
    app.session_state['setup_section']='Demo & reset';app.run()
    assert not app.exception,app.exception
    assert next(b for b in app.button if b.label=='Reset for next take').disabled
    next(c for c in app.checkbox if c.label=='Reset all application data to this snapshot').check().run()
    click(app,'Reset for next take')
    assert core.get_iep(sid)==record and added not in core.list_students()
    assert 'suggestions_'+sid not in app.session_state
    assert 'reviewer_name' not in app.session_state
    assert not app.exception
