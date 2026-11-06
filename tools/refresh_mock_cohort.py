"""Replace untouched generated practice packets with populated original templates.

Build and validate every replacement before installing any. Preserve stable student
and review IDs, source files, old versions and a complete migration backup. Never
replace a human-edited record or approve a draft.
"""
import copy
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core
import local_store as store
import mock_cohort as M
import mock_course_data as C
import native_templates as N
import pdf_workspace as P
import reviews as R


def refresh(sources, progress=print):
    cases={c['id']:c for c in M.profiles()}
    templates={t['id']:(i,t) for i,t in enumerate(sources['templates'])}
    owned=[m for m in store.all_records('mock_student') if m.get('generator')==M.VERSION and m.get('complete')]
    stage=store.DATA_DIR/'mock_cohort'/'native-migration'
    stage.mkdir(parents=True,exist_ok=True)
    engine_sha=P.digest(Path(N.__file__).read_bytes()+Path(P.__file__).read_bytes())
    prepared=[];skipped=[];current=[]
    for meta in owned:
        sid=meta['student_id'];old=core.get_iep(sid);doc=P.student_document(sid);review=R.get(meta['review_id'])
        if doc.get('mock_layout_version')==N.LAYOUT_VERSION:
            if review['status']=='pending' and review['base_hash']==R.fingerprint(old) and review['document_hash']!=R.fingerprint(doc):
                raise ValueError('Interrupted refresh or changed document needs inspection: '+sid)
            current.append(sid);continue
        case=cases[meta['case_id']]
        expected=copy.deepcopy(old)
        expected['profile']['needs']+=' Proposed review: '+case['proposal']
        expected['services']['supplementary_aids']['rows'][0]['service']=case['proposal']
        expected['progress_report_weeks']='4'
        generated_events=all((e['action'],e['actor']) in {
            ('submitted','Synthetic dataset generator'),
            ('Synthetic reference margin corrected','Dataset generator')} for e in review['events'])
        if (review['status']!='pending' or review.get('seed_generator')!=M.VERSION
            or review['revision']!=2 or R.fingerprint(old)!=review['base_hash']
            or R.fingerprint(doc)!=review['document_hash'] or review['candidate']!=expected or not generated_events):
            skipped.append(sid);continue
        i,t=templates[meta['template_id']];case=cases[meta['case_id']]
        record,candidate=M.build_record(case,t,i,sources)
        layout=N.layouts()[t['id']]
        layout_sha=P.digest(json.dumps(layout,sort_keys=True).encode())
        cached_path=stage/(sid+'.prepared.json')
        cached=json.loads(cached_path.read_text(encoding='utf-8')) if cached_path.exists() else {}
        if (cached.get('engine_sha256')==engine_sha and cached.get('layout_sha256')==layout_sha and cached.get('record')==record
            and cached.get('candidate')==candidate and cached.get('old_record')==old
            and cached.get('old_document')==doc and cached.get('old_review')==review):
            P.source_bytes(cached['document'])
            prepared.append(cached);continue
        data,bindings,labels,native_pages=M.build_packet(record,candidate,t,(sources['reference_root']/(t['id']+'.pdf')).read_bytes())
        sha=P.digest(data);path=store.DATA_DIR/'originals'/(sha+'.pdf');path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():path.write_bytes(data)
        document={'source':str(path.relative_to(store.DATA_DIR)),'sha256':sha,'filename':sid+'.pdf','template_id':t['id'],
            'origin':'populated NASET template','baseline':record,'bindings':bindings,'page_labels':labels,
            'native_template_pages':native_pages,'reference_sha256':t['sha256'],'mock_layout_version':N.LAYOUT_VERSION,
            'default_page':layout['source_pages'].index(layout['default_source_page'])}
        _,missing=P.render_document(document,candidate)
        if missing:raise ValueError('Unmapped draft: '+sid)
        packet={'sid':sid,'meta':meta,'old_record':old,'old_document':doc,'old_review':review,
                'record':record,'candidate':candidate,'document':document,'layout_sha256':layout_sha,'engine_sha256':engine_sha}
        store.atomic_json(stage/(sid+'.prepared.json'),packet)
        prepared.append(packet)
        if len(prepared)%12==0:progress(f'Prepared {len(prepared)}/{len(owned)} original-template packets',flush=True)
    # Check again immediately before installation; a browser edit during preparation
    # must not be overwritten. The backup also retains superseded observations.
    for p in prepared:
        if (core.get_iep(p['sid'])!=p['old_record'] or P.student_document(p['sid'])!=p['old_document']
            or R.get(p['old_review']['id'])!=p['old_review']):raise ValueError('Practice record changed while preparing: '+p['sid'])
    backup=stage/'before.json'
    if prepared and not backup.exists():
        store.atomic_json(backup,{'at':store.now(),'sis':store.get('sis',M.PROVIDER),
            'reports':[r for r in store.all_records('report') if r.get('generator')==M.VERSION],
            'students':prepared})
    if prepared:M._roster([(p['sid'],p['record']) for p in prepared])
    for n,p in enumerate(prepared,1):
        sid=p['sid'];meta=p['meta'];record=p['record']
        core.save_iep(sid,record,'Updated generated practice fixture: original NASET form and course gradebook',force_version=True)
        P.save_document(sid,p['document'])
        evidence=C.seed_evidence(sid,record,cases[meta['case_id']],M.VERSION,M.PROVIDER)
        review=copy.deepcopy(p['old_review'])
        review.update(base=record,base_hash=R.fingerprint(record),candidate=p['candidate'],document=p['document'],
            document_hash=R.fingerprint(p['document']),revision=review['revision']+1,
            title='Review: '+cases[meta['case_id']]['goal_area'],
            evidence=evidence+[e for e in review['evidence'] if e.get('kind')=='reference'])
        R._event(review,'practice_fixture_refreshed','Local fixture generator','Populated original template; pending human review retained. Previous packet and evidence archived.')
        store.put('review',review['id'],review)
        meta['generation']['layout_version']=N.LAYOUT_VERSION
        meta['generation']['profile_spec_sha256']=P.digest(M.PROFILES.read_bytes())
        store.put('mock_student',sid,meta)
        if n%24==0:progress(f'Installed {n}/{len(prepared)} original-template packets',flush=True)
    result={'updated':len(prepared),'already_current':len(current),'skipped_human_changes':skipped,'layout_version':N.LAYOUT_VERSION}
    store.atomic_json(stage/'result.json',result)
    return result


if __name__=='__main__':print(json.dumps(refresh(M.load_sources()),indent=2))
