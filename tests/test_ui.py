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
    for tool in ['Ask','Suggest updates','Accommodations','History','Summary','Edit','Read']:
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
    click(app,'Ask'); click(app,'Edit')
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
    assert app.session_state['active_tool_'+sid]=='Suggest updates'
    assert any(b.label=='Draft suggestions' for b in app.button)


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
