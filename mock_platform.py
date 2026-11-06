"""Loopback-only synthetic SIS/LTI platform. A test double, not vendor certification.

python mock_platform.py --port 8502
"""
import argparse
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse, quote
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from local_store import DATA_DIR
import local_store as store

LTI = 'https://purl.imsglobal.org/spec/lti/claim/'
NRPS = 'https://purl.imsglobal.org/spec/lti-nrps/claim/namesroleservice'
AGS = 'https://purl.imsglobal.org/spec/lti-ags/claim/endpoint'
ROLE = 'http://purl.imsglobal.org/vocab/lis/v2/membership#'
SCOPES = ['https://purl.imsglobal.org/spec/lti-nrps/scope/contextmembership.readonly',
          'https://purl.imsglobal.org/spec/lti-ags/scope/lineitem.readonly',
          'https://purl.imsglobal.org/spec/lti-ags/scope/result.readonly']
PROVIDERS = {'powerschool': 'PowerSchool-style demo', 'infinite-campus': 'Infinite Campus-style demo', 'skyward': 'Skyward-style demo'}
CLIENT = 'iep-local-demo'
DEPLOYMENT = 'iep-demo-deployment'

def keypair(name):
    folder = DATA_DIR / 'mock_keys'; folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'{name}.pem'
    if not path.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return serialization.load_pem_private_key(path.read_bytes(), password=None)

def roster(provider):
    if provider in ('dataset-demo','hk-naset-v1'):
        snapshot=store.get('sis','dataset-demo')
        if not snapshot: raise ValueError('Example cohort has not been installed')
        return snapshot
    if provider not in PROVIDERS: raise ValueError('Unknown demo provider')
    def ref(identifier): return {'sourcedId': f'{provider}:{identifier}'}
    common = {'status': 'active', 'dateLastModified': '2026-11-01T00:00:00Z'}
    users = []
    for code, first, last, role, grade in [('stu-001', 'Jordan', 'Ellis', 'student', '09'), ('stu-002', 'Maya', 'Lopez', 'student', '07'),
                                          ('teacher-01', 'Alex', 'Morgan', 'teacher', ''), ('teacher-02', 'Sam', 'Rivera', 'teacher', '')]:
        users.append({**common, 'sourcedId': ref(code)['sourcedId'], 'identifier': code, 'enabledUser': True,
                      'username': code, 'givenName': first, 'familyName': last, 'role': role,
                      'roles': [{'roleType': 'primary', 'role': role, 'org': ref('school')}],
                      'grades': [grade] if grade else [], 'orgs': [ref('school')], 'agents': []})
    classes, courses, enrollments = [], [], []
    for code, title, student, teacher, grade in [('math-9', 'Algebra I', 'stu-001', 'teacher-01', '09'),
                                               ('english-9', 'English 9', 'stu-001', 'teacher-02', '09'),
                                               ('science-7', 'Science 7', 'stu-002', 'teacher-01', '07')]:
        courses.append({**common, 'sourcedId': ref('course-' + code)['sourcedId'], 'title': title, 'courseCode': code,
                        'schoolYear': ref('year'), 'org': ref('school'), 'grades': [grade]})
        classes.append({**common, 'sourcedId': ref(code)['sourcedId'], 'title': title, 'classCode': code, 'classType': 'scheduled',
                        'course': ref('course-' + code), 'school': ref('school'), 'terms': [ref('fall')], 'grades': [grade]})
        for person, role in [(student, 'student'), (teacher, 'teacher')]:
            enrollments.append({**common, 'sourcedId': ref(code + '-' + person)['sourcedId'], 'user': ref(person),
                                'class': ref(code), 'school': ref('school'), 'role': role, 'primary': role == 'teacher',
                                'beginDate': '2026-08-10', 'endDate': '2026-12-18'})
    return {'orgs': [{**common, 'sourcedId': ref('district')['sourcedId'], 'name': 'Synthetic Unified District', 'type': 'district'},
                     {**common, 'sourcedId': ref('school')['sourcedId'], 'name': 'Demonstration School', 'type': 'school', 'parent': ref('district')}],
            'academicSessions': [{**common, 'sourcedId': ref('year')['sourcedId'], 'title': '2026-2027', 'type': 'schoolYear', 'schoolYear': '2027', 'startDate': '2026-08-01', 'endDate': '2027-06-01'},
                                 {**common, 'sourcedId': ref('fall')['sourcedId'], 'title': 'Fall 2026', 'type': 'term', 'schoolYear': '2027', 'startDate': '2026-08-10', 'endDate': '2026-12-18', 'parent': ref('year')}],
            'users': users, 'courses': courses, 'classes': classes, 'enrollments': enrollments}

class PlatformServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address):
        super().__init__(address, Handler)
        self.base = f'http://127.0.0.1:{self.server_port}'
        self.platform_key, self.tool_key = keypair('platform'), keypair('tool')
        self.tokens, self.used_assertions = {}, set()
        self.lock = threading.Lock()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def send_json(self, data, status=200, media='application/json', headers=None):
        payload = json.dumps(data).encode()
        self.send_response(status); self.send_header('Content-Type', media); self.send_header('Content-Length', str(len(payload)))
        for key, value in (headers or {}).items(): self.send_header(key, value)
        self.end_headers(); self.wfile.write(payload)

    def authorized(self, scope, context=None):
        token = self.headers.get('Authorization', '').removeprefix('Bearer ')
        item = self.server.tokens.get(token)
        if not item or item['exp'] < time.time() or scope not in item['scopes']:
            raise PermissionError('Missing, expired or insufficient-scope token.')
        if context and item.get('context') != context: raise PermissionError('Token is not authorized for this course.')

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            if length > 100000: raise ValueError('Request too large')
            args = parse_qs(self.rfile.read(length).decode())
            if self.path != '/oauth/token': return self.send_json({'error': 'not_found'}, 404)
            scope = args.get('scope', [''])[0].split()
            if args.get('grant_type') != ['client_credentials']: raise PermissionError('Use client_credentials.')
            context = None
            if 'client_assertion' in args:
                if args.get('client_assertion_type') != ['urn:ietf:params:oauth:client-assertion-type:jwt-bearer']: raise PermissionError('Invalid assertion type.')
                claims = jwt.decode(args['client_assertion'][0], self.server.tool_key.public_key(), algorithms=['RS256'],
                                    audience=self.server.base + '/oauth/token', issuer=CLIENT, options={'require': ['exp', 'iat', 'jti', 'sub']})
                if claims['sub'] != CLIENT: raise PermissionError('Invalid subject.')
                with self.server.lock:
                    if claims['jti'] in self.server.used_assertions: raise PermissionError('Assertion replay.')
                    self.server.used_assertions.add(claims['jti'])
                context = claims.get('demo_context')
                if not context or not set(scope) <= set(SCOPES): raise PermissionError('Invalid scopes or course.')
            else:
                if args.get('client_id') != [CLIENT] or args.get('client_secret') != ['synthetic-local-secret']:
                    raise PermissionError('Invalid demo credentials.')
                if scope != ['roster.readonly']: raise PermissionError('Invalid SIS scope.')
            token = secrets.token_urlsafe(32)
            self.server.tokens[token] = {'exp': time.time() + 300, 'scopes': scope, 'context': context}
            self.send_json({'access_token': token, 'token_type': 'Bearer', 'expires_in': 300, 'scope': ' '.join(scope)})
        except (PermissionError, jwt.PyJWTError) as exc: self.send_json({'error': str(exc)}, 401)
        except (ValueError, KeyError) as exc: self.send_json({'error': str(exc)}, 400)

    def do_GET(self):
        try:
            parsed = urlparse(self.path); path = parsed.path; query = parse_qs(parsed.query)
            if path == '/health': return self.send_json({'status': 'ok', 'service': 'iep-synthetic-platform', 'mock': True})
            if path == '/.well-known/jwks.json':
                key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.server.platform_key.public_key()))
                key.update(kid='demo-platform', use='sig', alg='RS256')
                return self.send_json({'keys': [key]})
            if path == '/mock/launch':
                context = query['context'][0]; provider = context.split(':')[0]
                course = next(c for c in roster(provider)['classes'] if c['sourcedId'] == context)
                instructor = next(e['user']['sourcedId'] for e in roster(provider)['enrollments'] if e['class']['sourcedId'] == context and e['role'] == 'teacher')
                claims = {'iss': self.server.base, 'aud': CLIENT, 'sub': instructor, 'iat': int(time.time()),
                          'exp': int(time.time()) + 180, 'nonce': query['nonce'][0],
                          LTI+'version': '1.3.0', LTI+'message_type': 'LtiResourceLinkRequest', LTI+'deployment_id': DEPLOYMENT,
                          LTI+'target_link_uri': 'http://127.0.0.1:8501/', LTI+'resource_link': {'id': context + ':iep'},
                          LTI+'roles': [ROLE+'Instructor'], LTI+'context': {'id': context, 'label': course['classCode'], 'title': course['title']},
                          NRPS: {'context_memberships_url': self.server.base + f'/lti/contexts/{context}/memberships', 'service_versions': ['2.0']},
                          AGS: {'scope': SCOPES[1:], 'lineitems': self.server.base + f'/lti/contexts/{context}/lineitems'}}
                return self.send_json({'id_token': jwt.encode(claims, self.server.platform_key, algorithm='RS256', headers={'kid': 'demo-platform'}), 'state': query['state'][0]})
            if '/ims/oneroster/rostering/v1p2/' in path:
                self.authorized('roster.readonly')
                provider = path.split('/')[2]; resource = path.rsplit('/', 1)[1]
                values = roster(provider)[resource]
                start = max(0, int(query.get('offset', ['0'])[0])); limit = min(100, max(1, int(query.get('limit', ['2'])[0])))
                headers = {}
                if start + limit < len(values): headers['Link'] = f'<{self.server.base}{path}?offset={start+limit}&limit={limit}>; rel="next"'
                return self.send_json({resource: values[start:start+limit]}, headers=headers)
            if path.startswith('/lti/contexts/'):
                parts = path.split('/'); context = parts[3]; provider = context.split(':')[0]; resource = parts[4]
                data = roster(provider)
                course = next(c for c in data['classes'] if c['sourcedId'] == context)
                enrolled = [e for e in data['enrollments'] if e['class']['sourcedId'] == context]
                if resource == 'memberships':
                    self.authorized(SCOPES[0], context)
                    members = [{'status': 'Active', 'user_id': e['user']['sourcedId'] + ':lti', 'lis_person_sourcedid': e['user']['sourcedId'],
                                'roles': [ROLE + ('Learner' if e['role'] == 'student' else 'Instructor')],
                                'name': next(u['givenName']+' '+u['familyName'] for u in data['users'] if u['sourcedId'] == e['user']['sourcedId'])} for e in enrolled]
                    offset = int(query.get('offset', ['0'])[0]); headers = {}
                    if offset+1 < len(members): headers['Link'] = f'<{self.server.base}{path}?offset={offset+1}>; rel="next"'
                    return self.send_json({'id': self.server.base+path, 'context': {'id': context, 'title': course['title']}, 'members': members[offset:offset+1]}, media='application/vnd.ims.lti-nrps.v2.membershipcontainer+json', headers=headers)
                if resource == 'lineitems':
                    if len(parts) == 5:
                        self.authorized(SCOPES[1], context)
                        gradebook=store.get('mock_gradebook',context)
                        items=gradebook['items'] if gradebook else [{'key':'task-1','label':course['title']+' supported practice','scoreMaximum':100}]
                        return self.send_json([{'id':self.server.base+path+'/'+i['key'],'label':i['label'],'scoreMaximum':i['scoreMaximum'],
                                                'resourceLinkId':context+':iep','tag':'example'} for i in items],media='application/vnd.ims.lis.v2.lineitemcontainer+json')
                    if len(parts) == 7 and parts[6] == 'results':
                        self.authorized(SCOPES[2], context)
                        students = [e for e in enrolled if e['role'] == 'student']
                        teacher=next(e['user']['sourcedId']+':lti' for e in enrolled if e['role']=='teacher')
                        results = [{'id': self.server.base+path+'/'+e['user']['sourcedId'], 'userId': e['user']['sourcedId']+':lti',
                                    'resultScore': 78 if 'math' in context else 86, 'resultMaximum': 100,
                                    'scoringUserId':teacher,'comment':'Extended time was used; the task was completed with prompts.'} for e in students]
                        gradebook=store.get('mock_gradebook',context)
                        if gradebook:
                            entry=next(i for i in gradebook['items'] if i['key']==parts[5])
                            results=[{**r,'id':self.server.base+path+'/'+r['userId'],'scoreOf':self.server.base+path.rsplit('/results',1)[0]} for r in entry['results']]
                        elif parts[5]!='task-1': raise ValueError('Unknown line item')
                        user_id = query.get('user_id', [None])[0]
                        return self.send_json([r for r in results if user_id is None or r['userId'] == user_id], media='application/vnd.ims.lis.v2.resultcontainer+json')
            return self.send_json({'error': 'not_found'}, 404)
        except (PermissionError, jwt.PyJWTError) as exc: self.send_json({'error': str(exc)}, 401)
        except (ValueError, KeyError, StopIteration) as exc: self.send_json({'error': str(exc)}, 400)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--port', type=int, default=8502)
    args = parser.parse_args()
    print(f'Synthetic SIS/LTI platform on http://127.0.0.1:{args.port}', flush=True)
    PlatformServer(('127.0.0.1', args.port)).serve_forever()
