"""Reproducible, local-only synthetic cases; never infer real student outcomes."""
from __future__ import annotations

import copy
import io
import json
from pathlib import Path

import jsonschema
from pypdf import PdfReader

import core
import iep_schema as S
import integrations as I
import local_store as store
import ontology as O
import pdf_workspace as P
import reviews as R

ROOT = Path(__file__).parent
VERSION = 'hk-naset-v1'
PROVIDER = 'dataset-demo'
START, END = '2026-09-01', '2027-08-31'
OBS_START, OBS_END = '2026-10-05', '2026-10-30'
PROFILES = ROOT / 'fixtures' / 'mock_profiles.json'


def profiles():
    return json.loads(PROFILES.read_text(encoding='utf-8'))


def load_sources(root=ROOT / 'data'):
    refs = root / 'reference_sources'
    manifest = json.loads((refs / 'manifest.json').read_text(encoding='utf-8'))
    by_file = {x['path']: x for x in manifest['files']}
    for item in manifest['files']:
        if P.digest((refs / item['path']).read_bytes()) != item['sha256']:
            raise ValueError('Reference source changed: ' + item['path'])
    edb = {}
    for case in profiles():
        data = json.loads((refs / 'derived' / 'edb_text' / case['file']).read_text(encoding='utf-8'))
        source = data['source']
        if source['sha256'] != by_file[source['file']]['sha256']:
            raise ValueError('EDB extraction does not match source')
        edb[case['id']] = {**source, 'pages': list(range(1, len(data['pages'])+1)),
                          'jurisdiction': 'HK', 'use': 'Example category and planning structure; no source identities or outcomes copied'}
    accommodations = {}
    for file in sorted((refs / 'derived' / 'robworks' / 'data').glob('*.jsonl')):
        for line in file.read_text(encoding='utf-8').splitlines():
            item = json.loads(line)
            accommodations[item['record']['id']] = item
    if len(accommodations) != 50:
        raise ValueError('Expected the pinned 50-item accommodation catalog')
    udl = next(x for x in manifest['files'] if x.get('source') == 'jeremierostan/iep-udl-dataset' and x['path'].endswith('.jsonl'))
    conversations = [json.loads(line) for line in (refs / udl['path']).read_text(encoding='utf-8').splitlines() if line.strip()]
    if len(conversations) != 55:
        raise ValueError('Unexpected IEP/UDL conversation snapshot')
    # Only question-pattern provenance. Neither answers nor system messages are used.
    patterns = {**udl, 'rows': [1, 2, 40], 'use': 'Plan-grounded support questions and high expectations; independently authored wording'}
    templates = O.catalog()
    for template in templates:
        if P.digest((root / 'reference' / (template['id']+'.pdf')).read_bytes()) != template['sha256']:
            raise ValueError('NASET source changed: '+template['id'])
    return {'edb': edb, 'accommodations': accommodations, 'udl': patterns,
            'templates': templates, 'reference_root': root / 'reference'}


def age_for(case, template):
    tid = template['id']
    if 'ages-16-21' in tid: return 17, 11
    if 'secondary' in tid: return max(16, case['age']), max(10, case['grade'])
    if 'elementary' in tid: return min(11, case['age']), min(5, case['grade'])
    if 'ages-6-15' in tid: return min(14, case['age']), min(8, case['grade'])
    return case['age'], case['grade']


