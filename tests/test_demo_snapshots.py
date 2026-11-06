import copy
import json
import pytest
import core
import demo_snapshots as D
import demo_video
import local_store as store
import pdf_workspace as P
import reviews as R
import workspace_state as W


def test_snapshot_restores_students_history_reviews_evidence_and_vectors(workspace,record,original_pdf):
    sid=core.create_student(record);P.save_document(sid,P.archive_source(original_pdf,record,'original.pdf'))
    for kind in ('report','lms','sis','mock_gradebook','student_link'):
        store.put(kind,'example',{'student_id':sid,'score':72})
    core._col.add(ids=['chunk-1'],documents=['Starting context'],metadatas=[{'student_id':sid,'source':'note.txt'}],embeddings=[[1.,0.,0.]])
    snap=D.capture('Demo start');old_generation=W.generation()
    proposed=copy.deepcopy(record);proposed['grade']='10'
    review=R.stage_change(sid,proposed,'Demo edit');R.decide(review,'approved','Reviewer','Case manager',True)
    new=core.create_student(core.blank_iep('Added during take'))
    for kind in ('report','lms','sis','mock_gradebook','student_link'):store.put(kind,'example',{'student_id':sid,'score':99})
    core._col.delete(ids=['chunk-1'])
    core._col.add(ids=['chunk-2'],documents=['Later context'],metadatas=[{'student_id':sid,'source':'later.txt'}],embeddings=[[0.,1.,0.]])
    (workspace/'originals'/'later.pdf').write_bytes(b'Archived but unlinked')
    result=D.restore(snap['id'])
    assert W.generation()!=old_generation
    assert core.get_iep(sid)==record and new not in core.list_students()
    assert not core.list_versions(sid) and not R.list_reviews(sid)
    assert all(store.get(kind,'example')['score']==72 for kind in ('report','lms','sis','mock_gradebook','student_link'))
    assert core._col.get()['documents']==['Starting context']
    assert P.source_bytes(P.student_document(sid))==original_pdf
    assert (workspace/'originals'/'later.pdf').exists()
    assert result['backup']['label']=='Before reset · Demo start'
    assert result['backup']['students']==2
    D.restore(snap['id'])
    assert core.get_iep(sid)==record


def test_corrupt_snapshot_fails_before_any_changes(workspace,record):
    sid=core.create_student(record);snap=D.capture('Start')
    sha=snap['files'][f'students/{sid}/iep.json']
    (workspace/'snapshots'/'objects'/sha).write_text('damaged',encoding='utf-8')
    with pytest.raises(ValueError,match='integrity'):D.restore(snap['id'])
    assert core.get_iep(sid)==record and len(D.list_snapshots())==1


@pytest.mark.parametrize('path',['../outside','students/../../outside','students/../workspace.sqlite3','accommodations.json/child','C:/outside'])
def test_snapshot_paths_stay_inside_managed_locations(workspace,path):
    with pytest.raises(ValueError,match='location'):D._safe_target(path)


def test_failed_restore_rolls_back_the_current_take(workspace,record,monkeypatch):
    sid=core.create_student(record);snap=D.capture('Start')
    changed=copy.deepcopy(record);changed['grade']='10';core.save_iep(sid,changed)
    core._col.add(ids=['latest'],documents=['Latest context'],metadatas=[{'source':'later.txt'}],embeddings=[[1.,0.]])
    original=core._col.delete;calls=[]
    def fail_once(*args,**kwargs):
        calls.append(1)
        if len(calls)==1:raise RuntimeError('Simulated vector failure')
        return original(*args,**kwargs)
    monkeypatch.setattr(core._col,'delete',fail_once)
    with pytest.raises(RuntimeError,match='Simulated'):D.restore(snap['id'])
    assert core.get_iep(sid)==changed
    assert core._col.get()['documents']==['Latest context']
    assert len(core.list_versions(sid))==1


def test_demo_setup_is_once_only_and_archives_untouched_seed_reviews(workspace,record,original_pdf,monkeypatch):
    cast=[]
    for index in range(2):
        r=copy.deepcopy(record);r['student_name']=f'Video Student {index}';sid=core.create_student(r)
        P.save_document(sid,P.archive_source(original_pdf,r,'original.pdf'))
        changed=copy.deepcopy(r);changed['grade']='10'
        R.stage_change(sid,changed,'Prepared change','Synthetic dataset generator')
        cast.append({'id':sid,'name':r['student_name'],'initial_drafts':index,'purpose':'Demo'})
    monkeypatch.setattr(demo_video,'STUDENTS',cast)
    result=demo_video.prepare()
    assert len(R.list_reviews(cast[0]['id']))==0 and len(R.list_reviews(cast[1]['id']))==1
    assert len(store.all_records('review_archive'))==1
    assert len(D.list_snapshots())==2
    changed=core.get_iep(cast[0]['id']);changed['grade']='11';core.save_iep(cast[0]['id'],changed)
    assert demo_video.prepare()['already_prepared']
    assert core.get_iep(cast[0]['id'])['grade']=='11'
    D.restore(result['snapshot_id'])
    assert core.get_iep(cast[0]['id'])['grade']==record['grade']
