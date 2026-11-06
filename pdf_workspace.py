"""Original PDF preservation, field bindings, non-destructive review and export."""
import copy
import hashlib
import io
import json
from pathlib import Path

import pymupdf as fitz
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from xml.sax.saxutils import escape
import ontology
from local_store import DATA_DIR, atomic_json

def digest(data): return hashlib.sha256(data).hexdigest()

def ensure_form_tree(writer):
    """Restore the canonical form tree when page selection retained only widgets.

    MuPDF's select() keeps widget parent chains but can drop the catalog's
    AcroForm. PDF viewers still paint those appearances, hiding the data loss.
    """
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject
    roots=[];seen=set()
    for page in writer.pages:
        for ref in page.get('/Annots',[]):
            item=ref.get_object()
            if item.get('/Subtype')!='/Widget':continue
            root=ref
            while item.get('/Parent'):
                root=item['/Parent'].indirect_reference;item=root.get_object()
            identity=(root.idnum,root.generation)
            if identity not in seen:roots.append(root);seen.add(identity)
    if not roots:return
    form=writer._root_object.get('/AcroForm')
    if form:form=form.get_object()
    else:
        form=DictionaryObject();writer._root_object[NameObject('/AcroForm')]=writer._add_object(form)
    form[NameObject('/Fields')]=ArrayObject(roots)

def source_bytes(document):
    path = (DATA_DIR / document['source']).resolve()
    if not path.is_relative_to(DATA_DIR.resolve()): raise ValueError('Invalid document location.')
    data = path.read_bytes()
    if digest(data) != document['sha256']: raise ValueError('The original PDF changed on disk.')
    return data

def inspect_pdf(data):
    with fitz.open(stream=data, filetype='pdf') as doc:
        if doc.needs_pass: raise ValueError('Unlock this PDF before importing it.')
        if not len(doc): raise ValueError('The PDF has no pages.')
        pages = []
        for page in doc:
            pages.append({'width': page.rect.width, 'height': page.rect.height,
                          'unrotated_width': page.cropbox.width, 'unrotated_height': page.cropbox.height,
                          'rotation': page.rotation, 'text': page.get_text(),
                          'widgets': [{'name': w.field_name, 'value': w.field_value,
                                       'type': w.field_type_string, 'rect': list(w.rect)} for w in page.widgets() or []]})
        return pages

def bind_text(data, record):
    """Only exact, unambiguous value matches; every suggested binding is editable."""
    bindings = {}
    with fitz.open(stream=data, filetype='pdf') as doc:
        for path, value in ontology.leaf_fields(record).items():
            if not isinstance(value, str) or len(value.strip()) < 5: continue
            matches = []
            for pi, page in enumerate(doc):
                for widget in page.widgets() or []:
                    if widget.field_type == fitz.PDF_WIDGET_TYPE_TEXT and widget.field_value == value:
                        matches.append({'page': pi, 'rect': list(widget.rect), 'widget': widget.field_name, 'confirmed': False})
                if not matches:
                    rects = page.search_for(value)
                    # Multi-line text yields multiple rectangles: combine only when consecutive.
                    contiguous = all(0 < b.y0-a.y0 <= max(a.height, b.height)*1.6 for a,b in zip(rects,rects[1:]))
                    if rects and len(rects) < 20 and contiguous:
                        union = fitz.Rect(rects[0])
                        for rect in rects[1:]: union |= rect
                        if union.height < page.rect.height * .5:
                            matches.append({'page': pi, 'rect': list(union + (-1, -1, 2, 3)), 'confirmed': False})
            if len(matches) == 1 or path in ('student_name', 'dob'):
                if matches: bindings[path] = matches
    return bindings

