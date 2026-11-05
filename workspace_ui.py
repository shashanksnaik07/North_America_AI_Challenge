"""PDF-first workspace, durable review inbox, template designer and mock integrations."""
import base64
import copy
import datetime as dt
import json
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import iep_schema as S
import core
import integrations as I
import local_store as store
import ontology as O
import pdf_workspace as P
import reviews as R

region = components.declare_component('iep_pdf_region', path=str(Path(__file__).parent / 'components' / 'pdf_region'))

def attempt(fn, *args, **kwargs):
    try: return fn(*args, **kwargs)
    except Exception as exc:
        st.error(str(exc)); return None

def notice(message):
    st.session_state['flash'] = message; st.rerun()

def typed_value(label, value, key):
    if isinstance(value, bool) or value is None:
        choice = st.selectbox(label, ['Unanswered', 'Yes', 'No'], index=0 if value is None else 1 if value else 2, key=key, persist_state='session')
        return None if choice == 'Unanswered' else choice == 'Yes'
    if isinstance(value, (int, float)):
        return st.number_input(label, value=value, key=key, persist_state='session')
    if isinstance(value, (list, dict)):
        raw = st.text_area(label+' (JSON)', json.dumps(value, indent=2, ensure_ascii=False), key=key, persist_state='session')
        try: return json.loads(raw)
        except json.JSONDecodeError:
            st.error('Enter valid JSON.'); return value
    return st.text_area(label, str(value), key=key, height=160, persist_state='session')

def field_choices(record):
    # Both individual leaf values and structural lists are editable (including adding goals).
    fields = O.leaf_fields(record)
    fields['goals'] = record['goals']
    fields['participants'] = record['participants']
    for key in record['services']: fields[f'services.{key}.rows'] = record['services'][key]['rows']
    return dict(sorted(fields.items()))

def binding_controls(document, path, page, key):
    source = P.source_bytes(document); pages = P.inspect_pdf(source)
    selected = next((b for b in document['bindings'].get(path, []) if b['page'] == page), None)
    width, height = pages[page]['width'], pages[page]['height']
    data = P.page_image(source, page, [selected] if selected else [])
    coords = region(image=base64.b64encode(data).decode(), width=width, height=height, page=page, key=key+'_canvas', default=None)
    default = P.view_rectangle(document, page, selected['rect']) if selected else [30., 60., min(550., width-30), 130.]
    if coords and coords.get('page') == page:
        default = coords['rect']
    cols = st.columns(4)
    values = [col.number_input(label, min_value=0., max_value=float(width if index % 2 == 0 else height),
                               value=float(round(default[index], 1)), step=1., key=key+str(index)+'_'+str((coords or {}).get('event', 0)))
              for index, (col, label) in enumerate(zip(cols, ['Left', 'Top', 'Right', 'Bottom']))]
    if st.button('Bind this PDF region to the field', key=key+'_bind'):
        return attempt(P.set_binding, document, path, {'page': page, 'rect': P.view_rectangle(document, page, values, inverse=True)})
    return None

def show_pdf_diff(item, key):
    document = item.get('document')
    if not document:
        st.info('This source is text. The equivalent form diff is available below.'); return
    source = P.source_bytes(document); page_count = len(P.inspect_pdf(source))
    page = st.number_input('PDF page', min_value=1, max_value=page_count, value=1, key=key+'_page') - 1
    delta = P.changes(item['base'], item['candidate'])
    overlays = [b for d in delta for b in document['bindings'].get(P.binding_key(document, d['path']), [])]
    left, right = st.columns(2)
    before = source if item['kind'] == 'import' else P.render_document(document, item['base'], False)[0]
    left.markdown('**Before / source — red marks reviewed regions**')
    left.image(P.page_image(before, page, overlays, 'red'), width='stretch')
    try:
        after, unmapped = P.render_document(document, item['candidate'], False)
        right.markdown('**Proposed — green marks changed regions**')
        right.image(P.page_image(after, page, overlays, 'green'), width='stretch')
        missing = [d['path'] for d in delta if not P.binding_key(document, d['path'])]
        if missing: st.caption(f'{len(missing)} changed fields have no PDF region. Review them in the form diff; approved changes to unbound source fields appear in an addendum.')
        full, _ = P.render_document(document, item['candidate'])
        st.download_button('Download proposed original-layout PDF', full, 'proposed-iep.pdf', 'application/pdf', key=key+'_download')
    except ValueError as exc: right.error(str(exc))

