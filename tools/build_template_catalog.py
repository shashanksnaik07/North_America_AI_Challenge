"""Refresh NASET source metadata and candidate semantic crosswalks; PDFs stay ignored.
Run with the dev requirements installed. No student data is used.
"""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
from bs4 import BeautifulSoup
import pymupdf
import ontology

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://www.naset.com/ieps-from-around-the-country/'

def build():
    response = requests.get(URL, timeout=45); response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    links = soup.select('a.iep-download-btn')
    records = []
    cache = ROOT / 'data' / 'reference'; cache.mkdir(parents=True, exist_ok=True)
    for index, link in enumerate(links):
        parent = link.parent
        while parent and not parent.find('h3'): parent = parent.parent
        title = parent.find('h3').get_text(' ', strip=True)
        state_node = parent.select_one('.iep-state-badge')
        state = state_node.get_text(' ', strip=True) if state_node else title.split()[0]
        meta = parent.get_text(' ', strip=True)
        date = re.search(r'Form date:\s*(.*?)\s*Type:', meta)
        item_id = re.sub('[^a-z0-9]+', '-', title.lower()).strip('-')
        records.append({'id': item_id, 'state': state, 'title': title, 'form_date': date.group(1) if date else 'See source',
                        'form_type': meta.split('Type:', 1)[-1].replace('View IEP Template', '').strip(),
                        'url': link['href'], 'catalog_url': URL, 'retrieved': '2026-11-05', 'crosswalk_status': 'candidate; reviewer confirms field bindings'})
    def fetch(item):
        try:
            path = cache / (item['id'] + '.pdf')
            if not path.exists():
                r = requests.get(item['url'], timeout=60); r.raise_for_status(); path.write_bytes(r.content)
            data = path.read_bytes()
            with pymupdf.open(stream=data, filetype='pdf') as doc:
                pages = [page.get_text().lower() for page in doc]
                item['extraction_method'] = 'native PDF text'
                if sum(map(len, pages)) < 100:
                    import os
                    import pytesseract
                    from PIL import Image
                    if os.name == 'nt':
                        for root in [os.environ.get('LOCALAPPDATA', '')+'/Programs/Tesseract-OCR', os.environ.get('ProgramFiles', '')+'/Tesseract-OCR']:
                            binary = Path(root)/'tesseract.exe'
                            if binary.exists(): pytesseract.pytesseract.tesseract_cmd = str(binary); break
                    text_cache = cache/(item['id']+'.ocr.json')
                    if text_cache.exists(): pages = json.loads(text_cache.read_text(encoding='utf-8'))
                    else:
                        pages = []
                        for page in doc:
                            pix = page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
                            image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
                            pages.append(pytesseract.image_to_string(image).lower())
                        text_cache.write_text(json.dumps(pages), encoding='utf-8')
                    item['extraction_method'] = 'OCR; all candidate mappings require visual confirmation'
                item['pages'] = len(doc)
                item['sha256'] = hashlib.sha256(data).hexdigest()
                item['crosswalk'] = []
                for concept, field, aliases in ontology.CONCEPTS:
                    evidence = []
                    for page, content in enumerate(pages):
                        normalized = re.sub(r'\s+', ' ', content)
                        alias = next((a for a in aliases if a in normalized), None)
                        if alias: evidence.append({'page': page + 1, 'label': alias})
                    if evidence:
                        item['crosswalk'].append({'concept': concept, 'field': field, 'evidence': evidence})
                item['text_extractable'] = sum(map(len, pages)) > 100
        except Exception as exc:
            item.update(error=str(exc), crosswalk=[])
        return item
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(fetch, records))
    target = ROOT / 'templates'; target.mkdir(exist_ok=True)
    (target / 'catalog.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    (target / 'upper-ontology.ttl').write_text(ontology.turtle(), encoding='utf-8')
    (target / 'canonical.schema.json').write_text(json.dumps(ontology.graph_schema(), indent=2), encoding='utf-8')
    (target / 'iep-record.schema.json').write_text(json.dumps(ontology.record_schema(), indent=2), encoding='utf-8')
    print(json.dumps({'templates': len(records), 'failed': [r['title'] for r in records if r.get('error')],
                      'crosswalks': sum(len(r['crosswalk']) for r in records)}, indent=2))

if __name__ == '__main__': build()