def archive_source(data, record, filename, template_id='custom', origin='uploaded'):
    inspect_pdf(data)
    sha = digest(data)
    folder = DATA_DIR / 'originals'; folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'{sha}.pdf'
    if not path.exists(): path.write_bytes(data)
    from local_store import get
    design = get('template_design', template_id, {})
    bindings = bind_text(data, record)
    if design.get('source_sha256') == sha:
        bindings.update(copy.deepcopy(design.get('bindings', {})))
    return {'source': str(path.relative_to(DATA_DIR)), 'sha256': sha, 'filename': Path(filename).name,
            'template_id': template_id, 'origin': origin, 'baseline': copy.deepcopy(record),
            'bindings': bindings}

def student_document(sid):
    path = DATA_DIR / 'students' / sid / 'document.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None

def save_document(sid, document):
    atomic_json(DATA_DIR / 'students' / sid / 'document.json', document)

def ensure_document(sid, record):
    document = student_document(sid)
    if document: return document
    import export_pdf
    document = archive_source(export_pdf.build_pdf(record), record, f'{sid}-baseline.pdf', 'alabama-state-iep-template', 'generated baseline')
    save_document(sid, document)
    return document

def validate_binding(document, binding, pages=None):
    if pages is None:
        with fitz.open(stream=source_bytes(document),filetype='pdf') as source:
            pages=[{'unrotated_width':p.cropbox.width,'unrotated_height':p.cropbox.height} for p in source]
    page = binding.get('page')
    if not isinstance(page, int) or not 0 <= page < len(pages): raise ValueError('Invalid page.')
    rect = binding.get('rect', [])
    if len(rect) != 4 or not all(isinstance(x, (int, float)) for x in rect): raise ValueError('A rectangle needs four coordinates.')
    x0, y0, x1, y1 = rect
    p = pages[page]
    if not (0 <= x0 < x1 <= p['unrotated_width'] and 0 <= y0 < y1 <= p['unrotated_height']): raise ValueError('Keep the rectangle inside the page.')
    if x1 - x0 < 12 or y1 - y0 < 10: raise ValueError('Select a larger text area.')

def set_binding(document, path, binding):
    validate_binding(document, binding)
    document = copy.deepcopy(document)
    document['bindings'][path] = [{**binding, 'confirmed': True}]
    return document

def view_rectangle(document, page_number, rect, inverse=False):
    with fitz.open(stream=source_bytes(document), filetype='pdf') as doc:
        page = doc[page_number]
        return list(fitz.Rect(rect) * (page.derotation_matrix if inverse else page.rotation_matrix))

def binding_key(document, path):
    keys = [k for k in document['bindings'] if path == k or path.startswith(k+'.')]
    return max(keys, key=len) if keys else None

def changes(before, after):
    old, new = ontology.leaf_fields(before), ontology.leaf_fields(after)
    return [{'path': p, 'before': old.get(p), 'after': new.get(p),
             'operation': 'add' if p not in old else 'remove' if p not in new else 'replace'}
            for p in sorted(old.keys() | new.keys()) if old.get(p) != new.get(p) or (p in old) != (p in new)]

def _put_text(page, rect, value, color=(0, 0, 0)):
    value = ontology.text(value) if value is not None else ''
    # Test layout on a temporary page first; never leave partially inserted text.
    size = 11
    while size >= 6:
        trial = fitz.open(); trial_page = trial.new_page(width=page.cropbox.width, height=page.cropbox.height)
        remaining = trial_page.insert_textbox(rect, value, fontsize=size, fontname='helv')
        trial.close()
        if remaining >= 0:
            page.insert_textbox(rect, value, fontsize=size, fontname='helv', color=color)
            return
        size -= .5
    raise ValueError('Text does not fit the selected PDF area. Enlarge the binding or shorten the wording.')

def binding_text(page,rect,value,binding):
    if binding.get('format')=='labelled':
        from native_templates import display_value
        text=display_value(value)
    else:text=ontology.text(value) if value is not None else ''
    if binding.get('name_part')=='first':text=text.split(' ',1)[0]
    elif binding.get('name_part')=='last':text=text.split(' ',1)[-1]
    if binding.get('year_part')=='start':text=text.split('-',1)[0]
    elif binding.get('year_part')=='end':text=text.split('-',1)[-1]
    if text and binding.get('suffix'):text+=binding['suffix']
    if binding.get('continuation_page'):
        from native_templates import fits
        if not fits(rect,text):
            suffix=f"See continuation, page {binding['continuation_page']}."
            if not fits(rect,suffix):suffix=f"See p. {binding['continuation_page']}"
            words=text.split()
            while words and not fits(rect,' '.join(words)+' ... '+suffix):words.pop()
            text=(' '.join(words)+' ... ' if words else '')+suffix
    return text


