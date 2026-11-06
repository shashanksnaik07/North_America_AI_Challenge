"""Prepare a small recording cast without rewriting the rest of the caseload."""
import core
import demo_snapshots as snapshots
import local_store as store
import pdf_workspace as P
import reviews as R
import workspace_state as W

STUDENTS = [
    {'id':'demo-ellis-brook-t01','name':'Ellis Brook','initial_drafts':0,
     'purpose':'Course grades and comments → new modification draft → approval'},
    {'id':'demo-gray-marlow-t01','name':'Gray Marlow','initial_drafts':0,
     'purpose':'A precise PDF edit, or an accommodation option with delivery details'},
    {'id':'demo-logan-sage-t01','name':'Logan Sage','initial_drafts':1,
     'purpose':'Prepared changes → specialist escalation → human decision'},
]


@W.guarded
def prepare(backup_id=None):
    existing=store.get('demo_setup','video')
    if existing:
        return {'setup':existing,'already_prepared':True}
    to_archive=[]
    for student in STUDENTS:
        sid=student['id'];record=core.get_iep(sid);items=R.list_reviews(sid)
        if record['student_name']!=student['name']: raise ValueError('Unexpected recording student: '+sid)
        for item in items:
            if (item['status']!='pending' or item['base']!=record
                    or item.get('document_hash')!=R.fingerprint(P.student_document(sid))
                    or not all(event.get('actor') in ('Synthetic dataset generator','Dataset generator','Local fixture generator') for event in item['events'])):
                raise ValueError('This student already has human activity. Preserve it and choose another recording student: '+student['name'])
        if student['initial_drafts']==1 and len(items)!=1: raise ValueError('Expected one prepared review for '+student['name'])
        if student['initial_drafts']==0: to_archive.extend(items)
    if backup_id:
        before=snapshots._manifest(backup_id)
        snapshots._validate(before)
    else: before=snapshots.capture('Before demo preparation')
    setup={'students':STUDENTS,'prepared_at':store.now(),'backup_id':before['id'],'snapshot_label':'Demo start'}
    with store.transaction() as db:
        for item in to_archive:
            archived={**item,'archived_at':store.now(),'archive_reason':'Recording start: untouched generated draft retained outside the active inbox.'}
            store.put('review_archive','demo-start-'+item['id'],archived,db)
            db.execute("DELETE FROM records WHERE kind='review' AND id=?",(item['id'],))
        store.put('demo_setup','video',setup,db)
    try: start=snapshots.capture('Demo start')
    except Exception:
        # Preparing must never leave a half-configured recording workspace.
        with store.transaction() as db:
            for item in to_archive:
                store.put('review',item['id'],item,db)
                db.execute("DELETE FROM records WHERE kind='review_archive' AND id=?",('demo-start-'+item['id'],))
            db.execute("DELETE FROM records WHERE kind='demo_setup' AND id='video'")
        raise
    return {'setup':setup,'snapshot_id':start['id'],'already_prepared':False}
