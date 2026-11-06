import copy
import json
import jsonschema
import pytest
import pymupdf
import core
import integrations as I
import local_store as store
import mock_cohort as M
import ontology as O
import pdf_workspace as P
import reviews as R


def source_fixture(tmp_path, original_pdf):
    template={'id':'test-reference','state':'Test State','title':'Test reference form','form_date':'Test fixture',
              'form_type':'Blank template','pages':1,'sha256':P.digest(original_pdf),'url':'https://example.org/form.pdf','crosswalk':[], 'mock_layout':{'source_sha256':P.digest(original_pdf),'source_pages':[1],
                'fields':{'profile.needs':{'page':0,'rect':[40,120,570,208]}}}}
    (tmp_path/'test-reference.pdf').write_bytes(original_pdf)
    catalogs={key:{'record':{'id':key,'name':key,'evidence_level':'editorial'},'source':{'revision':'fixture'}}
              for case in M.profiles() for key in case['catalog_ids']}
    return {'reference_root':tmp_path,'templates':[template], 'accommodations':catalogs,
            'edb':{c['id']:{'url':'https://example.org/source.pdf','sha256':'fixture','jurisdiction':'HK'} for c in M.profiles()},
            'udl':{'rows':[1,2,40],'revision':'fixture'}}


def test_complete_matrix_and_age_specific_forms(tmp_path,original_pdf):
    sources=source_fixture(tmp_path,original_pdf)
    cases=M.profiles();templates=O.catalog();names=set()
    assert len(cases)==12 and len(templates)==32
    for i,template in enumerate(templates):
        for case in cases:
            record,candidate=M.build_record(case,template,i,sources)
            names.add(record['student_name'])
            assert len(P.changes(record,candidate))==3
            assert record['meta']['eligibility'].startswith('Not determined')
            age,grade=M.age_for(case,template)
            if 'ages-16-21' in template['id']: assert 16<=age<=21
            if 'elementary' in template['id']: assert age<=13
            if 'secondary' in template['id']: assert age>=16
            assert all(g['mastery_date']==M.END for g in record['goals'])
    assert len(names)==384


def test_seed_bindings_evidence_and_idempotency(workspace,original_pdf):
    sources=source_fixture(workspace,original_pdf)
    manifest=M.seed_cohort(sources,case_ids=['adhd'],progress=lambda _:None)
    pair=manifest['pairs'][0];sid=pair['student_id'];rid=pair['review_id']
    review=R.get(rid)
    assert review['status']=='pending' and len(P.changes(review['base'],review['candidate']))==3
    assert len(I.evidence(sid))==6
    assert len([r for r in I.evidence(sid) if r['kind']=='lti_result'])==4
    document=P.student_document(sid)
    original=P.source_bytes(document)
    rendered,unmapped=P.render_document(document,review['candidate'])
    assert not unmapped
    with pymupdf.open(stream=rendered,filetype='pdf') as pdf:
        assert 'Synthetic IEP original layout' in pdf[0].get_text()
        assert 'REFERENCE FORM ONLY' not in pdf[0].get_text()
        assert any('discreet break prompt' in p.get_text() for p in pdf)
    assert P.source_bytes(document)==original
    # Human edits and completed decisions must survive a repeat seed.
    R.decide(rid,'approved','Test reviewer','Case manager',True,revision=review['revision'])
    changed=core.get_iep(sid)
    M.seed_cohort(sources,case_ids=['adhd'],progress=lambda _:None)
    assert core.get_iep(sid)==changed
    assert len(R.list_reviews(sid))==1 and R.get(rid)['status']=='approved'
    assert M.verify_cohort()['reports']==2


def test_no_existing_student_overwrite(workspace,original_pdf):
    sources=source_fixture(workspace,original_pdf)
    record,_=M.build_record(M.profiles()[0],sources['templates'][0],0,sources)
    sid=core.create_student(record)
    with pytest.raises(ValueError,match='Refusing to replace'):
        M.seed_cohort(sources,case_ids=[M.profiles()[0]['id']],progress=lambda _:None)
    assert core.get_iep(sid)==record


