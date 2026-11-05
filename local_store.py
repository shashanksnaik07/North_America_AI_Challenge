"""Small, transactional local store for review records and integration snapshots."""
import contextlib
import datetime as dt
import json
import os
from pathlib import Path
import sqlite3

DATA_DIR = Path(os.environ.get('IEP_DATA_DIR', Path(__file__).parent / 'data'))

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')

@contextlib.contextmanager
def transaction():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DATA_DIR / 'workspace.sqlite3', timeout=30)
    try:
        con.execute('CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, body TEXT, PRIMARY KEY(kind,id))')
        con.execute('BEGIN IMMEDIATE')
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

def get(kind, key, default=None, con=None):
    if con is None:
        with transaction() as db:
            return get(kind, key, default, db)
    row = con.execute('SELECT body FROM records WHERE kind=? AND id=?', (kind, key)).fetchone()
    return json.loads(row[0]) if row else default

def put(kind, key, value, con=None):
    if con is None:
        with transaction() as db:
            return put(kind, key, value, db)
    con.execute('INSERT OR REPLACE INTO records VALUES (?,?,?)', (kind, key, json.dumps(value, ensure_ascii=False)))

def all_records(kind, con=None):
    if con is None:
        with transaction() as db:
            return all_records(kind, db)
    return [json.loads(r[0]) for r in con.execute('SELECT body FROM records WHERE kind=? ORDER BY id', (kind,))]

def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)
