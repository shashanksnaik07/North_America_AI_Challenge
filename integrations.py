"""Read-only mock SIS/LTI adapters and persistent course evidence with provenance."""
import datetime as dt
import hashlib
import json
import secrets
import time
from urllib.parse import urlparse
import uuid
import jwt
import requests
import local_store as store
from mock_platform import CLIENT, DEPLOYMENT, LTI, NRPS, AGS, ROLE, SCOPES, PROVIDERS, keypair

BASE = 'http://127.0.0.1:8502'

def _same_origin(url, base):
    u, b = urlparse(url), urlparse(base)
    if (u.scheme, u.netloc) != (b.scheme, b.netloc): raise ValueError('Service/pagination URL is outside the registered platform.')
    if u.username or u.password: raise ValueError('Credentials in service URLs are not allowed.')

def _pages(url, token, key=None, base=BASE, media='application/json'):
    seen, output = set(), []
    while url:
        _same_origin(url, base)
        if url in seen or len(seen) > 100: raise ValueError('Invalid pagination loop.')
        seen.add(url)
        result = requests.get(url, headers={'Authorization': 'Bearer '+token, 'Accept': media}, timeout=15, allow_redirects=False)
        result.raise_for_status()
        body = result.json(); output.extend(body[key] if key else body)
        url = result.links.get('next', {}).get('url')
    return output

def sync_sis(provider, base=BASE):
    if provider not in PROVIDERS: raise ValueError('Choose a demo SIS provider.')
    token = requests.post(base+'/oauth/token', data={'grant_type': 'client_credentials', 'client_id': CLIENT,
                          'client_secret': 'synthetic-local-secret', 'scope': 'roster.readonly'}, timeout=15)
    token.raise_for_status(); token = token.json()['access_token']
    snapshot = {'provider': provider, 'synced_at': store.now(), 'synthetic': True, 'standard': 'OneRoster 1.2 REST subset'}
    for resource in ('orgs', 'academicSessions', 'users', 'courses', 'classes', 'enrollments'):
        snapshot[resource] = _pages(base+f'/sis/{provider}/ims/oneroster/rostering/v1p2/{resource}?limit=2', token, resource, base)
    users = {u['sourcedId'] for u in snapshot['users']}
    classes = {c['sourcedId'] for c in snapshot['classes']}
    if any(e['user']['sourcedId'] not in users or e['class']['sourcedId'] not in classes for e in snapshot['enrollments']):
        raise ValueError('SIS snapshot contains broken enrollment references; previous snapshot retained.')
    store.put('sis', provider, snapshot)
    return snapshot

def link_student(sid, provider, sourced_id):
    snapshot = store.get('sis', provider)
    if not snapshot: raise ValueError('Sync the provider first.')
    match = next((u for u in snapshot['users'] if u['sourcedId'] == sourced_id and u['role'] == 'student' and u['status'] == 'active'), None)
    if not match: raise ValueError('Choose an active student from the synced roster.')
    for other in store.all_records('student_link'):
        if other['student_id'] != sid and other['provider'] == provider and other['sourced_id'] == sourced_id:
            raise ValueError('This SIS identity is already linked to another local student.')
    store.put('student_link', sid, {'student_id': sid, 'provider': provider, 'sourced_id': sourced_id, 'linked_at': store.now()})

def student_context(sid):
    link = store.get('student_link', sid)
    if not link: return None
    data = store.get('sis', link['provider'])
    user = next((u for u in data['users'] if u['sourcedId'] == link['sourced_id'] and u['status'] == 'active'), None)
    if not user: return None
    ids = {e['class']['sourcedId'] for e in data['enrollments'] if e['user']['sourcedId'] == link['sourced_id'] and e['status'] == 'active'}
    classes = [c for c in data['classes'] if c['sourcedId'] in ids and c['status'] == 'active']
    return {'link': link, 'user': user, 'classes': classes, 'synced_at': data['synced_at'], 'orgs': data['orgs']}

