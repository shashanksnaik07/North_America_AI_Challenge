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
        choice = st.selectbox(label, ['Unanswered', 'Yes', 'No'], index=0 if value is None else 1 if value else 2, key=key)
        return None if choice == 'Unanswered' else choice == 'Yes'
    if isinstance(value, (list, dict, int, float)):
        raw = st.text_area(label+' (JSON)', json.dumps(value, indent=2, ensure_ascii=False), key=key)
        try: return json.loads(raw)
        except json.JSONDecodeError:
            st.error('Enter valid JSON.'); return value
    return st.text_area(label, str(value), key=key)

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
    templates = [{'id': 'custom', 'title': 'Custom / identify during review'}] + O.catalog()
    template = st.selectbox('Source template', templates, format_func=lambda t: t['title'], key='import_template')
    upload = st.file_uploader('IEP (PDF or TXT)', type=['pdf', 'txt'], key='import_file')
    name = st.text_input('Student name override', key='import_name')
    students = core.list_students()
    target = st.selectbox('Import destination', [None] + list(students), format_func=lambda s: 'New student (requires confirmation)' if s is None else 'Replace after review: '+students[s])
    if st.button('Extract into review inbox', disabled=upload is None):
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
            st.session_state['selected_review'] = rid
            notice('Import staged. Open Review inbox to inspect, correct, escalate or confirm it. No student record was changed.')

def review_inbox(actor, role, sid=None, compact=False, include_imports=False):
    st.subheader('Review inbox')
    st.caption('Red: current · Green: proposed. Drafts require confirmation. Reviewer roles are self-selected in this demo.' if compact else 'Imports and changes are saved as drafts. Red = removed/current; green = added/proposed. Reviewer identities and roles are self-selected in this local demo.')
    include_closed = st.checkbox('Include resolved reviews', key=f'closed_{sid}')
    items = R.list_reviews(None if include_imports else sid, open_only=not include_closed)
    if include_imports: items = [r for r in items if r.get('student_id') in (None, sid)]
    if not items: st.info('No reviews in this view.'); return
    ids = [r['id'] for r in items]
    preferred = st.session_state.get('selected_review')
    rid = st.selectbox('Review', ids, index=ids.index(preferred) if preferred in ids else 0,
                       format_func=lambda r: next(f"{i['status'].upper()} · {i['title']}" for i in items if i['id'] == r), key=f'review_{sid}')
    item = R.get(rid); rev = str(item['revision']); key = rid+rev
    st.write(f"Required reviewer: **{item['required_role']}** · Assigned to: **{item['assignee'] or 'Unassigned'}**")
    for finding in item['findings']: st.warning(finding)
    if item.get('evidence'):
        with st.expander('Evidence supplied to this proposal'):
            st.json(item['evidence'])
    if compact:
        form_tab = st.container()
    else:
        pdf_tab, form_tab = st.tabs(['Original PDF review', 'Equivalent form diff'])
        with pdf_tab: attempt(show_pdf_diff, item, key)
    with form_tab:
        delta = P.changes(item['base'], item['candidate'])
        frame = pd.DataFrame([{'Field': d['path'], 'Before (red)': O.text(d['before']), 'Proposed (green)': O.text(d['after'])} for d in delta])
        if not frame.empty and not compact:
            st.dataframe(frame.style.set_properties(subset=['Before (red)'], **{'background-color': '#fee2e2', 'color': '#991b1b'}).set_properties(subset=['Proposed (green)'], **{'background-color': '#dcfce7', 'color': '#166534'}), hide_index=True, width='stretch')
        if delta:
            selected = st.selectbox('Inspect field difference', delta, format_func=lambda d: d['path'], key=key+'_diff')
            st.session_state['review_active_field'] = selected['path']
            st.markdown(R.diff_html(selected['before'], selected['after']), unsafe_allow_html=True)
        st.caption(f'{len(delta)} changed fields. Review the original page in the document canvas.')
        if item.get('source_text'):
            with st.expander('Extracted source text'): st.text(item['source_text'])
    if item['status'] in R.OPEN:
        with st.expander('Correct extracted data or proposed wording'):
            fields = field_choices(item['candidate'])
            field = st.selectbox('Field to correct', list(fields), key=key+'_field')
            value = typed_value('Proposed value', fields[field], key+field)
            if st.button('Save review correction', key=key+'_correct'):
                candidate = copy.deepcopy(item['candidate']); S.set_path(candidate, field, value)
                try:
                    R.update_candidate(rid, candidate, actor, item['revision']); notice('Review correction saved; confirmation applies to the updated draft.')
                except Exception as exc: st.error(str(exc))
            with st.expander('Advanced complete structured record'):
                raw = st.text_area('Draft JSON', json.dumps(item['candidate'], indent=2, ensure_ascii=False), height=300, key=key+'_json')
                if st.button('Validate and save structured draft', key=key+'_savejson'):
                    try: R.update_candidate(rid, json.loads(raw), actor, item['revision']); notice('Structured draft saved.')
                    except Exception as exc: st.error(str(exc))
        if item.get('document'):
            with st.expander('Map a form field onto the original PDF'):
                field = st.selectbox('Field for PDF binding', list(field_choices(item['candidate'])), key=key+'_bindfield')
                page_count = len(P.inspect_pdf(P.source_bytes(item['document'])))
                page = st.number_input('Page to bind', 1, page_count, 1, key=key+'_bindpage')-1
                mapped = binding_controls(item['document'], field, page, key+'_mapping_'+field+str(page))
                if mapped:
                    R.update_candidate(rid, item['candidate'], actor, item['revision'], mapped); notice('PDF field binding saved.')
        st.divider()
        confirmed = st.checkbox('I reviewed the original source, red/green differences, findings, and any unmapped addendum fields.', key=key+'_confirm')
        note = st.text_input('Review decision note', key=key+'_note')
        a, b = st.columns(2)
        if a.button('Confirm import' if item['kind'] == 'import' else 'Approve changes', type='primary', disabled=not confirmed or not actor.strip(), key=key+'_approve'):
            try:
                student = R.decide(rid, 'approved', actor, role, confirmed, note, item['revision'])
                if student: st.session_state['pending_student'] = student
                notice('Review approved and recorded.')
            except Exception as exc: st.error(str(exc))
        if b.button('Reject draft', disabled=not actor.strip(), key=key+'_reject'):
            try: R.decide(rid, 'rejected', actor, role, note=note, revision=item['revision']); notice('Draft rejected. The active IEP is unchanged.')
            except Exception as exc: st.error(str(exc))
        with st.expander('Escalate to another reviewer'):
            assignee = st.text_input('Assign to', key=key+'_assignee')
            required = st.selectbox('Required role', R.ROLES, index=1, key=key+'_role')
            reason = st.text_area('Escalation reason', key=key+'_reason')
            if st.button('Escalate review', key=key+'_escalate'):
                try: R.escalate(rid, actor, reason, assignee, required); notice('Escalated in the local inbox. No email or external message was sent.')
                except Exception as exc: st.error(str(exc))
    with st.expander('Review activity'): st.dataframe(item['events'], hide_index=True, width='stretch')
    return item