def build_record(case, template, template_index, sources):
    age, grade = age_for(case, template)
    surnames=[case['name'].split(' ',1)[1],'Chen','Garcia','Williams','Patel','Wilson','Kim','Brooks',
        'Nguyen','Davis','Anderson','Martinez','Taylor','Thomas','Jackson','White','Harris','Martin',
        'Thompson','Moore','Young','Allen','Lewis','Walker','Hall','Rivera','Scott','Green','Adams','Baker','Nelson','Carter']
    name=case['name'].split(' ',1)[0]+' '+surnames[template_index%len(surnames)]
    record = core.blank_iep(name)
    record.update(dob=f'{2026-age}-03-15', grade=str(grade), school_year='2026-2027', iep_from=START, iep_to=END)
    record['meta'] = {'school': f"Cedar Grove School - {template['state']}",
                      'case_manager': 'Sarah Patel', 'eligibility': 'Not determined - team review pending'}
    record['profile'].update(strengths=case['strengths'], needs=case['needs'],
        preferences_interests=case['interest'], parent_concerns=case['family'],
        evaluation_results='Formal evaluation results are not available in this record.',
        other='Review classroom observations and student preferences before finalizing changes.')
    record['progress_report_weeks'] = '6'
    record['goals'] = [S.empty_goal() | {
        'area': case['goal_area'], 'present_level': 'Independent performance in two of five comparable opportunities; supported and independent performance are recorded separately.',
        'goal': 'By the plan review date, the student will '+case['goal_action']+'.', 'mastery_date': END,
        'evaluation': ['Teacher Observation', 'Work Samples'],
        'benchmarks': [{'text': 'Establish comparable tasks and record support availability; no achieved outcome is assumed.', 'date': '2026-11-30'},
                       {'text': 'Review independent and supported responses across both courses with student feedback.', 'date': '2027-03-01'}]},
        S.empty_goal() | {'area': 'Student voice and self-advocacy',
        'present_level': 'A support preference was communicated in two of five offered check-ins.',
        'goal': 'By the plan review date, identify a useful support or request an adjustment in four of five offered check-ins, using a preferred communication method.',
        'mastery_date': END, 'evaluation': ['Teacher Observation'],
        'benchmarks': [{'text': 'Agree on a private and accessible check-in method.', 'date': '2026-11-30'},
                       {'text': 'Compare student preferences with implementation records; retain disagreements.', 'date': '2027-03-01'}]}]
    aids = []
    for index, catalog_id in enumerate(case['catalog_ids']):
        source = sources['accommodations'][catalog_id]['record']
        aids.append(S.empty_service() | {'service': case['support'] if index == 0 else source['name']+'. Agree on individual delivery conditions with the student.',
             'frequency': 'During agreed instructional tasks', 'amount': 'One planned support opportunity per task',
             'begin': START, 'end': END, 'location': 'Mathematics and English language arts courses'})
    record['services']['supplementary_aids'] = {'needed': True, 'rows': aids}
    record['services']['special_education']['rows'] = [S.empty_service() | {
        'service': 'Explicit instruction and guided practice linked to the two goals.',
        'frequency': 'Twice weekly', 'amount': '20 minutes per session', 'begin': START, 'end': END, 'location': 'Agreed classroom or small-group setting'}]
    record['participants'] = [{'position': role, 'name': name, 'date': '2026-09-01'} for role, name in [
        ('Student', record['student_name']), ('Parent / caregiver', 'Alex '+record['student_name'].split(' ',1)[1]),
        ('Case manager', 'Sarah Patel'), ('Mathematics teacher', 'Emily Harper'), ('English language arts teacher','Daniel Reed')]]
    record['transition']['applicable'] = age >= 16
    if age >= 16:
        record['transition']['postsecondary']['education']['long_term_goal'] = 'Explore education and training options connected to the student\'s interests, with accessible information and student-led planning.'
        record['transition_goals']['present_level'] = 'Interest discussion completed; formal transition assessment pending.'
    record['extensions'] = {'mock_cohort': VERSION, 'mock_profile_type': case['label'],
        'mock_template_state': template['state'], 'mock_template_id': template['id'],
        'mock_support_model': 'Tiered example structure; not a U.S. service-placement decision' if 'tiered' in case['id'] else 'Individualized planning example',
        'mock_review_questions': 'Which supports are documented? What differs across courses? What information is missing? How can appropriate challenge be retained?'}
    candidate = copy.deepcopy(record)
    candidate['profile']['needs'] += ' Proposed review: '+case['proposal']
    candidate['services']['supplementary_aids']['rows'][0]['service'] = case['proposal']
    candidate['progress_report_weeks'] = '4'
    for value in (record, candidate): jsonschema.validate(value, O.record_schema())
    return record, candidate


def build_packet(record, candidate, template, reference_bytes):
    from native_templates import build_packet as populate_original
    return populate_original(record,candidate,template,reference_bytes)


def _roster(pairs):
    from mock_course_data import roster
    return roster(pairs,VERSION,PROVIDER)


