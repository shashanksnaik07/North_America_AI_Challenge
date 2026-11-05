"""A small upper ontology plus IEP specializations and source-template crosswalks.

The legacy Alabama record remains an interoperable projection. Template-specific
fields are retained under extensions rather than dropped by that projection.
"""
import copy
import json
from pathlib import Path
import re
import uuid
import jsonschema

ROOT = Path(__file__).parent
NS = 'https://example.org/iep-ontology/'
CLASSES = {
    'Entity': None, 'Agent': 'Entity', 'Person': 'Agent', 'Organization': 'Agent',
    'InformationArtifact': 'Entity', 'Plan': 'InformationArtifact', 'Assertion': 'InformationArtifact',
    'Evidence': 'InformationArtifact', 'Activity': 'Entity', 'Observation': 'Activity',
    'Decision': 'Activity', 'TimeInterval': 'Entity', 'Location': 'Entity',
    'Student': 'Person', 'Stakeholder': 'Person', 'Course': 'Activity',
    'IEP': 'Plan', 'Goal': 'Plan', 'Service': 'Activity', 'Accommodation': 'Plan',
    'Assessment': 'Observation', 'CourseReport': 'Evidence', 'SourceDocument': 'Evidence',
    'Placement': 'Assertion', 'Eligibility': 'Assertion', 'ReviewDecision': 'Decision',
    'Template': 'InformationArtifact', 'FieldBinding': 'InformationArtifact',
}
# Concept, record path, terms used to locate corresponding sections in source PDFs.
CONCEPTS = [
    ('Student', 'student_name', ['student name', "student’s name", "student's name", 'name of student']),
    ('Assessment', 'profile.evaluation_results', ['evaluation results', 'evaluations', 'assessment results']),
    ('Assertion', 'profile.needs', ['present levels', 'present level', 'functional needs', 'plaafp']),
    ('Assertion', 'profile.strengths', ['strengths of', 'student strengths', 'strengths']),
    ('Assertion', 'profile.parent_concerns', ['parental concerns', 'parent concerns', 'concerns of the parent']),
    ('Goal', 'goals', ['annual goal', 'measurable goal']),
    ('Service', 'services.special_education', ['special education', 'specially designed instruction']),
    ('Service', 'services.related_services', ['related services', 'related service']),
    ('Accommodation', 'services.supplementary_aids', ['accommodations', 'supplementary aids', 'supplemental aids']),
    ('Placement', 'lre', ['least restrictive', 'educational placement', 'placement']),
    ('Plan', 'transition', ['transition']),
    ('Observation', 'progress_report_weeks', ['reporting progress', 'progress report', 'progress monitoring']),
    ('Stakeholder', 'participants', ['participants', 'team members', 'attended', 'attendance']),
    ('Eligibility', 'meta.eligibility', ['eligibility', 'disability']),
    ('Assertion', 'copies.rights_given', ['procedural safeguards', 'special education rights', 'parent rights']),
    ('Accommodation', 'extensions.emergency_evacuation', ['emergency evacuation']),
]

def catalog():
    path = ROOT / 'templates' / 'catalog.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else []

def template(template_id):
    return next((t for t in catalog() if t['id'] == template_id), {'id': 'custom', 'title': 'Custom uploaded IEP', 'crosswalk': []})


def template_schema(template_id, con=None):
    from local_store import get
    fields = get('template_design', template_id, {'fields': []}, con)['fields']
    schema = record_schema()
    schema['properties']['extensions'] = {
        'type': 'object', 'properties': {f['key']: {'type': [f['type'], 'null'],
        'title': f['label'], 'x-ontology-concept': f['concept']} for f in fields},
        'additionalProperties': True}
    return schema

def leaf_fields(value, prefix=''):
    """Include false, null and empty fields; unlike the prompt's text-only helper."""
    out = {}
    if isinstance(value, dict):
        for key, item in value.items():
            out.update(leaf_fields(item, f'{prefix}.{key}' if prefix else key))
    elif isinstance(value, list) and value:
        for index, item in enumerate(value):
            out.update(leaf_fields(item, f'{prefix}.{index}'))
    else:
        out[prefix] = value
    return out

def text(value):
    if value is None: return '(unanswered)'
    if isinstance(value, bool): return 'Yes' if value else 'No'
    if isinstance(value, (dict, list)): return json.dumps(value, ensure_ascii=False)
    return str(value)

def concept_for(path):
    return next((c for c, p, _ in CONCEPTS if path == p or path.startswith(p + '.')), 'Assertion')