def connected_courses(sid, actor):
    st.subheader('Connected courses & reports')
    st.info('Synthetic local integrations. SIS vendor names identify demo profiles; they are not live vendor connections. Teacher reports are app-owned, not an LTI service.')
    provider = st.selectbox('Mock SIS', list(I.PROVIDERS), format_func=I.PROVIDERS.get, key='provider_'+sid)
    if st.button('Sync SIS roster', key='sis_sync_'+sid):
        result = attempt(I.sync_sis, provider)
        if result: st.success('Roster synchronized using paginated OneRoster-shaped REST responses.')
    snapshot = store.get('sis', provider)
    if snapshot:
        st.caption('Last successful sync: '+snapshot['synced_at'])
        students = [u for u in snapshot['users'] if u['role'] == 'student' and u['status'] == 'active']
        chosen = st.selectbox('Match local student to SIS identity', students, format_func=lambda u: f"{u['givenName']} {u['familyName']} · {u['sourcedId']}", key='sis_match_'+sid)
        if st.button('Confirm student identity link', key='sis_link_'+sid):
            try: I.link_student(sid, provider, chosen['sourcedId']); notice('SIS identity linked. The IEP itself was not overwritten.')
            except Exception as exc: st.error(str(exc))
        with st.expander('Inspect standards payloads'): st.json(snapshot)
    context = I.student_context(sid)
    if not context: st.info('Sync a roster and explicitly link a student to fetch course evidence.'); return
    st.write(f"Linked: **{context['user']['givenName']} {context['user']['familyName']}** · {context['link']['sourced_id']}")
    if st.button('Propose SIS demographics update', key='sis_demo_'+sid):
        candidate = core.get_iep(sid); candidate['grade'] = next(iter(context['user'].get('grades', [])), candidate['grade'])
        schools = {o['sourcedId']: o['name'] for o in context['orgs']}
        if context['classes']: candidate['meta']['school'] = schools.get(context['classes'][0]['school']['sourcedId'], '')
        if attempt(R.stage_change, sid, candidate, 'SIS demographics sync', actor, evidence=[context]): notice('SIS changes submitted for review.')
    if not context['classes']: st.info('No current classes in the linked roster.'); return
    course = st.selectbox('Course', context['classes'], format_func=lambda c: c['title'], key='course_'+sid)
    if st.button('Simulate LTI launch and fetch course context', key='lti_sync_'+sid):
        records = attempt(I.sync_lms, sid, course['sourcedId'])
        if records is not None: st.success(f'Validated signed LTI launch; fetched roster membership and {len(records)} permitted grade result(s).')
    st.caption('LTI 1.3 supplies launch/course context. NRPS supplies course membership. AGS supplies results exposed to this tool deployment; general course pages, discussion posts and all LMS grades are not provided by these services.')
    with st.expander('Submit a course accommodation report', expanded=True):
        with st.form('course_report_'+sid):
            reporter = st.text_input('Report author', value=actor)
            accommodation = st.text_input('Accommodation used')
            usage = st.selectbox('Usage', ['Every opportunity', 'Most opportunities', 'Sometimes', 'Not used'])
            effectiveness = st.selectbox('Observed effectiveness', ['Helpful', 'Mixed', 'Not helpful', 'Insufficient evidence'])
            a, b = st.columns(2)
            today = dt.date.today()
            start = a.date_input('Period start', value=today.replace(day=1)); end = b.date_input('Period end', value=today)
            observation = st.text_area('Observations and supporting examples')
            if st.form_submit_button('Save course report'):
                if attempt(I.submit_report, sid, course['sourcedId'], reporter, accommodation, usage, effectiveness, observation, start, end): notice('Course report saved and available as suggestion context.')
    aggregation = I.aggregate_reports(sid)
    if aggregation:
        st.markdown('**Across-course accommodation observations**')
        st.dataframe(aggregation, hide_index=True, width='stretch')
    items = I.evidence(sid)
    if items:
        st.markdown('**Evidence available to IEP suggestions**')
        st.dataframe(pd.DataFrame(items), hide_index=True, width='stretch')
        st.download_button('Export evidence with provenance', json.dumps(items, indent=2), 'course-evidence.json', 'application/json')
    st.caption('Use Document → Suggest updates to draft changes. The proposal records exactly which evidence was supplied, including course, source and fetch/report dates.')

