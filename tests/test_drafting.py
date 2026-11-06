import copy
import json
import pytest
import core
import drafting as D
import pdf_workspace as P
import reviews as R
import workspace_state as W
import local_store as store


def student(record,original_pdf):
    sid=core.create_student(record)
    P.save_document(sid,P.archive_source(original_pdf,record,'original.pdf'))
    return sid


def option(sid,record,path,text):
    return D.stamp([core._make_change(record,path,text,'Course evidence','teacher note')],D.basis(sid))[0]


def test_related_changes_share_one_review_and_one_history_version(workspace,record,original_pdf):
    sid=student(record,original_pdf)
    items=[option(sid,record,'grade','10'),option(sid,record,'profile.needs','Use a private checkpoint during independent work.')]
    D.submit(sid,items,'Morgan Lee')
    assert core.get_iep(sid)==record
    reviews=R.list_reviews(sid);assert len(reviews)==1
    R.decide(reviews[0]['id'],'approved','Morgan Lee','Case manager',True)
    assert core.get_iep(sid)['grade']=='10'
    assert core.get_iep(sid)['profile']['needs']==items[1]['suggested_text']
    assert len(core.list_versions(sid))==1


def test_stale_queue_and_reset_generation_cannot_submit(workspace,record,original_pdf):
    sid=student(record,original_pdf);item=option(sid,record,'grade','10')
    changed=copy.deepcopy(record);changed['profile']['needs']='A newer approved plan.'
    core.save_iep(sid,changed)
    with pytest.raises(ValueError,match='IEP changed'):D.submit(sid,[item])
    core.save_iep(sid,record)
    store.atomic_json(workspace/'workspace_generation.json',{'id':'reset'})
    with pytest.raises(ValueError,match='workspace was reset'):D.submit(sid,[item])
    assert not R.list_reviews(sid)


def test_other_student_or_changed_pdf_rejects_queued_option(workspace,record,original_pdf):
    sid=student(record,original_pdf);item=option(sid,record,'grade','10')
    other=copy.deepcopy(record);other['student_name']='Other Student';other_sid=core.create_student(other)
    with pytest.raises(ValueError,match='different student'):D.submit(other_sid,[item])
    document=P.student_document(sid);document['filename']='replacement.pdf';P.save_document(sid,document)
    with pytest.raises(ValueError,match='source PDF changed'):D.submit(sid,[item])


def test_conflicting_options_and_duplicate_review_are_rejected(workspace,record,original_pdf):
    sid=student(record,original_pdf);a=option(sid,record,'grade','10');b=option(sid,record,'grade','11')
    with pytest.raises(ValueError,match='same field'):D.submit(sid,[a,b])
    assert not R.list_reviews(sid)
    D.submit(sid,[a,a])
    with pytest.raises(ValueError,match='already saved'):D.submit(sid,[a])
    assert len(R.list_reviews(sid))==1


def test_new_service_has_editable_pdf_region_and_requires_delivery_details(workspace,record,original_pdf):
    import pdf_viewer as V
    sid=student(record,original_pdf)
    item=core._make_service(record,'supplementary_aids',{'service':'Private checkpoint'},'Observation','teacher note')
    item=D.stamp([item],D.basis(sid))[0]
    with pytest.raises(ValueError,match='Complete when'):D.submit(sid,[item])
    item['payload'].update(frequency='Each independent task',amount='Two minutes',location='Mathematics')
    D.submit(sid,[item]);review=R.list_reviews(sid)[0]
    redlines=V.review_redlines(review['document'],review['base'],review['candidate'])
    assert any('Private checkpoint' in token['text'] and token['kind']=='insert' for line in redlines for token in line['tokens'])
    assert P.render_document(review['document'],review['candidate'])[1]==[]
    assert P.source_bytes(P.student_document(sid))==original_pdf
    R.decide(review['id'],'approved','Reviewer','Case manager',True)
    assert core.get_iep(sid)['services']['supplementary_aids']['rows'][-1]['location']=='Mathematics'


def test_long_wording_gets_space_before_review_and_corrections_can_grow(workspace,record,original_pdf):
    import pymupdf
    sid=student(record,original_pdf)
    item=option(sid,record,'student_name','Jordan Ellis '+('extended wording ' * 25))
    D.submit(sid,[item]);review=R.list_reviews(sid)[0]
    assert len(review['document']['page_labels'])>1
    revised=copy.deepcopy(review['candidate']);revised['student_name']+='additional context '*30
    R.update_candidate(review['id'],revised,'Reviewer',1)
    review=R.get(review['id']);data,unmapped=P.render_document(review['document'],review['candidate'])
    assert not unmapped
    with pymupdf.open(stream=data,filetype='pdf') as pdf:assert 'additional context' in ''.join(page.get_text() for page in pdf)
    assert P.source_bytes(P.student_document(sid))==original_pdf


def test_noop_and_malformed_model_fields_do_not_become_drafts(workspace,record,original_pdf,monkeypatch):
    sid=student(record,original_pdf)
    assert core._make_change(record,'grade',record['grade'],'','') is None
    assert core._make_service(record,'supplementary_aids',{'service':None},'','') is None
    assert core._make_goal(record,{'goal':None},'','') is None
    monkeypatch.setattr(core,'recommend_accommodations',lambda *a,**k:[])
    monkeypatch.setattr(core,'_context',lambda *a:('',[]))
    for response in ['not JSON','[]','{"suggestions":{}}','{"suggestions":[{"action":"change","field":"student_name","new_value":"Wrong person"}]}']:
        monkeypatch.setattr(core,'_chat',lambda *a,**k:response)
        with pytest.raises(ValueError):core.suggest_updates(sid,'Review course evidence')
    assert not R.list_reviews(sid)


def test_reset_blocks_a_decision_from_an_old_session(workspace,record,original_pdf):
    sid=student(record,original_pdf);changed=copy.deepcopy(record);changed['grade']='10'
    rid=R.stage_change(sid,changed,'Grade')
    generation=W.generation();store.atomic_json(workspace/'workspace_generation.json',{'id':'reset'})
    with pytest.raises(ValueError,match='workspace was reset'):
        R.decide(rid,'approved','Reviewer','Case manager',True,expected_generation=generation)
    assert core.get_iep(sid)==record and R.get(rid)['status']=='pending'


def test_continuation_keeps_native_form_values_and_original_bytes(workspace,record):
    import io
    import pymupdf as fitz
    from pypdf import PdfReader
    with fitz.open() as pdf:
        page=pdf.new_page(width=612,height=792)
        widget=fitz.Widget();widget.field_type=fitz.PDF_WIDGET_TYPE_TEXT
        widget.field_name='student-name';widget.field_value=record['student_name']
        widget.rect=fitz.Rect(40,60,240,82);widget.text_fontsize=10
        page.add_widget(widget);original=pdf.tobytes()
    sid=student(record,original)
    item=option(sid,record,'student_name','Jordan Ellis '+('longer wording '*25))
    D.submit(sid,[item]);review=R.list_reviews(sid)[0]
    output,_=P.render_document(review['document'],review['candidate'])
    assert P.source_bytes(review['document']['original_source'])==original
    fields=PdfReader(io.BytesIO(output)).get_fields();assert fields
    canonical=fields['student-name']['/V'];assert 'p.' in canonical or 'page' in canonical
    with fitz.open(stream=output,filetype='pdf') as pdf:
        widget=next(pdf[0].widgets());assert widget.field_value==canonical
        assert pdf.xref_get_key(widget.xref,'AP')[0]!='null'
        assert 'longer wording' in pdf[-1].get_text()