def import_controls(actor):
    st.caption('1. Choose a file → 2. Check the extracted information → 3. Approve the import')
    upload = st.file_uploader('Choose the student’s IEP', type=['pdf', 'txt'], key='import_file',help='PDF or text. Scanned documents may need extra review.')
    with st.expander('Import options (optional)'):
        templates = [{'id': 'custom', 'title': 'Identify during review'}] + O.catalog()
        template = st.selectbox('Known template', templates, format_func=lambda t: t['title'], key='import_template')
        name = st.text_input('Student name, if the document is unclear', key='import_name')
        students = core.list_students()
        target = st.selectbox('Add to', [None] + list(students), format_func=lambda s: 'A new student' if s is None else 'Existing student: '+students[s])
    if st.button('Prepare for review',type='primary', disabled=upload is None):
        info = {}; candidate = core.blank_iep(name)
        with st.spinner('Reading the source and preparing a review draft...'):
            try:
                if upload.name.lower().endswith('.pdf'):
                    pages = P.inspect_pdf(upload.getvalue())
                    info['ocr_used'] = sum(len(p['text'].strip()) for p in pages) < 25 * len(pages)
                text = core.extract_text(upload.name, upload.getvalue())
                info.update(source_text=text, truncated=len(text) > core.MAX_DOC_CHARS)
                candidate = core.import_iep(text, name, template_id=template['id'])
            except Exception as exc: info['error'] = str(exc)
            rid = attempt(R.stage_import, candidate, upload.name, upload.getvalue(), template['id'], actor, info, target)
        if rid:
            st.session_state.pop('active_import',None)
            st.session_state.pop('setup_section',None)
            st.session_state['selected_review'] = rid
            st.session_state['pending_main']='Student workspace'
            selected=target
            if target is None: st.session_state['active_import']=rid
            if selected:
                st.session_state['pending_student']=selected
                st.session_state['pending_tool_'+selected]='Review'
                st.session_state['pending_student_section']='IEP'
            notice('Import ready to review. Check the extracted information before approving.')




