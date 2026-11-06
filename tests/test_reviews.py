import copy
import json
import pytest
import core
import reviews as R
import pdf_workspace as P
import local_store as store

def test_import_does_not_save_until_confirmed(workspace, record, original_pdf):
    rid = R.stage_import(record, 'original.pdf', original_pdf, 'custom', 'Importer')
    assert not core.list_students()
    assert R.get(rid)['status'] == 'pending'
    with pytest.raises(ValueError, match='Confirm'): R.decide(rid, 'approved', 'Reviewer', 'Case manager')
    assert not core.list_students()
    sid = R.decide(rid, 'approved', 'Reviewer', 'Case manager', True)
    assert core.get_iep(sid) == record
    assert P.source_bytes(P.student_document(sid)) == original_pdf
    assert R.get(rid)['events'][-1]['action'] == 'approved'
    with pytest.raises(ValueError, match='resolved'): R.decide(rid, 'approved', 'Reviewer', 'Case manager', True)

def test_ocr_failure_escalation_and_assignee_enforced(workspace, record, original_pdf):
    rid = R.stage_import(record, 'scan.pdf', original_pdf, 'custom', 'Importer', {'ocr_used': True, 'error': 'Model unavailable'})
    assert R.get(rid)['status'] == 'escalated'
    with pytest.raises(ValueError, match='requires'): R.decide(rid, 'approved', 'Alex', 'Case manager', True)
    R.escalate(rid, 'Alex', 'Verify the scan', 'Sam', 'Specialist')
    with pytest.raises(ValueError, match='another reviewer'): R.decide(rid, 'approved', 'Alex', 'Specialist', True)
    sid = R.decide(rid, 'approved', 'Sam', 'Specialist', True)
    assert sid in core.list_students()

def test_rejection_keeps_active_record(workspace, record, original_pdf):
    sid = core.create_student(record)
    P.save_document(sid, P.archive_source(original_pdf, record, 'source.pdf'))
    changed = copy.deepcopy(record); changed['grade'] = '10'
    rid = R.stage_change(sid, changed, 'Grade', 'Teacher')
    R.decide(rid, 'rejected', 'Reviewer', 'Case manager')
    assert core.get_iep(sid) == record
    assert not core.list_versions(sid)

def test_stale_proposals_cannot_overwrite_newer_changes(workspace, record, original_pdf):
    sid = core.create_student(record); P.save_document(sid, P.archive_source(original_pdf, record, 'source.pdf'))
    a = copy.deepcopy(record); a['grade'] = '10'
    b = copy.deepcopy(record); b['grade'] = '11'
    first = R.stage_change(sid, a, 'First')
    with pytest.raises(ValueError, match='different wording'): R.stage_change(sid, b, 'Second')
    R.decide(first, 'approved', 'Reviewer', 'Case manager', True)
    assert core.get_iep(sid)['grade'] == '10'
    assert len(core.list_versions(sid)) == 1
    assert core.list_versions(sid)[0]['document']['sha256'] == P.digest(original_pdf)

def test_review_revision_prevents_lost_corrections(workspace, record, original_pdf):
    rid = R.stage_import(record, 'source.pdf', original_pdf, 'custom', 'A')
    changed = copy.deepcopy(record); changed['grade'] = '10'
    R.update_candidate(rid, changed, 'B', 1)
    with pytest.raises(ValueError, match='Another session'): R.update_candidate(rid, record, 'C', 1)
    with pytest.raises(ValueError, match='Another session'): R.decide(rid, 'approved', 'C', 'Case manager', True, revision=1)

def test_same_name_import_does_not_replace_existing(workspace, record, original_pdf):
    sid = core.create_student(record)
    rid = R.stage_import(record, 'source.pdf', original_pdf, 'custom', 'A')
    other = R.decide(rid, 'approved', 'B', 'Case manager', True)
    assert sid != other and len(core.list_students()) == 2

def test_modification_suggestion_only_stages(workspace, record, original_pdf):
    sid = core.create_student(record); P.save_document(sid, P.archive_source(original_pdf, record, 'source.pdf'))
    suggestion = core._make_change(record, 'grade', '10', 'Synthetic', 'teacher note')
    message = core.apply_suggestion(sid, suggestion, 'Teacher')
    assert 'Added' in message and core.get_iep(sid)['grade'] == record['grade']
    assert len(R.list_reviews(sid, open_only=True)) == 1

def test_diff_escapes_untrusted_html():
    html = R.diff_html('<script>alert(1)</script>', '<img src=x onerror=alert(1)>')
    assert '<script>' not in html and '<img' not in html and '<del ' in html and '<ins ' in html