def validate_launch(token, jwks, nonce, state, expected_state, base=BASE):
    if not secrets.compare_digest(state, expected_state): raise ValueError('LTI state mismatch.')
    header = jwt.get_unverified_header(token)
    key = next((k for k in jwks['keys'] if k.get('kid') == header.get('kid')), None)
    if not key: raise ValueError('Unknown LTI signing key.')
    claims = jwt.decode(token, jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key)), algorithms=['RS256'],
                        issuer=base, audience=CLIENT, options={'require': ['exp', 'iat', 'nonce', 'sub']})
    if claims['nonce'] != nonce: raise ValueError('LTI nonce mismatch.')
    if isinstance(claims['aud'], list) and len(claims['aud']) > 1 and claims.get('azp') != CLIENT: raise ValueError('Invalid authorized party.')
    for key, value in [('version', '1.3.0'), ('message_type', 'LtiResourceLinkRequest'), ('deployment_id', DEPLOYMENT)]:
        if claims.get(LTI+key) != value: raise ValueError('Invalid LTI '+key)
    if ROLE+'Instructor' not in claims.get(LTI+'roles', []): raise ValueError('Instructor launch required for this demo workflow.')
    if not claims.get(LTI+'context', {}).get('id') or not claims.get(LTI+'resource_link', {}).get('id'): raise ValueError('Missing launch context/resource.')
    with store.transaction() as db:
        if store.get('nonce', nonce, con=db): raise ValueError('LTI launch replay detected.')
        store.put('nonce', nonce, {'used': store.now()}, db)
    return claims

def sync_lms(sid, course_id, base=BASE):
    context = student_context(sid)
    if not context or course_id not in {c['sourcedId'] for c in context['classes']}: raise ValueError('This student is not enrolled in the selected course.')
    nonce, state = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    response = requests.get(base+'/mock/launch', params={'context': course_id, 'nonce': nonce, 'state': state}, timeout=15)
    response.raise_for_status(); launch = response.json()
    keys = requests.get(base+'/.well-known/jwks.json', timeout=15); keys.raise_for_status()
    claims = validate_launch(launch['id_token'], keys.json(), nonce, launch['state'], state, base)
    if claims[LTI+'context']['id'] != course_id: raise ValueError('Launch returned a different course.')
    for url in [claims[NRPS]['context_memberships_url'], claims[AGS]['lineitems']]: _same_origin(url, base)
    assertion = jwt.encode({'iss': CLIENT, 'sub': CLIENT, 'aud': base+'/oauth/token', 'iat': int(time.time()),
                            'exp': int(time.time())+120, 'jti': uuid.uuid4().hex, 'demo_context': course_id}, keypair('tool'), algorithm='RS256')
    response = requests.post(base+'/oauth/token', data={'grant_type': 'client_credentials', 'scope': ' '.join(SCOPES),
                             'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer', 'client_assertion': assertion}, timeout=15)
    response.raise_for_status(); token = response.json()['access_token']
    members = _pages(claims[NRPS]['context_memberships_url'], token, 'members', base, 'application/vnd.ims.lti-nrps.v2.membershipcontainer+json')
    learner = next((m for m in members if m.get('lis_person_sourcedid') == context['link']['sourced_id'] and ROLE+'Learner' in m['roles'] and m.get('status', 'Active') == 'Active'), None)
    if not learner: raise ValueError('No active NRPS learner matches the linked SIS identifier. No evidence was imported.')
    lineitems = _pages(claims[AGS]['lineitems'], token, base=base, media='application/vnd.ims.lis.v2.lineitemcontainer+json')
    records = []
    for item in lineitems:
        results = _pages(item['id']+'/results', token, base=base, media='application/vnd.ims.lis.v2.resultcontainer+json')
        for result in results:
            if result['userId'] != learner['user_id']: continue
            key = hashlib.sha256((sid+'|'+item['id']+'|'+learner['user_id']).encode()).hexdigest()
            records.append({'id': key, 'student_id': sid, 'sis_id': context['link']['sourced_id'], 'kind': 'lti_result',
                            'course_id': course_id, 'course': claims[LTI+'context']['title'], 'source': 'LTI Advantage AGS result',
                            'label': item['label'], 'score': result.get('resultScore'), 'maximum': result.get('resultMaximum'),
                            'observation': result.get('comment', ''), 'fetched_at': store.now(), 'source_url': item['id'], 'synthetic': True})
    # Replace a course snapshot, including an empty result set, so deletions cannot linger.
    store.put('lms', sid+'|'+course_id, {'id': sid+'|'+course_id, 'student_id': sid, 'course_id': course_id,
              'sis_id': context['link']['sourced_id'], 'records': records, 'members': members, 'synced_at': store.now(),
              'launch': {'issuer': claims['iss'], 'deployment': DEPLOYMENT, 'context': claims[LTI+'context'], 'verified': True}})
    return records

