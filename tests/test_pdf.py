import copy
import io
import pymupdf as fitz
from pypdf import PdfReader
import pytest
import pdf_workspace as P

def test_original_layout_edit_and_overlay(workspace, record, original_pdf):
    record['profile']['needs'] = 'Short reading tasks support attention.'
    doc = P.archive_source(original_pdf, record, 'source.pdf')
    doc = P.set_binding(doc, 'profile.needs', {'page': 0, 'rect': [40, 130, 560, 195]})
    changed = copy.deepcopy(record); changed['profile']['needs'] = 'Provide short reading tasks with scheduled breaks.'
    result, unmapped = P.render_document(doc, changed)
    assert not unmapped
    with fitz.open(stream=result, filetype='pdf') as out:
        text = out[0].get_text()
        assert 'scheduled breaks' in text and 'Unchanged footer and layout' in text
        assert 'Short reading tasks support attention.' not in text
    assert P.source_bytes(doc) == original_pdf
    bindings = doc['bindings']['profile.needs']
    assert P.page_image(result, 0, bindings, 'green') != P.page_image(original_pdf, 0, bindings, 'red')

def test_unmapped_changes_are_not_silently_lost(workspace, record, original_pdf):
    doc = P.archive_source(original_pdf, record, 'source.pdf')
    changed = copy.deepcopy(record); changed['grade'] = '12'
    output, unmapped = P.render_document(doc, changed)
    assert any(d['path'] == 'grade' for d in unmapped)
    with fitz.open(stream=output, filetype='pdf') as pdf:
        assert len(pdf) == 2 and 'grade' in pdf[-1].get_text()

def test_overflow_blocks_export(workspace, record, original_pdf):
    doc = P.archive_source(original_pdf, record, 'source.pdf')
    doc = P.set_binding(doc, 'profile.needs', {'page': 0, 'rect': [40, 130, 90, 150]})
    changed = copy.deepcopy(record); changed['profile']['needs'] = 'Very long proposed content. ' * 100
    with pytest.raises(ValueError, match='does not fit'): P.render_document(doc, changed)

def test_widget_value_and_appearance_are_updated(workspace, record):
    doc = fitz.open(); page = doc.new_page()
    widget = fitz.Widget(); widget.field_name = 'StudentName'; widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.rect = fitz.Rect(40, 40, 300, 70); widget.field_value = record['student_name']; widget.text_fontsize = 12
    page.add_widget(widget); original = doc.tobytes(); doc.close()
    source = P.archive_source(original, record, 'form.pdf')
    assert source['bindings']['student_name'][0]['widget'] == 'StudentName'
    changed = copy.deepcopy(record); changed['student_name'] = 'Synthetic Updated Student'
    result, missing = P.render_document(source, changed)
    reader = PdfReader(io.BytesIO(result))
    assert reader.get_fields()['StudentName']['/V'] == changed['student_name']
    for annotation in reader.pages[0]['/Annots']:
        widget = annotation.get_object()
        owner = widget
        while '/V' not in owner and '/Parent' in owner: owner = owner['/Parent'].get_object()
        assert owner['/V'] == changed['student_name'] and '/N' in widget['/AP']
    assert P.page_image(original, 0) != P.page_image(result, 0)

def test_rotation_coordinate_round_trip(workspace, record, original_pdf):
    with fitz.open(stream=original_pdf, filetype='pdf') as doc:
        doc[0].set_rotation(90); rotated = doc.tobytes()
    source = P.archive_source(rotated, record, 'rotated.pdf')
    rect = [40, 130, 560, 195]
    view = P.view_rectangle(source, 0, rect)
    assert P.view_rectangle(source, 0, view, inverse=True) == pytest.approx(rect)
    source = P.set_binding(source, 'profile.needs', {'page': 0, 'rect': rect})
    changed = copy.deepcopy(record); changed['profile']['needs'] = 'Updated observation'
    assert P.render_document(source, changed)[0]

def test_rectangle_and_source_integrity(workspace, record, original_pdf):
    source = P.archive_source(original_pdf, record, 'source.pdf')
    with pytest.raises(ValueError, match='inside'): P.set_binding(source, 'grade', {'page': 0, 'rect': [-5, 0, 500, 40]})
    (workspace/source['source']).write_bytes(b'changed')
    with pytest.raises(ValueError, match='changed on disk'): P.source_bytes(source)


def test_ambiguous_repeated_text_is_not_mapped(workspace, record):
    record['profile']['needs'] = 'Repeated observation'
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 60), 'Repeated observation')
        page.insert_text((40, 160), 'Repeated observation')
        source = P.archive_source(doc.tobytes(), record, 'ambiguous.pdf')
    assert 'profile.needs' not in source['bindings']
