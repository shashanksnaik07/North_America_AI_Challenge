"""Candidate freshness, deduplication and a single human review for related edits."""
import copy
import json
import core
import iep_schema as S
import pdf_workspace as P
import reviews as R
import workspace_state as W


@W.guarded
def basis(sid, record=None):
    return {'_student_id':sid, '_base_hash':R.fingerprint(record if record is not None else core.get_iep(sid)),
            '_document_hash':R.fingerprint(P.student_document(sid)), '_generation':W.generation()}


def stamp(items, context):
    return [{**item, **context} for item in items if item]


def identity(item):
    return json.dumps({key:item.get(key) for key in ('action','field','category','suggested_text','payload','_base_hash')},sort_keys=True,ensure_ascii=False)


def merge(existing, incoming):
    # Keep edited candidates and their widget IDs when the same option recurs.
    result=list(existing); seen={identity(item) for item in existing}
    for item in incoming:
        key=identity(item)
        if key not in seen: result.append(item); seen.add(key)
    return result


def validate_basis(sid, item, record):
    W.check_generation(item.get('_generation'))
    if item.get('_student_id',sid)!=sid:
        raise ValueError('This draft belongs to a different student.')
    if item.get('_base_hash') != R.fingerprint(record):
        raise ValueError('The IEP changed after this option was drafted. Draft a fresh option before sending it to review.')
    if '_document_hash' in item and item['_document_hash']!=R.fingerprint(P.student_document(sid)):
        raise ValueError('The source PDF changed after this option was drafted. Draft a fresh option.')


@W.guarded
def submit(sid, items, actor=''):
    if not items: raise ValueError('Choose at least one draft change.')
    base=core.get_iep(sid); candidate=copy.deepcopy(base); used=set(); evidence=[]; fields={}
    for item in items:
        validate_basis(sid,item,base)
        key=identity(item)
        if key in used: continue
        used.add(key)
        text=str(item.get('suggested_text') or '').strip()
        if not text: raise ValueError('Enter proposed wording for every change.')
        if item['action']=='change':
            field=item['field']
            if field in fields and fields[field]!=text:
                raise ValueError('Two options propose different wording for the same field. Keep one before sending all changes.')
            fields[field]=text; S.set_path(candidate,field,text)
        elif item['action']=='add_service':
            row={**S.empty_service(), **item['payload'], 'service':text}
            if not all(str(row[k]).strip() for k in ('frequency','amount','location')):
                raise ValueError('Complete when/how often, amount/duration and course/setting for this service.')
            category=item['category']
            if row not in candidate['services'][category]['rows']:
                candidate['services'][category]['rows'].append(row)
            candidate['services'][category]['needed']=True
        elif item['action']=='add_goal':
            goal={**S.empty_goal(), **item['payload'], 'goal':text}
            if not goal['area'].strip(): raise ValueError('Enter an area for the new goal.')
            if goal not in candidate['goals']: candidate['goals'].append(goal)
        else: raise ValueError('Unknown draft action.')
        evidence.extend(item.get('evidence',[]))
        if item.get('teacher_note'): evidence.append({'source':'teacher note','text':item['teacher_note'], 'omitted_evidence_ids':item.get('omitted_evidence_ids',[])})
    evidence=list({json.dumps(value,sort_keys=True):value for value in evidence}.values())
    title=items[0]['section'] if len(used)==1 else f'Modifications: {len(used)} related changes'
    R.stage_change(sid,candidate,title,actor,evidence=evidence,expected_base_hash=R.fingerprint(base))
    return 'Added to the working IEP draft. Review the combined changes before approval.'