def test_student_evidence_never_crosses_pairs(workspace,original_pdf,monkeypatch):
    sources=source_fixture(workspace,original_pdf)
    result=M.seed_cohort(sources,case_ids=['adhd','visual'],progress=lambda _:None)
    for pair in result['pairs']:
        sid=pair['student_id']
        evidence=I.evidence(sid)
        assert len(evidence)==6
        assert all(e['student_id']==sid and sid in e['course_id'] for e in evidence)
    prompts=[]
    monkeypatch.setattr(core,'retrieve',lambda sid,question:[])
    monkeypatch.setattr(core,'_chat',lambda system,prompt:prompts.append(prompt) or 'Grounded discussion')
    first,second=[pair['student_id'] for pair in result['pairs']]
    reply,citations=core.answer(first,'Compare classroom implementation.')
    assert first in prompts[0] and second not in prompts[0]
    assert 'COURSE EVIDENCE' in prompts[0] and len(citations)==6


def test_seeded_gradebooks_use_lti_course_instructors(platform,original_pdf,monkeypatch):
    sources=source_fixture(store.DATA_DIR,original_pdf)
    manifest=M.seed_cohort(sources,case_ids=['adhd'],progress=lambda _:None)
    sid=manifest['pairs'][0]['student_id']
    for course in I.student_context(sid)['classes']:
        results=I.sync_lms(sid,course['sourcedId'],platform.base)
        assert len(results)==2
        assert all(r['author_verified_in_course'] and r['score'] is not None and r['observation'] for r in results)
        expected='Emily Harper' if course['title']=='Mathematics' else 'Daniel Reed'
        assert {r['reporter'] for r in results}=={expected}
        I.sync_lms(sid,course['sourcedId'],platform.base)
    assert len(I.evidence(sid))==6
    prompts=[]
    monkeypatch.setattr(core,'_context',lambda *args:('',[]))
    monkeypatch.setattr(core,'recommend_accommodations',lambda *args,**kw:[])
    monkeypatch.setattr(core,'_chat_json',lambda system,prompt:prompts.append((system,prompt)) or {'suggestions':[]})
    core.suggest_updates(sid,'Review grades and assignment feedback.')
    system,prompt=prompts[0]
    assert '"score": 72' in prompt and '"maximum": 100' in prompt
    assert 'Multi-step problem solving' in prompt and 'Emily Harper' in prompt
    assert 'do not infer a course grade' in system


def test_missing_grader_never_infers_an_author():
    from mock_platform import ROLE
    teacher={'user_id':'teacher','name':'Course teacher','roles':[ROLE+'Instructor']}
    record=I.lms_result_record('s','sis','course','Math',{'id':'line','label':'Task'},
                               {'userId':'learner','resultScore':0,'resultMaximum':10,'comment':'Revisit step two.'},[teacher])
    assert record['reporter']=='Author not provided by LMS'
    assert not record['author_verified_in_course'] and record['score']==0 and record['graded_at'] is None


def test_native_widget_values_remain_in_canonical_form_tree(workspace):
    import io
    from reportlab.pdfgen import canvas
    from pypdf import PdfReader
    import native_templates as N
    buffer=io.BytesIO();page=canvas.Canvas(buffer)
    page.drawString(40,750,'Original template heading')
    page.acroForm.textfield(name='StudentName',x=40,y=700,width=200,height=20)
    page.showPage();page.save()
    source=buffer.getvalue()
    record=core.blank_iep('Test Student');record['profile']['needs']='Support starting a task.'
    candidate=copy.deepcopy(record);candidate['student_name']='Revised Student'
    template={'id':'unit','state':'Test','mock_layout':{'source_sha256':P.digest(source),'source_pages':[1],
        'fields':{'profile.needs':{'page':0,'rect':[40,150,550,230]}}}}
    data,bindings,_,_=N.build_packet(record,candidate,template,source)
    assert PdfReader(io.BytesIO(data)).get_fields()['StudentName']['/V']=='Test Student'
    path=workspace/'native.pdf';path.write_bytes(data)
    document={'source':'native.pdf','sha256':P.digest(data),'baseline':record,'bindings':bindings}
    rendered,missing=P.render_document(document,candidate)
    assert not missing and PdfReader(io.BytesIO(rendered)).get_fields()['StudentName']['/V']=='Revised Student'
    assert path.read_bytes()==data