def templates_workspace(actor):
    st.subheader('IEP templates & shared ontology')
    st.caption('NASET reference forms retain their published dates. Candidate crosswalks locate shared concepts; they are not determinations of current state requirements.')
    items = O.catalog()
    state = st.selectbox('State', ['All']+sorted({t['state'] for t in items}))
    items = [t for t in items if state == 'All' or t['state'] == state]
    item = st.selectbox('Template', items, format_func=lambda t: t['title'])
    st.write(f"{item['pages']} pages · Form date: {item['form_date']} · {item.get('form_type', '')} · {item['crosswalk_status']}")
    st.link_button('Open NASET source PDF', item['url'])
    rows = [{'Concept': c['concept'], 'Record path': c['field'], 'Source pages': ', '.join(str(e['page']) for e in c['evidence']), 'Matched label': c['evidence'][0]['label']} for c in item['crosswalk']]
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
                st.session_state['selected_review'] = rid; notice('Template draft created in Review inbox. Fill the record and bind its fields before confirmation.')
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

def edit_side_panel(sid, record, actor):
    fields = field_choices(record)
    field = st.selectbox('Edit a field', list(fields), index=list(fields).index('student_name'), format_func=S.label_for, key='editor_field_'+sid)
    value = typed_value('Proposed wording / value', fields[field], f'edit_{sid}_{field}_{R.fingerprint(record)[:8]}')
    if st.button('Submit PDF edit for review', type='primary', key='submit_pdf_'+sid):
        candidate = copy.deepcopy(record); S.set_path(candidate, field, value)
        rid = attempt(R.stage_change, sid, candidate, 'PDF edit: '+S.label_for(field), actor)
        if rid:
            st.session_state['selected_review'] = rid; st.session_state['pending_tool_'+sid] = 'Review'
            notice('Edit submitted. Compare the source and proposal before confirming.')
    document = P.ensure_document(sid, record)
    selected = st.session_state.get('selected_region_'+sid)
    if selected:
        st.caption('Selected page region: '+', '.join(f'{v:.1f}' for v in selected['rect']))
        if st.button('Use selected region for this field', key='bind_selected_'+sid):
            mapped = attempt(P.set_binding, document, field, {'page': selected['page'], 'rect': P.view_rectangle(document, selected['page'], selected['rect'], inverse=True)})
            if mapped:
                rid = attempt(R.stage_change, sid, record, 'Position PDF field: '+S.label_for(field), actor, document=mapped)
                if rid:
                    st.session_state['selected_review']=rid; st.session_state['pending_tool_'+sid]='Review'; notice('PDF position submitted for confirmation.')
    with st.expander('Exact field coordinates'):
        count=len(P.inspect_pdf(P.source_bytes(document)))
        pi=st.number_input('Binding page', 1, count, 1, key='exact_page_'+sid)-1
        old=next((b['rect'] for b in document['bindings'].get(field,[]) if b['page']==pi),[30.,60.,300.,120.])
        coords=[st.number_input(label,value=float(old[i]),step=1.,key=f'exact_{sid}_{field}_{pi}_{i}') for i,label in enumerate(['Left','Top','Right','Bottom'])]
        if st.button('Submit coordinate binding',key='exact_submit_'+sid):
            mapped=attempt(P.set_binding,document,field,{'page':pi,'rect':coords})
            if mapped and attempt(R.stage_change,sid,record,'PDF field location: '+field,actor,document=mapped): notice('Coordinate binding submitted for review.')
    with st.expander('Attach original PDF'):
        upload=st.file_uploader('Original PDF',type=['pdf'],key='attach_'+sid)
        if st.button('Submit original PDF',disabled=upload is None,key='attach_submit_'+sid):
            mapped=attempt(P.archive_source,upload.getvalue(),record,upload.name)
            if mapped and attempt(R.stage_change,sid,record,'Attach original PDF',actor,document=mapped): notice('Source attachment submitted for review.')
    with st.expander('Template-specific field'):
        key=st.text_input('New field key',key='extension_key_'+sid)
        value=st.text_area('New field value',key='extension_value_'+sid)
        if st.button('Propose template field',key='extension_add_'+sid):
            import re
            if not re.fullmatch('[a-zA-Z][a-zA-Z0-9_]{0,63}',key): st.error('Use letters, digits and underscores; begin with a letter.')
            else:
                candidate=copy.deepcopy(record);candidate.setdefault('extensions',{})[key]=value
                if attempt(R.stage_change,sid,candidate,'Template field: '+key,actor): notice('Template field submitted for review.')
    return field