def canonical(iep, student_id, template_id='custom', evidence=()):
    import pdf_workspace
    import local_store
    document = pdf_workspace.student_document(student_id)
    if document: template_id = document['template_id']
    design = local_store.get('template_design', template_id, {'fields': []})
    extension_types = {'extensions.'+f['key']: f['concept'] for f in design['fields']}
    nodes = [{'id': f'student:{student_id}', 'type': 'Student', 'label': iep['student_name']},
             {'id': f'iep:{student_id}', 'type': 'IEP', 'subject': f'student:{student_id}', 'usesTemplate': f'template:{template_id}'},
             {'id': f'template:{template_id}', 'type': 'Template', 'label': template(template_id)['title']}]
    for path, value in leaf_fields(iep).items():
        nodes.append({'id': f'iep:{student_id}#{path}', 'type': extension_types.get(path, concept_for(path)), 'partOf': f'iep:{student_id}',
                      'path': path, 'value': value})
    nodes.extend({'id': f"evidence:{e['id']}", 'type': 'CourseReport' if e.get('kind') == 'report' else 'Evidence',
                  'subject': f'student:{student_id}', 'value': e} for e in evidence)
    if document:
        doc_id = f"document:{document['sha256']}"
        nodes.append({'id': doc_id, 'type': 'SourceDocument', 'subject': f'student:{student_id}',
                      'sha256': document['sha256'], 'label': document['filename']})
        for path, bindings in document['bindings'].items():
            nodes.append({'id': doc_id+'#'+path, 'type': 'FieldBinding', 'partOf': doc_id, 'path': path, 'value': bindings})
    context = {'@vocab': NS, 'type': '@type', 'id': '@id'}
    context.update({key: {'@type': '@id'} for key in ['subject', 'partOf', 'usesTemplate', 'supportedBy', 'performedBy', 'occursDuring', 'occursAt']})
    result = {'schemaVersion': '1.0', '@context': context, 'nodes': nodes}
    jsonschema.validate(result, graph_schema())
    return result

def graph_schema():
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'type': 'object',
            'required': ['schemaVersion', '@context', 'nodes'], 'properties': {
                'schemaVersion': {'const': '1.0'}, '@context': {'type': 'object'},
                'nodes': {'type': 'array', 'items': {'type': 'object', 'required': ['id', 'type'],
                    'properties': {'id': {'type': 'string'}, 'type': {'enum': list(CLASSES)},
                                   'path': {'type': 'string'}, 'subject': {'type': 'string'}}}}}}

def record_schema():
    import iep_schema as S
    def shape(value):
        if isinstance(value, dict):
            return {'type': 'object', 'properties': {k: shape(v) for k, v in value.items()},
                    'required': list(value), 'additionalProperties': False}
        if isinstance(value, list): return {'type': 'array'}
        if value is None: return {'type': ['boolean', 'null']}
        if isinstance(value, bool): return {'type': 'boolean'}
        return {'type': 'string'}
    schema = shape(S.empty_iep())
    schema['$schema'] = 'https://json-schema.org/draft/2020-12/schema'
    schema['properties']['extensions'] = {'type': 'object', 'additionalProperties': {'type': ['string', 'number', 'boolean', 'null', 'array', 'object']}}
    schema['properties']['goals']['items'] = shape(S.empty_goal())
    for category in schema['properties']['services']['properties'].values():
        category['properties']['rows']['items'] = shape(S.empty_service())
    return schema

def turtle():
    lines = ['@prefix iep: <' + NS + '> .', '@prefix owl: <http://www.w3.org/2002/07/owl#> .',
             '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .', 'iep: a owl:Ontology .']
    for name, parent in CLASSES.items():
        lines.append(f'iep:{name} a owl:Class' + (f'; rdfs:subClassOf iep:{parent}' if parent else '') + ' .')
    for relation, domain, target in [('subject', 'InformationArtifact', 'Entity'), ('partOf', 'Entity', 'Entity'),
                                    ('supportedBy', 'Assertion', 'Evidence'), ('performedBy', 'Activity', 'Agent'),
                                    ('occursDuring', 'Activity', 'TimeInterval'), ('occursAt', 'Activity', 'Location'),
                                    ('usesTemplate', 'IEP', 'Template')]:
        lines.append(f'iep:{relation} a owl:ObjectProperty; rdfs:domain iep:{domain}; rdfs:range iep:{target} .')
    return '\n'.join(lines) + '\n'