def test_template_draft_renders_values_into_saved_template_locations(workspace, record, original_pdf):
    import local_store
    import pymupdf
    local_store.put('template_design', 'custom', {
        'source_sha256': P.digest(original_pdf), 'fields': [],
        'bindings': {'student_name': [{'page': 0, 'rect': [80, 68, 400, 95], 'confirmed': True}]}})
    record['student_name'] = 'New Synthetic Student'
    rid = R.stage_import(record, 'blank.pdf', original_pdf, 'custom', 'Author', {'template_draft': True})
    item = R.get(rid)
    output, _ = P.render_document(item['document'], item['candidate'])
    with pymupdf.open(stream=output, filetype='pdf') as doc:
        assert 'New Synthetic Student' in doc[0].get_text()
    assert P.source_bytes(item['document']) == original_pdf


def test_invalid_pdf_is_retained_for_escalation(workspace, record):
    rid = R.stage_import(record, 'unreadable.pdf', b'not a pdf', 'custom', 'Author')
    item = R.get(rid)
    assert item['status'] == 'escalated' and item['document'] is None
    assert (workspace/item['source_attachment']).read_bytes() == b'not a pdf'
    assert not core.list_students()


def test_unicode_round_trip_in_record_and_history(workspace, record):
    record['profile']['needs'] = 'José — visual prompts; math ≤ 3 steps.'
    sid = core.create_student(record)
    changed = copy.deepcopy(record); changed['profile']['needs'] += ' Next review: mañana.'
    core.save_iep(sid, changed, note='Revisión — enseñanza')
    assert core.get_iep(sid) == changed
    assert core.list_versions(sid)[0]['iep'] == record
    assert core.list_versions(sid)[0]['note'] == 'Revisión — enseñanza'


def test_document_only_changes_keep_history_and_block_stale_review(workspace, record, original_pdf):
    sid = core.create_student(record)
    source = P.archive_source(original_pdf, record, 'original.pdf'); P.save_document(sid, source)
    stale = R.stage_import(record, 'replacement.pdf', original_pdf, 'custom', 'Author', target_sid=sid)
    mapped = P.set_binding(source, 'grade', {'page': 0, 'rect': [40, 200, 300, 240]})
    with pytest.raises(ValueError, match='pending import'):
        R.stage_change(sid, record, 'Field location', document=mapped)
    R.decide(stale, 'rejected', 'Reviewer', 'Case manager')
    rid = R.stage_change(sid, record, 'Field location', document=mapped)
    with pytest.raises(ValueError, match='working draft'):
        R.stage_import(record, 'replacement.pdf', original_pdf, 'custom', 'Author', target_sid=sid)
    R.decide(rid, 'approved', 'Reviewer', 'Case manager', True)
    assert core.list_versions(sid)[0]['document'] == source
    assert P.student_document(sid) == mapped
    stale = R.stage_import(record, 'replacement.pdf', original_pdf, 'custom', 'Author', target_sid=sid)
    P.save_document(sid, source)
    with pytest.raises(ValueError, match='PDF bindings changed'):
        R.decide(stale, 'approved', 'Reviewer', 'Case manager', True)


def test_deletion_cannot_revive_proposals_or_linked_evidence(workspace, record, original_pdf):
    import local_store
    sid = core.create_student(record)
    P.save_document(sid, P.archive_source(original_pdf, record, 'original.pdf'))
    changed = copy.deepcopy(record); changed['grade'] = '10'
    R.stage_change(sid, changed, 'Pending')
    local_store.put('report', 'report-1', {'student_id': sid})
    local_store.put('student_link', sid, {'student_id': sid})
    core.delete_student(sid)
    core.create_student(record)
    assert not R.list_reviews(sid)
    assert not local_store.all_records('report')
    assert local_store.get('student_link', sid) is None


def test_template_extension_types_are_validated(workspace, record, original_pdf):
    import jsonschema
    import local_store
    local_store.put('template_design', 'custom', {'fields': [
        {'key': 'observed_count', 'label': 'Observed count', 'type': 'number', 'concept': 'Observation'}]})
    record['extensions'] = {'observed_count': 'not a number'}
    rid = R.stage_import(record, 'source.pdf', original_pdf, 'custom', 'Author')
    with pytest.raises(jsonschema.ValidationError):
        R.decide(rid, 'approved', 'Reviewer', 'Case manager', True)
    record['extensions']['observed_count'] = 3
    R.update_candidate(rid, record, 'Reviewer', 1)
    sid = R.decide(rid, 'approved', 'Reviewer', 'Case manager', True)
    assert core.get_iep(sid)['extensions']['observed_count'] == 3