def templates_workspace(actor):
    st.subheader('IEP templates')
    st.caption('Browse reference forms by state. Check the source and publication date before starting a plan.')
    items = O.catalog()
    state = st.selectbox('State', ['All']+sorted({t['state'] for t in items}))
    items = [t for t in items if state == 'All' or t['state'] == state]
    item = st.selectbox('Template', items, format_func=lambda t: t['title'])
    st.caption(f"{item['pages']} pages · Form date: {item['form_date']} · {item.get('form_type', '')}")
    st.link_button('Open NASET source PDF', item['url'])
    rows = [{'Concept': c['concept'], 'Record path': c['field'], 'Source pages': ', '.join(str(e['page']) for e in c['evidence']), 'Matched label': c['evidence'][0]['label']} for c in item['crosswalk']]
    with st.expander('Section mappings (for template designers)'):
        st.caption('Candidate mappings need visual confirmation. These reference forms do not establish current state requirements.')
        st.dataframe(rows, hide_index=True, width='stretch')
    cache = store.DATA_DIR / 'reference' / (item['id']+'.pdf')
    if not cache.exists():
        if st.button('Download this reference template'):
            import requests
            response = requests.get(item['url'], timeout=45); response.raise_for_status()
            if P.digest(response.content) != item['sha256']: st.error('Source changed since catalog build; refresh the catalog before using it.')
            else: cache.parent.mkdir(parents=True, exist_ok=True); cache.write_bytes(response.content); st.rerun()
    else:
        data = cache.read_bytes()
        page = st.number_input('Template preview page', 1, item['pages'], 1, key=item['id'])-1
        st.image(P.page_image(data, page, scale=1), width='stretch')
        with st.expander('Design reusable PDF field locations'):
            design = store.get('template_design', item['id'], {'template_id': item['id'], 'fields': []})
            blank = S.normalize(S.empty_iep())
            blank['extensions'] = {f['key']: '' for f in design['fields']}
            path = st.selectbox('Template field to position', list(field_choices(blank)), key='template_position_field')
            document = P.archive_source(data, blank, item['id']+'.pdf', item['id'], 'reference template')
            mapped = binding_controls(document, path, page, 'template_binding_'+item['id']+path+str(page))
            if mapped:
                design.update(bindings=mapped['bindings'], source_sha256=mapped['sha256'])
                store.put('template_design', item['id'], design); notice('Reusable template location saved. It will be applied to new drafts on this exact PDF version.')
            st.download_button('Download reusable template design', json.dumps(design, indent=2), item['id']+'.design.json', 'application/json')
        with st.expander('Start an IEP on this original template'):
            name = st.text_input('New student name')
            st.caption('Some references contain sample content. Select a blank form and inspect every page before confirmation.')
            if st.button('Create template review draft', disabled=not name.strip()):
                candidate = core.blank_iep(name.strip())
                design = store.get('template_design', item['id'], {'fields': []})
                candidate['extensions'] = {f['key']: {'string': '', 'number': 0, 'boolean': None}[f['type']] for f in design['fields']}
                rid = R.stage_import(candidate, item['id']+'.pdf', data, item['id'], actor, {'template_draft': True})
                st.session_state['selected_review']=rid
                st.session_state['pending_main']='Student workspace'
                st.session_state['active_import']=rid
                st.session_state.pop('setup_section',None)
                notice('Template draft ready. Complete the information and check the PDF before approval.')
    with st.expander('Design template-specific schema fields'):
        design = store.get('template_design', item['id'], {'template_id': item['id'], 'fields': []})
        st.json(design)
        key = st.text_input('New field key', key='design_key')
        label = st.text_input('Display label', key='design_label')
        concept = st.selectbox('Ontology concept', list(O.CLASSES), index=list(O.CLASSES).index('Assertion'))
        kind = st.selectbox('Value type', ['string', 'number', 'boolean'])
        if st.button('Save field definition'):
            import re
            if not re.fullmatch('[a-zA-Z][a-zA-Z0-9_]{0,63}', key) or not label.strip(): st.error('Enter a valid key and label.')
            else:
                design['fields'] = [f for f in design['fields'] if f['key'] != key] + [{'key': key, 'label': label, 'concept': concept, 'type': kind}]
                store.put('template_design', item['id'], design); notice('Template field definition saved.')
        schema = O.template_schema(item['id'])
        st.download_button('Download template JSON Schema', json.dumps(schema, indent=2), item['id']+'.schema.json', 'application/json')
        st.download_button('Download source crosswalk', json.dumps(item, indent=2), item['id']+'.crosswalk.json', 'application/json')
    with st.expander('Upper ontology and IEP specialization'):
        st.dataframe([{'Class': c, 'Parent class': parent or '(root)'} for c, parent in O.CLASSES.items()], hide_index=True, width='stretch')
        st.download_button('Download OWL/Turtle ontology', O.turtle(), 'iep-upper-ontology.ttl', 'text/turtle')
        st.download_button('Download canonical graph schema', json.dumps(O.graph_schema(), indent=2), 'canonical.schema.json', 'application/json')

def export_current(sid, record):
    document = P.student_document(sid)
    if document: return P.render_document(document, record)[0]
    import export_pdf
    return export_pdf.build_pdf(record)




def acrobat_workspace(*args, **kwargs):
    from workspace_design import acrobat_workspace as render
    return render(*args, **kwargs)


def review_inbox(*args, **kwargs):
    from workspace_design import review_inbox as render
    return render(*args, **kwargs)


def resources_workspace(*args, **kwargs):
    from workspace_design import resources_workspace as render
    return render(*args, **kwargs)
