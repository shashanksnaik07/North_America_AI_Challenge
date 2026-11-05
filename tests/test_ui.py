from pathlib import Path
import core
import reviews
import pdf_workspace as P
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1]/'app.py'

def test_pdf_edit_review_confirmation_workflow(workspace, record, original_pdf):
    sid = core.create_student(record)
    P.save_document(sid, P.archive_source(original_pdf, record, 'source.pdf'))
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not app.exception
    next(t for t in app.text_input if t.label == 'Your name (for the change log)').set_value('UI Reviewer').run()
    next(t for t in app.text_area if t.label == 'Proposed wording / value').set_value('Jordan Test')
    next(b for b in app.button if b.label == 'Submit PDF edit for review').click().run()
    assert not app.exception, app.exception
    assert core.get_iep(sid)['student_name'] == 'Jordan Ellis'
    assert len(reviews.list_reviews(sid, open_only=True)) == 1
    next(c for c in app.checkbox if c.label.startswith('I reviewed the original source')).check().run()
    next(b for b in app.button if b.label == 'Approve changes').click().run()
    assert not app.exception, app.exception
    assert not app.error
    assert core.get_iep(sid)['student_name'] == 'Jordan Test'
    assert reviews.list_reviews(sid)[0]['status'] == 'approved'
    assert P.source_bytes(P.student_document(sid)) == original_pdf

def test_global_inbox_and_templates_available_without_students(workspace):
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    assert [t.label for t in app.tabs] == ['Document', 'Connections & templates']
    assert not app.exception
    assert any('No reviews' in x.value for x in app.info)
    next(r for r in app.radio if r.label == 'Connection workspace').set_value('Template designer').run()
    assert not app.exception, app.exception
    assert len(next(s for s in app.selectbox if s.label == 'Template').options) == 32


def test_tools_remain_in_two_tab_document_workspace(workspace, record, original_pdf):
    sid = core.create_student(record)
    P.save_document(sid, P.archive_source(original_pdf, record, 'source.pdf'))
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    for tool in ['Ask', 'Suggest updates', 'Accommodations', 'History', 'Summary', 'Review', 'Edit']:
        next(s for s in app.selectbox if s.label == 'Document tool').set_value(tool).run()
        assert not app.exception, (tool, app.exception)
        assert [t.label for t in app.tabs] == ['Document', 'Connections & templates']
        assert any(s.label == 'Zoom' for s in app.selectbox)
    next(s for s in app.selectbox if s.label == 'Document view').set_value('Equivalent form').run()
    assert not app.exception, app.exception
