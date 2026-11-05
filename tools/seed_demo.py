"""Populate synthetic course evidence and one pending review without approving edits."""
import copy
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core
import integrations as I
import local_store as store
import pdf_workspace as P
import reviews as R

def seed():
    for sample in sorted((core.APP_DIR/'samples').glob('*.json')):
        sid = core.make_student_id(sample.stem.replace('_', ' '))
        if sid not in core.list_students(): core.load_sample(sample)
    sid='jordan-ellis'; record=core.get_iep(sid)
    if record['student_name'] != 'Jordan Ellis': raise ValueError('Demo student was renamed; refusing to relink it.')
    I.sync_sis('powerschool')
    link = store.get('student_link', sid)
    if link and link['sourced_id'] != 'powerschool:stu-001': raise ValueError('An existing identity link differs; preserve it and seed manually.')
    I.link_student(sid, 'powerschool', 'powerschool:stu-001')
    for course, teacher, outcome, observation in [
        ('math-9', 'Demo math teacher', 'Helpful', 'Synthetic observation: extended time helped Jordan finish algebra practice. Short written directions reduced prompts.'),
        ('english-9', 'Demo English teacher', 'Mixed', 'Synthetic observation: extended time alone did not sustain attention during reading. Chunked passages and planned breaks helped.')]:
        I.sync_lms(sid, 'powerschool:'+course)
        if not any(r.get('reporter') == teacher for r in I.evidence(sid)):
            I.submit_report(sid, 'powerschool:'+course, teacher, 'Extended time', 'Most opportunities', outcome, observation, '2026-10-01', '2026-10-31')
    P.ensure_document(sid, record)
    title = 'Demo: compare accommodation observations across courses'
    if not any(r['title'] == title for r in R.list_reviews(sid)):
        candidate=copy.deepcopy(record)
        candidate['profile']['needs'] = record['profile']['needs'] + '\nSynthetic course reports describe mixed responses to extended time. The team should review task chunking and planned breaks across courses.'
        rid = R.stage_change(sid, candidate, title, 'Demo coordinator', I.evidence(sid))
        print('Pending demo review:', rid)
    print('Demo evidence ready; active IEP content unchanged.')

if __name__ == '__main__': seed()