def seed_cohort(sources, case_ids=None, template_ids=None, progress=print):
    selected_cases=[c for c in profiles() if not case_ids or c['id'] in case_ids]
    selected_templates=[(i,t) for i,t in enumerate(sources['templates']) if not template_ids or t['id'] in template_ids]
    if not selected_cases or not selected_templates: raise ValueError('No matching cases or templates')
    plans=[]
    installed_pairs={(r['case_id'],r['template_id']):r['student_id'] for r in store.all_records('mock_student') if r.get('generator')==VERSION}
    for index,template in selected_templates:
        for case in selected_cases:
            record,candidate=build_record(case,template,index,sources)
            sid=installed_pairs.get((case['id'],template['id']),core.make_student_id(record['student_name']))
            existing=store.get('mock_student',sid)
            if (core.STUDENTS_DIR/sid/'iep.json').exists() and (not existing or existing.get('generator')!=VERSION):
                raise ValueError('Refusing to replace an existing student: '+sid)
            plans.append((sid,record,candidate,case,template))
    _roster([(sid,core.get_iep(sid) if (store.get('mock_student',sid) or {}).get('complete') else record) for sid,record,*_ in plans])
    results=[]
    for sid,record,candidate,case,template in plans:
        existing=store.get('mock_student',sid)
        if existing and existing.get('complete'):
            if not (core.STUDENTS_DIR/sid/'iep.json').exists() or not P.student_document(sid):
                raise ValueError('Seeded student is incomplete; inspect before repairing: '+sid)
            results.append(existing);progress('Kept '+sid);continue
        meta=existing or {'student_id':sid,'generator':VERSION,'synthetic':True,'case_id':case['id'],'case_label':case['label'],
             'template_id':template['id'],'state':template['state'],'complete':False,'review_status':'not educator reviewed',
             'source_family':case['id'].replace('-tiered',''),'template_family':template['state'],
             'edb':sources['edb'][case['id']],'udl_question_patterns':sources['udl'],
             'catalog_sources':[sources['accommodations'][x]['source']|{'id':x,'source_evidence_label':sources['accommodations'][x]['record'].get('evidence_level'),'evidence_verified':False} for x in case['catalog_ids']],
             'naset':{k:template[k] for k in ['id','state','title','form_type','form_date','url','sha256']},
             'generation':{'method':'deterministic independently authored scenarios','version':VERSION,'profile_spec_sha256':P.digest(PROFILES.read_bytes()),'seed':0},
             'rights_scope':'Local demonstration only; no public dataset release or model training authorized by this generator'}
        store.put('mock_student',sid,meta)
        if not (core.STUDENTS_DIR/sid/'iep.json').exists(): core.create_student(record)
        else:
            if core.get_iep(sid)!=record: raise ValueError('Interrupted seed has since been edited: '+sid)
        if not P.student_document(sid):
            source=(sources['reference_root']/(template['id']+'.pdf')).read_bytes()
            packet,bindings,labels,plan_pages=build_packet(record,candidate,template,source)
            from native_templates import layouts
            layout=template.get('mock_layout') or layouts()[template['id']]
            sha=P.digest(packet); path=store.DATA_DIR/'originals'/(sha+'.pdf');path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(packet)
            document={'source':str(path.relative_to(store.DATA_DIR)),'sha256':sha,'filename':sid+'.pdf','template_id':template['id'],
                'origin':'populated NASET template','baseline':record,'bindings':bindings,'page_labels':labels,
                'native_template_pages':plan_pages,'reference_sha256':template['sha256'],'mock_layout_version':3,
                'default_page':layout['source_pages'].index(layout.get('default_source_page',layout['source_pages'][0]))}
            P.save_document(sid,document)
        link=store.get('student_link',sid)
        if link and (link['provider']!=PROVIDER or link['sourced_id']!=VERSION+':'+sid): raise ValueError('Existing identity link changed: '+sid)
        I.link_student(sid,PROVIDER,VERSION+':'+sid)
        from mock_course_data import seed_evidence
        reports=seed_evidence(sid,record,case,VERSION,PROVIDER)
        title='Mock review: '+case['goal_area']
        if not meta.get('review_id'):
            old=next((r for r in R.list_reviews(sid) if r['title']==title and r.get('seed_generator')==VERSION),None)
            if old: meta['review_id']=old['id']
            else:
                evidence=reports+[{'id':sid+':source:'+str(n),'kind':'reference','source':label,'description':description,'synthetic':False,'provenance':data} for n,(label,description,data) in enumerate([
                    ('Hong Kong EDB example','Category and planning structure only; source outcomes were not transferred.',meta['edb']),
                    ('Robworks accommodation catalog','Catalog concepts are reference material, not evidence of effectiveness.',meta['catalog_sources']),
                    ('IEP/UDL question patterns','Independently worded plan-grounded questions; source answers and identities were not used.',meta['udl_question_patterns'])])]
                rid=R.stage_change(sid,candidate,title,'Synthetic dataset generator',evidence)
                review=R.get(rid);review['seed_generator']=VERSION;store.put('review',rid,review);meta['review_id']=rid
        meta['complete']=True;store.put('mock_student',sid,meta);results.append(meta)
        progress(f"Created {len(results)}/{len(plans)}: {case['label']} / {template['state']}")
    # Report the entire installed cohort, including earlier selections.
    installed=[r for r in store.all_records('mock_student') if r.get('generator')==VERSION and r.get('complete')]
    manifest={'generator':VERSION,'synthetic':True,'students':len(installed),'profiles':len({r['case_id'] for r in installed}),
        'templates':len({r['template_id'] for r in installed}),'states':len({r['state'] for r in installed}),
        'pairs':[{'student_id':r['student_id'],'case_id':r['case_id'],'template_id':r['template_id'],'state':r['state'],'review_id':r['review_id']} for r in installed]}
    store.atomic_json(store.DATA_DIR/'mock_cohort'/'manifest.json',manifest)
    return manifest


