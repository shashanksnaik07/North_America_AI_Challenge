"""Local, content-addressed snapshots of application data for repeatable recordings.

Student files, history, PDF sources, reviews, integrations, reports, grades and
supporting-document embeddings are captured. Models, reference datasets, server
logs and secrets are not copied. Immutable source PDFs added later stay archived
but become unlinked when their student/review records are restored.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import uuid

import local_store as store
import workspace_state as W

VERSION = 1
LOOSE_FILES = ('accommodations.json', 'change_log.json')


def _root():
    return store.DATA_DIR.resolve() / 'snapshots'


def _encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')


def _object(data):
    sha = hashlib.sha256(data).hexdigest()
    target = _root() / 'objects' / sha
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = target.with_suffix('.tmp')
        temporary.write_bytes(data); temporary.replace(target)
    return sha


def _read_object(sha):
    if not re.fullmatch(r'[0-9a-f]{64}', str(sha)):
        raise ValueError('Invalid snapshot object.')
    data = (_root() / 'objects' / sha).read_bytes()
    if hashlib.sha256(data).hexdigest() != sha:
        raise ValueError('Snapshot integrity check failed. No data was restored.')
    return data


def _manifest(snapshot_id):
    if not re.fullmatch(r'[0-9a-f]{32}', snapshot_id):
        raise ValueError('Invalid snapshot ID.')
    path = _root() / 'manifests' / (snapshot_id + '.json')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if manifest.get('version') != VERSION or manifest.get('id') != snapshot_id:
        raise ValueError('Unsupported snapshot manifest.')
    return manifest


def list_snapshots():
    return sorted([json.loads(p.read_text(encoding='utf-8')) for p in (_root() / 'manifests').glob('*.json')],
                  key=lambda item: item['created'], reverse=True)


@W.guarded
def capture(label):
    import core
    if not label.strip(): raise ValueError('Name this snapshot before saving it.')
    files = {}
    root = store.DATA_DIR.resolve()
    for folder in ('students', 'originals'):
        for path in sorted((root / folder).rglob('*')):
            if path.is_file():
                if path.is_symlink() or not path.resolve().is_relative_to(root):
                    raise ValueError('Cannot snapshot files outside this workspace.')
                files[path.relative_to(root).as_posix()] = _object(path.read_bytes())
    for name in LOOSE_FILES:
        if (root / name).exists(): files[name] = _object((root / name).read_bytes())
    with store.transaction() as db:
        rows = db.execute('SELECT kind,id,body FROM records ORDER BY kind,id').fetchall()
    documents = core._col.get(include=['documents','metadatas','embeddings'])
    vectors = {key: documents.get(key) for key in ('ids','documents','metadatas','embeddings')}
    if hasattr(vectors['embeddings'], 'tolist'): vectors['embeddings'] = vectors['embeddings'].tolist()
    manifest = {'version':VERSION, 'id':uuid.uuid4().hex, 'label':label.strip(), 'created':store.now(),
                'files':files, 'records':_object(_encode(rows)), 'vectors':_object(_encode(vectors)),
                'students':len(core.list_students()), 'reviews':sum(row[0]=='review' for row in rows),
                'supporting_chunks':len(vectors['ids'])}
    store.atomic_json(_root() / 'manifests' / (manifest['id']+'.json'),manifest)
    return manifest


def _safe_target(relative):
    root = store.DATA_DIR.resolve()
    path = Path(relative)
    target = (root / path).resolve()
    if (not path.parts or '..' in path.parts or path.is_absolute() or not target.is_relative_to(root)
            or path.parts[0] not in ('students','originals',*LOOSE_FILES)
            or (path.parts[0] in LOOSE_FILES and len(path.parts)!=1)):
        raise ValueError('Invalid snapshot file location.')
    return target


def _validate(manifest):
    for relative, sha in manifest['files'].items():
        _safe_target(relative); _read_object(sha)
    rows = json.loads(_read_object(manifest['records']))
    for kind, key, body in rows: json.loads(body)
    vectors = json.loads(_read_object(manifest['vectors']))
    if any(len(vectors['ids']) != len(vectors[key] or []) for key in ('documents','metadatas','embeddings')):
        raise ValueError('Incomplete supporting-document snapshot.')
    return rows, vectors


def _install(manifest, rows, vectors):
    import core
    root = store.DATA_DIR.resolve()
    stage = root / ('.restore-' + uuid.uuid4().hex)
    stage.mkdir(); (stage / 'students').mkdir()
    try:
        for relative, sha in manifest['files'].items():
            if relative.startswith('students/'):
                destination = stage / relative
                destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(_root()/'objects'/sha,destination)
        for relative, sha in manifest['files'].items():
            if relative.startswith('originals/'):
                destination = _safe_target(relative)
                if not destination.exists() or hashlib.sha256(destination.read_bytes()).hexdigest()!=sha:
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(_root()/'objects'/sha,destination)
        with store.transaction() as db:
            db.execute('DELETE FROM records')
            db.executemany('INSERT INTO records VALUES (?,?,?)', rows)
            current = root / 'students'
            if current.exists(): current.rename(stage / 'previous-students')
            (stage / 'students').rename(current)
            for name in LOOSE_FILES:
                if name in manifest['files']: shutil.copyfile(_root()/'objects'/manifest['files'][name],root/name)
                elif (root/name).exists(): (root/name).unlink()
            existing = core._col.get()['ids']
            for index in range(0,len(existing),1000): core._col.delete(ids=existing[index:index+1000])
            for index in range(0,len(vectors['ids']),1000):
                core._col.add(**{key:values[index:index+1000] for key,values in vectors.items()})
        core._cache.clear()
    finally:
        # This temporary tree is inside DATA_DIR, never an inferred external path.
        if stage.resolve().parent != root or not stage.name.startswith('.restore-') or stage.is_symlink():
            raise ValueError('Unsafe restore staging directory.')
        shutil.rmtree(stage)


@W.guarded
def restore(snapshot_id):
    """Preflight all content, automatically back up this take, then restore."""
    manifest = _manifest(snapshot_id)
    rows, vectors = _validate(manifest)
    backup = capture('Before reset · ' + manifest['label'])
    try:
        _install(manifest, rows, vectors)
    except Exception:
        backup_rows, backup_vectors = _validate(backup)
        _install(backup, backup_rows, backup_vectors)
        raise
    store.atomic_json(store.DATA_DIR/'workspace_generation.json',{'id':uuid.uuid4().hex,'restored_from':snapshot_id,'at':store.now()})
    return {'restored':manifest,'backup':backup}
