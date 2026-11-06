"""Continuous PDF preview. Navigation stays in the browser; edits use review services."""
import base64
from pathlib import Path

import pymupdf as fitz
import streamlit as st
import streamlit.components.v1 as components
import pdf_workspace as P
import iep_schema as S
import reviews as R

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


def review_redlines(document, before, after):
    """Attach full word diffs to each mapped region, never to a guessed position."""
    from native_templates import display_value
    result = []
    keys = sorted({P.binding_key(document, change['path']) for change in P.changes(before, after)} - {None})
    def value(record, key):
        try: return S.get_path(record, key)
        except (KeyError, IndexError, TypeError): return None
    def formatted(value, binding):
        text = display_value(value) if value is not None else ''
        if binding.get('name_part') == 'first': text = text.split(' ', 1)[0]
        elif binding.get('name_part') == 'last': text = text.split(' ', 1)[-1]
        if binding.get('year_part') == 'start': text = text.split('-', 1)[0]
        elif binding.get('year_part') == 'end': text = text.split('-', 1)[-1]
        if text and binding.get('suffix'): text += binding['suffix']
        return text
    with fitz.open(stream=P.source_bytes(document), filetype='pdf') as pdf:
        for key in keys:
            for binding in document['bindings'][key]:
                tokens = R.diff_tokens(formatted(value(before, key), binding), formatted(value(after, key), binding))
                # A split first/last name or year field may be unchanged on this page.
                if not any(t['kind'] != 'equal' for t in tokens): continue
                result.append({'path':key, 'label':S.label_for(key), 'page':binding['page'],
                    'rect':list(fitz.Rect(binding['rect']) * pdf[binding['page']].rotation_matrix),
                    'tokens':tokens, 'continuation_page':binding.get('continuation_page')})
    return result


def continuation_notice(document):
    """Explain generated supplement pages separately from original NASET pages."""
    native = document.get('native_template_pages')
    total = len(document.get('page_labels', []))
    if native and total > native:
        with st.expander(f'About the {total-native} app-added pages'):
            st.write(f'Pages 1–{native} use the original NASET form. Pages {native+1}–{total} were added by this app for '
                     'text overflow and plan fields that are not yet mapped to a box on the original form. '
                     'They are not pages from the NASET template.')