def render_document(document, record, append_unmapped=True):
    """Modify a copy. Original bytes and field-tree values are preserved separately."""
    original = source_bytes(document)
    delta = changes(document['baseline'], record)
    unmapped = []
    with fitz.open(stream=original, filetype='pdf') as doc:
        page_geometry=[{'unrotated_width':p.cropbox.width,'unrotated_height':p.cropbox.height} for p in doc]
        applied = set()
        for change in delta:
            key = binding_key(document, change['path'])
            bindings = document['bindings'].get(key, [])
            if not bindings:
                unmapped.append(change); continue
            if key in applied: continue
            applied.add(key)
            if key != change['path']:
                import iep_schema as S
                try: value = S.get_path(record, key)
                except (KeyError, IndexError): value = None
                change = {**change, 'after': value}
            for binding in bindings:
                validate_binding(document, binding, page_geometry)
                page = doc[binding['page']]
                rect = fitz.Rect(binding['rect'])
                displayed=binding_text(page,rect,change['after'],binding)
                if binding.get('widget'):
                    widget = next((w for w in page.widgets() or [] if w.field_name == binding['widget']), None)
                    if widget is None: raise ValueError('The mapped PDF field is missing.')
                    widget.field_value = displayed
                    if not widget.field_flags & fitz.PDF_TX_FIELD_IS_MULTILINE:
                        length = fitz.get_text_length(widget.field_value, fontname='helv', fontsize=1)
                        size = min(widget.text_fontsize or 11, (rect.width-4)/max(length, 1), (rect.height-4)*.7)
                        if size < 6 or '\n' in widget.field_value:
                            raise ValueError('Text does not fit the PDF form field. Shorten it or bind a larger area.')
                        widget.text_fontsize = size
                    else:
                        trial = fitz.open(); trial_page = trial.new_page(width=page.cropbox.width, height=page.cropbox.height)
                        _put_text(trial_page, rect, displayed); trial.close()
                        widget.text_fontsize = 0  # PDF auto-size, after verifying the minimum readable fit
                    widget.update()
                else:
                    page.add_redact_annot(rect, fill=(1, 1, 1))
                    page.apply_redactions(graphics=0)
                    _put_text(page, rect, displayed)
        if unmapped and append_unmapped:
            buffer = io.BytesIO(); styles = getSampleStyleSheet()
            story = [Paragraph('IEP review addendum - fields without a PDF binding', styles['Heading1']),
                     Paragraph('The original pages are retained. These record changes need placement in the source form. This export does not itself indicate approval.', styles['BodyText']), Spacer(1, 12)]
            for change in unmapped:
                story.extend([Paragraph(escape(change['path']), styles['Heading3']),
                              Paragraph(escape(ontology.text(change['after'])).replace('\n', '<br/>'), styles['BodyText']), Spacer(1, 8)])
            SimpleDocTemplate(buffer).build(story)
            with fitz.open(stream=buffer.getvalue(), filetype='pdf') as appendix: doc.insert_pdf(appendix)
        return doc.tobytes(garbage=3, deflate=True), unmapped

def page_image(data, page_number, overlays=(), color='green', scale=1.3):
    with fitz.open(stream=data, filetype='pdf') as doc:
        page = doc[page_number]
        rgb = (.05, .55, .22) if color == 'green' else (.8, .12, .12)
        for binding in overlays:
            if binding['page'] == page_number:
                page.draw_rect(fitz.Rect(binding['rect']), color=rgb, fill=rgb, fill_opacity=.13, width=2, overlay=True)
        return page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes('png')
