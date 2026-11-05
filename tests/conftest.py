import os
from pathlib import Path
import tempfile
import sys
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Never open the user's live Chroma database during tests.
_test_root = tempfile.TemporaryDirectory(prefix='iep-proposed-tests-', ignore_cleanup_errors=True)
os.environ['IEP_DATA_DIR'] = _test_root.name
os.environ['ANONYMIZED_TELEMETRY'] = 'False'

import pytest
import core
import local_store
import pdf_workspace
import mock_platform

@pytest.fixture
def workspace(tmp_path, monkeypatch):
    for module in [core, local_store, pdf_workspace, mock_platform]: monkeypatch.setattr(module, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(core, 'STUDENTS_DIR', tmp_path/'students')
    monkeypatch.setattr(core, 'LOG_FILE', tmp_path/'change_log.json')
    monkeypatch.setattr(core, 'ACC_FILE', tmp_path/'accommodations.json')
    core.STUDENTS_DIR.mkdir()
    local_store.atomic_json(core.ACC_FILE, {'accommodations': []})
    core._cache.clear()
    monkeypatch.setattr(core, '_col', core.chromadb.EphemeralClient().get_or_create_collection('test-'+uuid.uuid4().hex))
    return tmp_path

@pytest.fixture
def record():
    import json
    return core.S.normalize(json.loads((Path(__file__).resolve().parents[1]/'samples/jordan_ellis.json').read_text(encoding='utf-8')))

@pytest.fixture
def original_pdf():
    import io
    from reportlab.pdfgen import canvas
    buffer = io.BytesIO(); page = canvas.Canvas(buffer, pagesize=(612, 792))
    page.setFont('Helvetica', 12)
    page.drawString(40, 750, 'Synthetic IEP original layout')
    page.drawString(40, 710, 'Student: Jordan Ellis')
    page.drawString(40, 650, 'Short reading tasks support attention.')
    page.rect(35, 580, 540, 95)
    page.drawString(40, 550, 'Unchanged footer and layout')
    page.save(); return buffer.getvalue()

@pytest.fixture
def platform(workspace):
    import threading
    server = mock_platform.PlatformServer(('127.0.0.1', 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    yield server
    server.shutdown(); server.server_close(); thread.join(timeout=5)