def verify_cohort(progress=None):
    manifest=json.loads((store.DATA_DIR/'mock_cohort'/'manifest.json').read_text(encoding='utf-8'))
    seen=set();counts={'students':0,'reviews':0,'reports':0,'lms_results':0,'pdf_pages':0,'reference_widgets':0}
    for pair in manifest['pairs']:
        sid=pair['student_id'];key=(pair['case_id'],pair['template_id'])
        if key in seen: raise ValueError('Duplicate pairing')
        seen.add(key);record=core.get_iep(sid);jsonschema.validate(record,O.record_schema())
        doc=P.student_document(sid);data=P.source_bytes(doc)
        if doc.get('mock_layout_version')!=3 or doc.get('origin')!='populated NASET template':
            raise ValueError('Practice PDF still uses a legacy layout: '+sid)
        review=R.get(pair['review_id'])
        if review['student_id']!=sid or doc['template_id']!=pair['template_id']: raise ValueError('Cross-student/template reference')
        rendered,missing=P.render_document(doc,review['candidate'])
        if missing: raise ValueError('Draft contains an unmapped field: '+sid)
        reader=PdfReader(io.BytesIO(rendered));fields=reader.get_fields() or {}
        for page in reader.pages:
            for ref in page.get('/Annots',[]):
                annotation=ref.get_object()
                if annotation.get('/Subtype')=='/Widget':
                    effective=annotation;parts=[]
                    while effective is not None:
                        if effective.get('/T'): parts.append(str(effective['/T']))
                        effective=effective['/Parent'].get_object() if effective.get('/Parent') else None
                    name='.'.join(reversed(parts))
                    if name and name not in fields: raise ValueError('Orphaned reference form field: '+name)
                    counts['reference_widgets']+=1
        counts['pdf_pages']+=len(reader.pages);counts['students']+=1;counts['reviews']+=1
        if progress and counts['students']%24==0: progress(f"Verified {counts['students']}/{manifest['students']} PDFs and drafts")
    # Validate every evidence record against its exact seeded student and course.
    roster=store.get('sis',PROVIDER);enrollments={(e['user']['sourcedId'],e['class']['sourcedId']) for e in roster['enrollments']}
    for report in store.all_records('report'):
        if report.get('generator')!=VERSION or report.get('superseded_by_lms'): continue
        if (report['sis_id'],report['course_id']) not in enrollments: raise ValueError('Unscoped synthetic observation')
        if report['student_id'] not in {p['student_id'] for p in manifest['pairs']}: raise ValueError('Report outside cohort')
        if report['period_start']>report['period_end']: raise ValueError('Invalid observation chronology')
        counts['reports']+=1
    student_ids={p['student_id'] for p in manifest['pairs']}
    for snapshot in store.all_records('lms'):
        if snapshot['student_id'] not in student_ids:continue
        for result in snapshot['records']:
            if (result['sis_id'],result['course_id']) not in enrollments or result['student_id']!=snapshot['student_id']:
                raise ValueError('Unscoped gradebook result')
            author=next((m for m in snapshot['members'] if m['user_id']==result.get('scoring_user_id')),None)
            if not author or not result.get('author_verified_in_course') or result['reporter']!=author['name']:
                raise ValueError('Gradebook author is not verified in course')
            if not isinstance(result['score'],(int,float)) or not isinstance(result['maximum'],(int,float)) or result['maximum']<=0:
                raise ValueError('Invalid assignment grade')
            counts['lms_results']+=1
    return counts
