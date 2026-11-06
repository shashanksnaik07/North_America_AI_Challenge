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
    app.run(); click(app, 'Review draft')
    assert len(captured[-1]['pages']) == 2
    assert captured[-1]['highlighted_fields'] == []
    assert [r['path'] for r in captured[-1]['redlines']] == ['student_name']
    assert next(s for s in app.segmented_control if s.label=='Compare PDF').value == 'Changes'
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


def test_redlines_include_deletions_additions_and_repeated_regions(workspace, record, original_pdf):
    document = P.archive_source(original_pdf, record, 'source.pdf')
    document['bindings'] = {
        'profile.needs':[{'page':0,'rect':[40,130,560,195]}, {'page':0,'rect':[40,400,560,465]}],
        'progress_report_weeks':[{'page':0,'rect':[40,70,80,90]}],
    }
    before = copy.deepcopy(record); before['profile']['needs'] = 'Use extended time for all tasks.'; before['progress_report_weeks'] = 6
    after = copy.deepcopy(before); after['profile']['needs'] = 'Use planned breaks for independent tasks.'; after['progress_report_weeks'] = 4
    redlines = V.review_redlines(document,before,after)
    assert len(redlines) == 3
    needs = [r for r in redlines if r['path']=='profile.needs']
    assert needs[0]['tokens'] == needs[1]['tokens']
    assert {'kind':'delete','text':'extended time'} in needs[0]['tokens']
    assert {'kind':'insert','text':'planned breaks'} in needs[0]['tokens']
    number = next(r for r in redlines if r['path']=='progress_report_weeks')
    assert number['tokens'] == [{'kind':'delete','text':'6'},{'kind':'insert','text':'4'}]
    assert P.source_bytes(document) == original_pdf


def test_redlines_handle_removed_fields_rotation_and_partial_bindings(workspace, record, original_pdf):
    with fitz.open(stream=original_pdf,filetype='pdf') as pdf:
        pdf[0].set_rotation(90); rotated = pdf.tobytes()
    document = P.archive_source(rotated,record,'rotated.pdf')
    document['bindings'] = {
        'student_name':[{'page':0,'rect':[40,70,140,90],'name_part':'first'}, {'page':0,'rect':[140,70,240,90],'name_part':'last'}],
        'extensions.teacher_comment':[{'page':0,'rect':[40,130,560,195]}],
    }
    before = copy.deepcopy(record); before['extensions']['teacher_comment'] = '<script>remove me</script>'
    after = copy.deepcopy(before); after['student_name'] = 'Jordan Updated'; del after['extensions']['teacher_comment']
    redlines = V.review_redlines(document,before,after)
    assert len(redlines)==2  # unchanged first name is not marked as removed
    name = next(r for r in redlines if r['path']=='student_name')
    assert name['rect'] == [702,140,722,240]
    assert name['tokens'] == [{'kind':'delete','text':'Ellis'},{'kind':'insert','text':'Updated'}]
    removed = next(r for r in redlines if r['path'].startswith('extensions.'))
    assert removed['tokens'] == [{'kind':'delete','text':'<script>remove me</script>'}]
