"""Durable draft -> human review -> approval/rejection with stale-data protection."""
import copy
import hashlib
import json
import uuid
import jsonschema
import iep_schema as S
import local_store as store
import ontology
import pdf_workspace as pdf
import workspace_state as W
from draft_merge import combine, evidence_union

OPEN = {'pending', 'escalated'}
ROLES = ['Case manager', 'Specialist', 'Administrator']

def fingerprint(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def get(review_id):
    item = store.get('review', review_id)
    if not item: raise ValueError('Review no longer exists.')
    return item

def list_reviews(sid=None, open_only=False):
    return sorted([r for r in store.all_records('review') if (sid is None or r.get('student_id') == sid)
                   and (not open_only or r['status'] in OPEN)], key=lambda r: r['created'], reverse=True)

def _event(item, action, actor, detail=''):
    item['events'].append({'at': store.now(), 'action': action, 'actor': actor or 'Unspecified', 'detail': detail})

def findings(candidate, import_info=None):
    result = []
    for path in ['student_name', 'dob', 'grade', 'iep_from', 'iep_to', 'profile.needs']:
        if not S.get_path(candidate, path): result.append(f'Missing or empty: {path}')
    if not candidate['goals']: result.append('No annual goals extracted.')
    if import_info:
        if import_info.get('ocr_used'): result.append('OCR was used. Verify names, numbers, dates and checkboxes against the scan.')
        if import_info.get('truncated'): result.append('The model input was truncated; review the remaining source pages manually.')
        if import_info.get('error'): result.append('Extraction failed: ' + import_info['error'])
    return result

@W.guarded
def stage_import(candidate, filename, data, template_id, actor, import_info=None, target_sid=None):
    import core
    if target_sid and list_reviews(target_sid,open_only=True):
        raise ValueError('This student already has a working draft. Review or reject it before importing another IEP.')
    candidate = S.normalize(candidate)
    baseline = core.get_iep(target_sid) if target_sid else S.normalize(S.empty_iep())
    info = import_info or {}
    document = None
    if filename.lower().endswith('.pdf'):
        try: document = pdf.archive_source(data, candidate, filename, template_id)
        except Exception as exc:
            info = {**info, 'error': f"{info.get('error', '')} Original PDF cannot be rendered: {exc}"}
    if document and info.get('template_draft'):
        # A blank template has no candidate values yet; render those as edits.
        document['baseline'] = S.normalize(S.empty_iep())
    attachment = store.DATA_DIR / 'originals' / (pdf.digest(data) + ('.pdf' if filename.lower().endswith('.pdf') else '.txt'))
    attachment.parent.mkdir(parents=True, exist_ok=True)
    if not attachment.exists(): attachment.write_bytes(data)
    item = {'id': uuid.uuid4().hex, 'kind': 'import', 'student_id': target_sid, 'title': f'Import: {filename}',
            'created': store.now(), 'base': baseline, 'base_hash': fingerprint(baseline), 'candidate': candidate,
            'document': document, 'template_id': template_id, 'source_text': info.get('source_text', ''),
            'findings': findings(candidate, info), 'status': 'pending', 'required_role': 'Case manager',
            'assignee': '', 'events': [], 'revision': 1, 'evidence': [], 'import_info': info,
            'source_attachment': str(attachment.relative_to(store.DATA_DIR))}
    if target_sid: item['document_hash'] = fingerprint(pdf.student_document(target_sid))
    if item['findings']: item.update(status='escalated', required_role='Specialist')
    _event(item, 'submitted', actor)
    store.put('review', item['id'], item)
    return item['id']

@W.guarded
def stage_change(sid, candidate, title, actor='', evidence=(), document=None, expected_base_hash=None, expected_draft_revision=None):
    import core
    base = core.get_iep(sid); candidate = S.normalize(candidate)
    if expected_base_hash and fingerprint(base) != expected_base_hash:
        raise ValueError('The IEP changed while this draft was being prepared. Reload and try again.')
    existing=working_draft(sid)
    if existing and existing['kind']=='import': raise ValueError('Review the pending import before editing this IEP.')
    if expected_draft_revision is not None and expected_draft_revision != (existing['revision'] if existing else 0):
        raise ValueError('Another session changed the working draft. Reload it before saving your edits.')
    if existing:
        if existing.get('merge_conflicts'): raise ValueError('Resolve the conflicting changes in Review draft before adding more edits.')
        if expected_draft_revision is None:
            conflicts=[]
            candidate=combine(base,existing['candidate'],candidate,conflicts,source=title)
            if conflicts:
                names=', '.join(S.label_for(c['path']) for c in conflicts)
                raise ValueError('The working draft already has different wording for '+names+'. Use Edit draft to revise it.')
        layout=copy.deepcopy(document or existing.get('layout_document') or existing['document'])
        if candidate==existing['candidate'] and (document is None or document==existing['document']):
            raise ValueError('These changes are already saved in the working draft.')
        _prepare(existing,candidate,layout)
        existing['title']='Working IEP draft'
        existing['evidence']=evidence_union(existing.get('evidence',[]),evidence)
        existing['revision']+=1
        _event(existing,'draft edited',actor,title)
        store.put('review',existing['id'],existing)
        return existing['id']
    if base == candidate and document is None: raise ValueError('There are no changes to review.')
    source=copy.deepcopy(pdf.ensure_document(sid,base))
    layout=copy.deepcopy(document or source)
    item = {'id': uuid.uuid4().hex, 'kind': 'change', 'student_id': sid, 'title': title,
            'created': store.now(), 'base': base, 'base_hash': fingerprint(base), 'candidate': candidate,
            'base_document':source,
            'document_hash': fingerprint(pdf.student_document(sid)), 'findings': [],
            'status': 'pending', 'required_role': 'Case manager', 'assignee': '', 'events': [],
            'revision': 1, 'evidence': copy.deepcopy(list(evidence))}
    _prepare(item,candidate,layout)
    _event(item, 'submitted', actor)
    store.put('review', item['id'], item)
    return item['id']


def _prepare(item,candidate,layout):
    jsonschema.validate(candidate,ontology.template_schema(layout.get('template_id','custom')))
    prepared=pdf.prepare_draft_document(layout,item['base'],candidate)
    pdf.render_document(prepared,candidate)
    item.update(candidate=copy.deepcopy(candidate),layout_document=copy.deepcopy(layout),document=prepared)


@W.guarded
def working_draft(sid):
    """Consolidate legacy proposals and rebase safely before presenting a review."""
    import core
    items=list_reviews(sid,open_only=True)
    if not items: return None
    imports=[item for item in items if item['kind']=='import']
    if imports: return imports[0]  # New imports and changes are mutually exclusive.
    base=core.get_iep(sid); source=pdf.ensure_document(sid,base)
    items.sort(key=lambda item:(item['created'],item['id']))
    if len(items)==1 and items[0]['base_hash']==fingerprint(base) and items[0].get('document_hash')==fingerprint(source):
        return items[0]
    keeper=copy.deepcopy(items[0]);candidate=copy.deepcopy(base);layout=copy.deepcopy(source);conflicts=[]
    evidence=[];findings=[]
    for item in items:
        candidate=combine(item['base'],candidate,item['candidate'],conflicts,source=item['title'])
        conflicts.extend(copy.deepcopy(item.get('merge_conflicts',[])))
        incoming=item.get('layout_document') or item['document']
        old_source=item.get('base_document')
        if old_source is None:
            old_source=source if item.get('document_hash')==fingerprint(source) else next(
                (v.get('document') for v in core.list_versions(sid) if fingerprint(v.get('document'))==item.get('document_hash')),None)
        if incoming!=layout and incoming!=old_source:
            if layout==old_source: layout=copy.deepcopy(incoming)
            else: conflicts.append({'id':uuid.uuid4().hex,'path':'@document','current':copy.deepcopy(layout),
                                    'proposed':copy.deepcopy(incoming),'source':item['title']})
        evidence=evidence_union(evidence,item.get('evidence',[]))
        findings.extend(item.get('findings',[]))
    keeper.update(base=base,base_hash=fingerprint(base),base_document=source,document_hash=fingerprint(source),
                  title='Working IEP draft',merge_conflicts=conflicts,evidence=evidence,findings=list(dict.fromkeys(findings)),
                  revision=keeper['revision']+1)
    escalated=[item for item in items if item['status']=='escalated']
    if escalated:
        assignees={item['assignee'] for item in escalated if item['assignee']}
        required=max((item['required_role'] for item in escalated),key=ROLES.index)
        if len(assignees)>1:
            required='Administrator';keeper['findings'].append('Earlier drafts had different assigned reviewers. Administrator review is required.')
        keeper.update(status='escalated',required_role=required,assignee=next(iter(assignees)) if len(assignees)==1 else '')
    _prepare(keeper,candidate,layout)
    _event(keeper,'draft consolidated','System','Earlier proposals carried forward against the current IEP. Review all changes again.')
    with store.transaction() as db:
        for item in items:
            store.put('review_archive',f"single-draft-{item['id']}-{item['revision']}",item,db)
            if item['id']!=keeper['id']:
                item.update(status='superseded',superseded_by=keeper['id'],revision=item['revision']+1,resolved=store.now())
                _event(item,'combined into draft','System',keeper['id']);store.put('review',item['id'],item,db)
        store.put('review',keeper['id'],keeper,db)
    return keeper


@W.guarded
def resolve_conflict(review_id,conflict_id,use_proposed,actor,revision):
    item=get(review_id);_editable(item,revision)
    conflict=next((c for c in item.get('merge_conflicts',[]) if c['id']==conflict_id),None)
    if conflict is None: raise ValueError('This conflict has already been resolved. Reload the draft.')
    candidate=copy.deepcopy(item['candidate']);layout=item.get('layout_document') or item['document']
    if use_proposed:
        if conflict['path']=='@document': layout=conflict['proposed']
        else: S.set_path(candidate,conflict['path'],copy.deepcopy(conflict['proposed']))
    _prepare(item,candidate,layout)
    item['merge_conflicts']=[c for c in item['merge_conflicts'] if c['id']!=conflict_id]
    item['revision']+=1
    _event(item,'conflict resolved',actor,('Used alternative: ' if use_proposed else 'Kept working draft: ')+conflict['path'])
    store.put('review',review_id,item)

def update_candidate(review_id, candidate, actor, revision, document=None):
    with store.transaction() as db:
        item = store.get('review', review_id, con=db)
        _editable(item, revision)
        if item.get('merge_conflicts'): raise ValueError('Resolve the conflicting changes before editing this draft.')
        # Fetch the design on the same connection: SQLite uses a single writer.
        template_id = (document or item.get('document') or {}).get('template_id', item.get('template_id', 'custom'))
        schema = ontology.template_schema(template_id, db)
        jsonschema.validate(candidate, schema)
        if item['kind']=='change':
            layout=document or item.get('layout_document') or item['document']
            document=pdf.prepare_draft_document(layout,item['base'],candidate)
            pdf.render_document(document,candidate)
            item['layout_document']=copy.deepcopy(layout)
        item['candidate'] = copy.deepcopy(candidate)
        if document is not None: item['document'] = document
        item['revision'] += 1
        _event(item, 'draft edited', actor)
        store.put('review', review_id, item, db)

def _editable(item, revision):
    if not item or item['status'] not in OPEN: raise ValueError('This review has already been resolved.')
    if item['revision'] != revision: raise ValueError('Another session changed this review. Reload it before continuing.')


def escalate(review_id, actor, reason, assignee, role='Specialist'):
    if not actor.strip() or not reason.strip() or not assignee.strip(): raise ValueError('Enter your name, a reason and an assignee.')
    if role not in ROLES: raise ValueError('Unknown review role.')
    with store.transaction() as db:
        item = store.get('review', review_id, con=db); _editable(item, item['revision'])
        item.update(status='escalated', required_role=role, assignee=assignee.strip(), revision=item['revision'] + 1)
        _event(item, 'escalated', actor, reason)
        store.put('review', review_id, item, db)

def decide(review_id, decision, actor, role, confirmed=False, note='', revision=None, expected_generation=None):
    import core
    if decision not in ('approved', 'rejected'): raise ValueError('Unknown decision.')
    if not actor.strip(): raise ValueError('Enter the reviewer name.')
    if role not in ROLES: raise ValueError('Choose a review role.')
    with store.transaction() as db:
        W.check_generation(expected_generation)
        item = store.get('review', review_id, con=db)
        _editable(item, revision if revision is not None else item['revision'])
        if item['status'] == 'escalated' and role not in (item['required_role'], 'Administrator'):
            raise ValueError(f"Escalated review requires {item['required_role']} or Administrator.")
        if item['assignee'] and actor.strip().casefold() != item['assignee'].casefold() and role != 'Administrator':
            raise ValueError('This review is assigned to another reviewer.')
        if decision == 'approved':
            if not confirmed: raise ValueError('Confirm that you reviewed the source, differences and findings.')
            if item.get('merge_conflicts'): raise ValueError('Resolve every conflicting change before approving this draft.')
            candidate = item['candidate']
            jsonschema.validate(candidate, ontology.template_schema((item.get('document') or {}).get('template_id', item.get('template_id', 'custom')), db))
            if not candidate['student_name'].strip(): raise ValueError('A student name is required before approval.')
            sid = item['student_id']
            if sid and fingerprint(core.get_iep(sid)) != item['base_hash']:
                raise ValueError('The current IEP changed. Reopen Review draft to reconcile it and check the combined changes before approval.')
            if sid and item.get('document_hash') and fingerprint(pdf.student_document(sid)) != item['document_hash']:
                raise ValueError('The source document or PDF bindings changed after this proposal. Create a fresh review.')
            # Validate PDF fit and source integrity before writing any approved record.
            if item['document']: pdf.render_document(item['document'], candidate)
            if sid:
                core.save_iep(sid, candidate, note=f"Reviewed by {actor}: {item['title']}",
                              force_version=item['document'] != pdf.student_document(sid))
            else:
                # Same-name imports are separate students unless an explicit target was chosen.
                sid = S.make_student_id(candidate['student_name']) or 'student'
                if (core.STUDENTS_DIR / sid / 'iep.json').exists(): sid += '-' + item['id'][:8]
                store.atomic_json(core.STUDENTS_DIR / sid / 'iep.json', candidate)
                item['student_id'] = sid
            if item['document']: pdf.save_document(sid, item['document'])
            core.log_decision(sid, {'section': item['title'], 'review_id': review_id, 'suggested_text': note}, 'approved', actor)
        item.update(status=decision, revision=item['revision'] + 1, resolved=store.now())
        _event(item, decision, actor, note)
        store.put('review', review_id, item, db)
    return item.get('student_id')

def diff_tokens(before, after):
    """Word-level changes shared by form and original-document review views."""
    import difflib
    old = (ontology.text(before) if before is not None else '').split()
    new = (ontology.text(after) if after is not None else '').split()
    parts = []
    for kind, a, b, c, d in difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes():
        if kind == 'equal': parts.append({'kind':'equal','text':' '.join(old[a:b])})
        if kind in ('delete', 'replace'): parts.append({'kind':'delete','text':' '.join(old[a:b])})
        if kind in ('insert', 'replace'): parts.append({'kind':'insert','text':' '.join(new[c:d])})
    return parts


def diff_html(before, after):
    """Escaped word-level insertions/deletions, with labels in addition to colors."""
    from html import escape
    parts = []
    for token in diff_tokens(before, after):
        text = escape(token['text'])
        if token['kind'] == 'delete': text = '<del style="background:#fee2e2;color:#991b1b">'+text+'</del>'
        elif token['kind'] == 'insert': text = '<ins style="background:#dcfce7;color:#166534;text-decoration:underline">'+text+'</ins>'
        parts.append(text)
    return '<div style="line-height:1.9;padding:12px;border:1px solid #cbd5e1;border-radius:8px">' + ' '.join(parts) + '</div>'
