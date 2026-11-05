import json
import jsonschema
from rdflib import Graph
import iep_schema as S
import ontology as O

def test_catalog_crosswalks_and_source_provenance():
    catalog = O.catalog()
    assert len(catalog) == 32 and len({t['id'] for t in catalog}) == 32
    assert 'Rhode Island' in {t['state'] for t in catalog}
    for template in catalog:
        assert template['sha256'] and template['catalog_url'] and template['pages'] > 0
        for crosswalk in template['crosswalk']:
            assert crosswalk['concept'] in O.CLASSES
            assert all(1 <= e['page'] <= template['pages'] for e in crosswalk['evidence'])

def test_upper_ontology_and_canonical_schema(record):
    graph = Graph().parse(data=O.turtle(), format='turtle')
    assert len(graph) > 40
    canonical = O.canonical(record, 'synthetic-student')
    jsonschema.validate(canonical, O.graph_schema())
    assert any(n['type'] == 'Goal' for n in canonical['nodes'])

def test_state_extensions_survive_legacy_projection(record):
    record['extensions'] = {'emergency_evacuation': 'Synthetic evacuation assistance', 'local_consent': True}
    normalized = S.normalize(record)
    assert normalized['extensions'] == record['extensions']
    assert 'evacuation assistance' in S.to_text(normalized)
    jsonschema.validate(normalized, O.record_schema())
