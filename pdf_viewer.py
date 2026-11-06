"""Continuous PDF preview. Navigation stays in the browser; edits use review services."""
import base64
from pathlib import Path

import pymupdf as fitz
import streamlit as st
import streamlit.components.v1 as components
import pdf_workspace as P

viewer = components.declare_component(
    'iep_pdf_viewer', path=str(Path(__file__).parent / 'components' / 'pdf_viewer'))


def preview_pages(data, bindings, labels=()):
    """Open once, preserving displayed page geometry, including added PDF pages.

    Browsers lazily decode the images. Field rectangles are in display coordinates
    so rotated pages use the same hit targets and review marks as ordinary pages.
    """
    by_page = {}
    for path, regions in bindings.items():
        for region in regions:
            by_page.setdefault(region['page'], []).append((path, region['rect']))
    pages = []
    with fitz.open(stream=data, filetype='pdf') as pdf:
        for index, page in enumerate(pdf):
            # Bound raster memory for unusually large source pages.
            scale = min(1.5, 1800 / max(page.rect.width, page.rect.height))
            png = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes('png')
            pages.append({
                'image': base64.b64encode(png).decode(),
                'width': page.rect.width, 'height': page.rect.height,
                'label': labels[index] if index < len(labels) else f'Page {index + 1}',
                'fields': [{'path': path, 'rect': list(fitz.Rect(rect) * page.rotation_matrix)}
                           for path, rect in by_page.get(index, [])],
            })
    return pages


@st.cache_data(max_entries=6, show_spinner=False)
def document_preview(source, document, record=None, append_unmapped=True):
    # Cache by source and record, not regenerated PDF bytes (their IDs can vary).
    # The caller verifies source integrity before entering this cache.
    data = source if record is None else P.render_document(document, record, append_unmapped)[0]
    return P.digest(data), preview_pages(data, document['bindings'], document.get('page_labels', []))
