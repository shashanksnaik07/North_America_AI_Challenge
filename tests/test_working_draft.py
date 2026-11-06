import copy
import uuid
import pytest
import core
import drafting as D
import reviews as R
import pdf_workspace as P
import local_store as store
from draft_merge import combine
from test_drafting import student, option


def legacy(sid, base, source, candidate, title):
    item={'id':uuid.uuid4().hex,'student_id':sid,'kind':'change','title':title,
          'created':store.now(),'base':copy.deepcopy(base),'base_hash':R.fingerprint(base),
          'candidate':candidate,'document':source,'document_hash':R.fingerprint(source),
          'status':'pending','required_role':'Case manager','assignee':'','revision':1,
          'events':[],'findings':[],'evidence':[{'source':title}]}
    store.put('review',item['id'],item)
    return item


def test_suggestions_and_manual_edits_share_one_draft_then_one_version(workspace,record,original_pdf):
    sid=student(record,original_pdf)
    first=option(sid,record,'goals.0.goal','Use a written next step in four of five sessions.')
    second=option(sid,record,'progress_report_weeks','4')
    D.submit(sid,[first],'Teacher')
    pending=R.working_draft(sid);rid=pending['id']
    edited=copy.deepcopy(pending['candidate']);edited['goals'][0]['goal']='Use a written next step in five of six sessions.'
    assert R.stage_change(sid,edited,'Goal wording','Case manager',expected_draft_revision=1)==rid
    D.submit(sid,[second],'Teacher')
    pending=R.working_draft(sid)
    assert pending['id']==rid and pending['revision']==3
    assert pending['candidate']['goals'][0]['goal']==edited['goals'][0]['goal']
    assert pending['candidate']['progress_report_weeks']=='4'
    assert len(R.list_reviews(sid,open_only=True))==1
    assert core.get_iep(sid)==record and not core.list_versions(sid)
    with pytest.raises(ValueError,match='Another session'):
        R.stage_change(sid,edited,'Outdated editor',expected_draft_revision=1)
    with pytest.raises(ValueError,match='Another session'):
        R.decide(rid,'approved','Reviewer','Case manager',True,revision=2)
    R.decide(rid,'approved','Reviewer','Case manager',True,revision=3)
    assert core.get_iep(sid)==pending['candidate']
    assert len(core.list_versions(sid))==1 and not R.list_reviews(sid,open_only=True)


def test_legacy_siblings_carry_forward_without_reverting_approved_goal(workspace,record,original_pdf):
    sid=student(record,original_pdf);source=P.student_document(sid)
    approved=copy.deepcopy(record);approved['goals'][0]['goal']='Already approved new goal.'
    core.save_iep(sid,approved)
    a=copy.deepcopy(record);a['profile']['parent_concerns']='Check implementation across courses.'
    b=copy.deepcopy(record);b['progress_report_weeks']='4'
    earlier=[legacy(sid,record,source,a,'Parent concerns'),legacy(sid,record,source,b,'Monitoring')]
    pending=R.working_draft(sid)
    assert pending['candidate']['goals']==approved['goals']
    assert pending['candidate']['profile']['parent_concerns']==a['profile']['parent_concerns']
    assert pending['candidate']['progress_report_weeks']=='4'
    assert not pending['merge_conflicts'] and len(pending['evidence'])==2
    assert len(R.list_reviews(sid,open_only=True))==1
    assert len(store.all_records('review_archive'))==2
    assert any(R.get(x['id'])['status']=='superseded' for x in earlier)
    assert core.get_iep(sid)==approved
    assert R.working_draft(sid)==pending  # idempotent, including revision
    R.decide(pending['id'],'approved','Reviewer','Case manager',True,revision=pending['revision'])
    assert len(core.list_versions(sid))==2 and core.list_versions(sid)[0]['iep']==approved


def test_rebase_blocks_conflicting_approval_until_explicit_resolution(workspace,record,original_pdf):
    sid=student(record,original_pdf)
    changed=copy.deepcopy(record);changed['grade']='10'
    rid=R.stage_change(sid,changed,'Grade')
    current=copy.deepcopy(record);current['grade']='11';core.save_iep(sid,current)
    with pytest.raises(ValueError,match='current IEP changed'):
        R.decide(rid,'approved','Reviewer','Case manager',True,revision=1)
    pending=R.working_draft(sid)
    assert pending['candidate']['grade']=='11' and len(pending['merge_conflicts'])==1
    with pytest.raises(ValueError,match='conflicting'):
        R.decide(rid,'approved','Reviewer','Case manager',True,revision=pending['revision'])
    R.resolve_conflict(rid,pending['merge_conflicts'][0]['id'],True,'Reviewer',pending['revision'])
    resolved=R.get(rid)
    assert resolved['candidate']['grade']=='10' and not resolved['merge_conflicts']
    assert core.get_iep(sid)==current
    R.decide(rid,'approved','Reviewer','Case manager',True,revision=resolved['revision'])
    assert core.get_iep(sid)['grade']=='10'


def test_legacy_conflicts_preserve_reviewer_restrictions(workspace,record,original_pdf):
    sid=student(record,original_pdf);source=P.student_document(sid)
    a=copy.deepcopy(record);a['grade']='10'
    b=copy.deepcopy(record);b['grade']='11'
    first=legacy(sid,record,source,a,'A');second=legacy(sid,record,source,b,'B')
    R.escalate(first['id'],'Teacher','Check','Alex','Specialist')
    R.escalate(second['id'],'Teacher','Check','Sam','Administrator')
    pending=R.working_draft(sid)
    assert len(pending['merge_conflicts'])==1 and pending['status']=='escalated'
    assert pending['required_role']=='Administrator' and pending['assignee']==''
    assert any('different assigned reviewers' in f for f in pending['findings'])
    R.resolve_conflict(pending['id'],pending['merge_conflicts'][0]['id'],False,'Admin',pending['revision'])
    with pytest.raises(ValueError,match='requires Administrator'):
        R.decide(pending['id'],'approved','Alex','Specialist',True)
    R.decide(pending['id'],'approved','Admin','Administrator',True)


def test_list_edits_preserve_appends_and_flag_ambiguous_deletions():
    base=[{'goal':'One'},{'goal':'Two'}]
    current=[{'goal':'Edited one'},{'goal':'Two'},{'goal':'Three'}]
    proposed=[{'goal':'One'},{'goal':'Edited two'},{'goal':'Four'}]
    conflicts=[]
    result=combine(base,current,proposed,conflicts,path='goals')
    assert result==[{'goal':'Edited one'},{'goal':'Edited two'},{'goal':'Three'},{'goal':'Four'}]
    assert not conflicts
    assert combine(base,current,base[1:],conflicts,path='goals')==current
    assert len(conflicts)==1 and conflicts[0]['path']=='goals'


def test_pdf_layout_edit_and_suggestion_share_draft(workspace,record,original_pdf):
    sid=student(record,original_pdf);source=P.student_document(sid)
    mapped=P.set_binding(source,'grade',{'page':0,'rect':[40,200,300,240]})
    rid=R.stage_change(sid,record,'Position grade',document=mapped,expected_draft_revision=0)
    D.submit(sid,[option(sid,record,'grade','10')])
    pending=R.working_draft(sid)
    assert pending['id']==rid and pending['document']['bindings']['grade']==mapped['bindings']['grade']
    assert P.student_document(sid)==source
    R.decide(rid,'approved','Reviewer','Case manager',True,revision=pending['revision'])
    assert len(core.list_versions(sid))==1 and core.get_iep(sid)['grade']=='10'