def submit_report(sid, course_id, reporter, accommodation, usage, effectiveness, observation, period_start, period_end):
    context = student_context(sid)
    course = next((c for c in (context or {}).get('classes', []) if c['sourcedId'] == course_id), None)
    if not course: raise ValueError('Choose a linked course.')
    if not all(str(x).strip() for x in [reporter, accommodation, usage, effectiveness, observation]): raise ValueError('Complete all report fields.')
    start, end = dt.date.fromisoformat(str(period_start)), dt.date.fromisoformat(str(period_end))
    if start > end: raise ValueError('Reporting period ends before it starts.')
    key = uuid.uuid4().hex
    report = {'id': key, 'student_id': sid, 'sis_id': context['link']['sourced_id'], 'kind': 'report', 'course_id': course_id,
              'course': course['title'], 'reporter': reporter.strip(), 'accommodation': accommodation.strip(), 'usage': usage,
              'effectiveness': effectiveness, 'observation': observation.strip(), 'period_start': str(start), 'period_end': str(end),
              'fetched_at': store.now(), 'source': 'App-owned course accommodation report (self-identified demo author)', 'synthetic': True}
    store.put('report', key, report)
    return key

def evidence(sid):
    context = student_context(sid)
    if not context: return []
    courses = {c['sourcedId'] for c in context['classes']}; sis_id = context['link']['sourced_id']
    reports = [r for r in store.all_records('report') if r['student_id'] == sid and r['sis_id'] == sis_id and r['course_id'] in courses]
    snapshots = [s for s in store.all_records('lms') if s['student_id'] == sid and s['sis_id'] == sis_id and s['course_id'] in courses]
    return sorted(reports + [r for s in snapshots for r in s['records']], key=lambda r: (r['course'], r['fetched_at']))

def evidence_context(sid, limit_chars=16000):
    records = evidence(sid)
    parts, used, omitted = [], [], []
    for item in records:
        tag = f"E{len(used)+1}"
        text = f'[{tag}] ' + json.dumps(item, ensure_ascii=False)
        if sum(map(len, parts)) + len(text) > limit_chars: omitted.append(item['id']); continue
        parts.append(text); used.append({**item, 'citation': tag})
    if omitted: parts.append(f'{len(omitted)} additional evidence records omitted by the context budget; no inference about them is justified.')
    return '\n\n'.join(parts) or 'No connected course evidence.', used, omitted

def aggregate_reports(sid):
    groups = {}
    for r in evidence(sid):
        if r['kind'] != 'report': continue
        key = r['accommodation'].strip().casefold()
        group = groups.setdefault(key, {'Accommodation': r['accommodation'], 'Reports': 0, 'Courses': set(), 'Outcomes': set(), 'Usage': set()})
        group['Reports'] += 1; group['Courses'].add(r['course']); group['Outcomes'].add(r['effectiveness']); group['Usage'].add(r['usage'])
    return [{**g, 'Courses': ', '.join(sorted(g['Courses'])), 'Outcomes': ', '.join(sorted(g['Outcomes'])),
             'Usage': ', '.join(sorted(g['Usage'])), 'Mixed observations': len(g['Outcomes']) > 1} for g in groups.values()]