def acrobat_workspace(sid, record, actor, role):
    import document_tools as tools
    if st.session_state.get('pending_tool_'+sid): st.session_state['tool_'+sid]=st.session_state.pop('pending_tool_'+sid)
    if st.session_state.get('pending_field_'+sid): st.session_state['editor_field_'+sid]=st.session_state.pop('pending_field_'+sid)
    toolbar=st.columns([1,1,1.3,2])
    thumbnails=toolbar[0].checkbox('Pages',value=False,key='show_pages_'+sid)
    show_tools=toolbar[1].checkbox('Tools panel',value=True,key='show_tools_'+sid)
    view=toolbar[2].selectbox('Document view',['PDF','Equivalent form'],label_visibility='collapsed',key='document_view_'+sid)
    toolbar[3].caption('Changes stay in review until confirmed.')
    widths=([.55] if thumbnails else [])+[3.2]+([1.65] if show_tools else [])
    columns=st.columns(widths,gap='small')
    rail=columns[0] if thumbnails else None
    canvas=columns[1 if thumbnails else 0]
    pane=columns[-1] if show_tools else None
    item=None;field=None; tool='Read'
    if pane is not None:
        with pane:
            tool=st.selectbox('Document tool',['Edit','Ask','Suggest updates','Accommodations','History','Summary','Review'],key='tool_'+sid)
            with st.container(height=760,border=True):
                if tool=='Edit': field=edit_side_panel(sid,record,actor)
                elif tool=='Review': item=review_inbox(actor,role,sid,compact=True,include_imports=True)
                else:
                    renderer={'Ask':tools.ask,'Suggest updates':tools.updates,'Accommodations':tools.accommodations,'History':tools.history,'Summary':tools.summary}[tool]
                    renderer(sid,actor)
    document=(item or {}).get('document') or P.ensure_document(sid,record)
    if tool=='Review' and item and not item.get('document'):
        with canvas:
            st.info('This import has a text or unreadable source. Use the equivalent form differences and original text to review it.')
            st.text(item.get('source_text','No extractable source text.'))
        return
    if view=='Equivalent form':
        with canvas:
            if tool=='Review' and item:
                st.markdown('**Equivalent form — before and proposed**')
                for d in P.changes(item['base'],item['candidate']):
                    st.markdown('**'+S.label_for(d['path'])+'**')
                    st.markdown(R.diff_html(d['before'],d['after']),unsafe_allow_html=True)
            else: tools.form(sid,actor)
        return
    source=P.source_bytes(document);pages=P.inspect_pdf(source)
    scope=sid+document['sha256'][:8]
    page_key='canvas_page_'+scope
    if 'pending_page_'+sid in st.session_state: st.session_state[page_key]=st.session_state.pop('pending_page_'+sid)
    with canvas:
        bar=st.columns([1,1.3,1.5])
        page=bar[0].number_input('Page',1,len(pages),1,key=page_key)-1
        zoom=bar[1].selectbox('Zoom',[75,100,125,150,200],index=1,format_func=lambda x:f'{x}%',key='zoom_'+sid)
        mode=bar[2].selectbox('PDF tool',['Select field','Map region','Read'],key='pdf_mode_'+sid) if tool=='Edit' else 'Read'
        overlays=[]; color='green'
        if item:
            version=st.radio('Compare',['Proposed (green)','Before / source (red)'],horizontal=True,key='compare_'+item['id'])
            delta=P.changes(item['base'],item['candidate'])
            overlays=[b for d in delta for b in document['bindings'].get(P.binding_key(document,d['path']),[])]
            if version.startswith('Before'):
                current=source if item['kind']=='import' else P.render_document(document,item['base'],False)[0];color='red'
            else:
                try: current=P.render_document(document,item['candidate'],False)[0]
                except ValueError as exc: st.error(str(exc));current=source
            st.caption(item['title'])
            unbound=[d for d in delta if not P.binding_key(document,d['path'])]
            if unbound: st.warning(f'{len(unbound)} changed fields are unbound. Inspect them in the equivalent form; exported source changes are included in an addendum.')
        else:
            try: current=P.render_document(document,record)[0]
            except ValueError as exc: st.error(str(exc));current=source
            st.caption(document['filename']+' · '+document['origin'])
        show_fields=st.checkbox('Show editable field locations',value=tool=='Edit',key='show_fields_'+sid+tool)
        fields=[{'path':path,'rect':P.view_rectangle(document,page,b['rect'])} for path,bindings in document['bindings'].items() for b in bindings if b['page']==page]
        png=P.page_image(current,page,overlays,color,scale=1.5)
        selection=st.session_state.get('selected_region_'+sid)
        result=region(image=base64.b64encode(png).decode(),width=pages[page]['width'],height=pages[page]['height'],page=page,
                      fields=fields,show_fields=show_fields,active_field=field,zoom=zoom,viewport_height=720,
                      selection=selection['rect'] if selection and selection['page']==page and tool=='Edit' else None,
                      mode={'Select field':'select','Map region':'map','Read':'read'}[mode],key='document_canvas_'+scope,default=None)
        if result and result['event']!=st.session_state.get('handled_canvas_event_'+sid):
            st.session_state['handled_canvas_event_'+sid]=result['event']
            if result.get('field'):
                if result['field'] in field_choices(record):
                    st.session_state['pending_field_'+sid]=result['field'];st.session_state['pending_tool_'+sid]='Edit';st.rerun()
            elif result.get('rect'):
                st.session_state['selected_region_'+sid]=result;st.rerun()
        downloads=st.columns(2)
        downloads[0].download_button('Original PDF',source,document['filename'],'application/pdf',key='canvas_source_'+scope)
        try:
            export=P.render_document(document,item['candidate'] if item else record)[0]
            downloads[1].download_button('Proposed PDF' if item else 'Current PDF',export,'iep-proposed.pdf' if item else 'iep.pdf','application/pdf',key='canvas_export_'+scope)
        except ValueError: downloads[1].caption('Resolve the PDF layout issue before export.')
    if rail is not None:
        with rail:
            st.caption('Pages')
            with st.container(height=820):
                for pi in range(len(pages)):
                    st.image(P.page_image(source,pi,scale=.2),width='stretch')
                    if st.button(str(pi+1),key=f'thumb_{scope}_{pi}',width='stretch'):
                        st.session_state['pending_page_'+sid]=pi+1;st.rerun()
