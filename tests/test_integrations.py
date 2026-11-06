import copy
import time
import jwt
import pytest
import requests
import core
import integrations as I
import local_store as store
from mock_platform import LTI, CLIENT, SCOPES

def linked(platform, record):
    sid = core.create_student(record)
    snapshot = I.sync_sis('powerschool', platform.base)
    I.link_student(sid, 'powerschool', 'powerschool:stu-001')
    return sid, snapshot

def test_paginated_roster_and_explicit_identity(platform, record):
    sid, snapshot = linked(platform, record)
    assert len(snapshot['users']) == 4 and len(snapshot['enrollments']) == 6
    assert {c['title'] for c in I.student_context(sid)['classes']} == {'Algebra I', 'English 9'}
    assert core.get_iep(sid) == record
    other = copy.deepcopy(record); other['student_name'] = 'Another Synthetic Student'; other_sid = core.create_student(other)
    with pytest.raises(ValueError, match='already linked'): I.link_student(other_sid, 'powerschool', 'powerschool:stu-001')

@pytest.mark.parametrize('provider', ['powerschool', 'infinite-campus', 'skyward'])
def test_all_provider_profiles(platform, provider):
    data = I.sync_sis(provider, platform.base)
    assert data['users'][0]['sourcedId'].startswith(provider+':')

def test_lti_results_and_student_course_isolation(platform, record):
    sid, _ = linked(platform, record)
    records = I.sync_lms(sid, 'powerschool:math-9', platform.base)
    assert len(records) == 1 and records[0]['sis_id'] == 'powerschool:stu-001'
    with pytest.raises(ValueError, match='not enrolled'): I.sync_lms(sid, 'powerschool:science-7', platform.base)
    I.sync_lms(sid, 'powerschool:math-9', platform.base)
    assert len(I.evidence(sid)) == 1  # repeat sync is idempotent
    I.link_student(sid, 'powerschool', 'powerschool:stu-002')
    assert not I.evidence(sid)  # old identity's results never leak into the new identity

def test_auth_and_pagination_origin(platform):
    url=platform.base+'/sis/powerschool/ims/oneroster/rostering/v1p2/users'
    assert requests.get(url).status_code == 401
    with pytest.raises(ValueError, match='outside'): I._same_origin('https://unregistered.example/next', platform.base)

def launch(platform):
    response=requests.get(platform.base+'/mock/launch', params={'context': 'powerschool:math-9', 'nonce': 'test-nonce', 'state': 'test-state'}).json()
    keys=requests.get(platform.base+'/.well-known/jwks.json').json()
    return response['id_token'], keys

def test_lti_nonce_state_signature_and_replay(platform):
    token, keys = launch(platform)
    with pytest.raises(ValueError, match='state'): I.validate_launch(token, keys, 'test-nonce', 'bad', 'test-state', platform.base)
    with pytest.raises(ValueError, match='nonce'): I.validate_launch(token, keys, 'bad', 'test-state', 'test-state', platform.base)
    changed = jwt.decode(token, options={'verify_signature': False}); changed['aud'] = 'another-client'
    forged = jwt.encode(changed, platform.platform_key, algorithm='RS256', headers={'kid': 'demo-platform'})
    with pytest.raises(jwt.InvalidAudienceError): I.validate_launch(forged, keys, 'test-nonce', 'test-state', 'test-state', platform.base)
    I.validate_launch(token, keys, 'test-nonce', 'test-state', 'test-state', platform.base)
    with pytest.raises(ValueError, match='replay'): I.validate_launch(token, keys, 'test-nonce', 'test-state', 'test-state', platform.base)

def test_course_reports_aggregate_and_enter_suggestion_prompt(platform, record, monkeypatch):
    sid, _ = linked(platform, record)
    for course, outcome in [('math-9', 'Helpful'), ('english-9', 'Mixed')]:
        I.submit_report(sid, 'powerschool:'+course, 'Synthetic Teacher', 'Extended time', 'Most opportunities', outcome,
                        'Completes work with extended time; attention varies by task.', '2026-10-01', '2026-10-31')
    group = I.aggregate_reports(sid)[0]
    assert group['Reports'] == 2 and group['Mixed observations']
    filtered=I.aggregate_reports(sid,records=[r for r in I.evidence(sid) if r['course']=='Algebra I'])
    assert len(filtered)==1 and filtered[0]['Reports']==1 and filtered[0]['Courses']=='Algebra I'
    assert not filtered[0]['Mixed observations']
    assert I.aggregate_reports(sid,records=[])==[]
    prompts = []
    def chat(system, prompt, **kw):
        prompts.append(prompt)
        return {'suggestions': [{'action': 'change', 'field': 'profile.needs', 'new_value': 'Review extended time across courses.', 'reason': 'Mixed reports', 'source': 'E1'}]}
    monkeypatch.setattr(core, '_chat_json', chat)
    suggestions = core.suggest_updates(sid)
    assert 'Algebra I' in prompts[0] and 'English 9' in prompts[0]
    assert len(suggestions[0]['evidence']) == 2
    text, used, omitted = I.evidence_context(sid, limit_chars=1)
    assert not used and len(omitted) == 2 and 'omitted' in text
