"""Preview geometry and navigation integration, without accessing live students."""
import base64
import copy

import pymupdf as fitz

import core
import pdf_workspace as P
import pdf_viewer as V
import reviews
from test_ui import ready, click


def test_continuous_preview_keeps_rotated_fields_and_all_pages(original_pdf):
    with fitz.open(stream=original_pdf, filetype='pdf') as pdf:
        pdf[0].set_rotation(90)
        pdf.new_page(width=300, height=400).insert_text((20, 30), 'Continuation')
        data = pdf.tobytes()
    before = P.digest(data)
    pages = V.preview_pages(data, {'student_name': [{'page': 0, 'rect': [40, 70, 240, 90]}]}, ['Original form'])
    assert len(pages) == 2
    assert (pages[0]['width'], pages[0]['height']) == (792, 612)
    assert pages[0]['fields'] == [{'path': 'student_name', 'rect': [702, 40, 722, 240]}]
    assert pages[1]['label'] == 'Page 2'
    assert not pages[1]['fields']
    assert all(base64.b64decode(page['image']).startswith(b'\x89PNG') for page in pages)
    assert P.digest(data) == before


def test_review_jump_is_explicit_and_every_page_is_available(workspace, record, original_pdf, monkeypatch):
    captured = []
    monkeypatch.setattr(V, 'viewer', lambda **kwargs: captured.append(kwargs))
    with fitz.open(stream=original_pdf, filetype='pdf') as pdf:
        pdf.new_page(width=612, height=792).insert_text((40, 90), record['student_name'])
        data = pdf.tobytes()
    sid, app = ready(record, data)
    document = P.student_document(sid)
    document = P.set_binding(document, 'student_name', {'page': 1, 'rect': [35, 72, 260, 105]})
    P.save_document(sid, document)
    candidate = copy.deepcopy(record); candidate['student_name'] = 'Jordan Updated'
    review_id = reviews.stage_change(sid, candidate, 'Review name', 'Teacher')
    app.run(); click(app, 'Review drafts (1)')
    assert len(captured[-1]['pages']) == 2
    assert captured[-1]['highlighted_fields'] == ['student_name']
    click(app, 'Show this field on PDF')
    first_command = captured[-1]['navigation']
    assert first_command['page'] == 1
    assert captured[-1]['pages'][1]['fields'][0]['path'] == 'student_name'
    click(app, 'Show this field on PDF')
    assert captured[-1]['navigation']['token'] != first_command['token']
    # Reruns retain the command token so ordinary editing does not reset scrolling.
    command = captured[-1]['navigation']
    app.run()
    assert captured[-1]['navigation'] == command
    assert reviews.get(review_id)['status'] == 'pending'
    assert core.get_iep(sid) == record
