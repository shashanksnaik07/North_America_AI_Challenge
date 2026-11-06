"""Populate measured fields in original NASET pages, with linked overflow."""
import copy
from functools import lru_cache
import io
import json
import re
from pathlib import Path
from xml.sax.saxutils import escape
import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
import iep_schema as S
import ontology as O
import pdf_workspace as P

LAYOUT_VERSION=3
LAYOUTS=Path(__file__).parent/'templates'/'mock_layouts.json'

def layouts():return json.loads(LAYOUTS.read_text(encoding='utf-8'))

def display_value(value):
    if isinstance(value,dict):
        return '\n'.join(k.replace('_',' ').capitalize()+': '+display_value(v) for k,v in value.items() if v not in ('',[],None))
    if isinstance(value,list):return '\n'.join(display_value(v) for v in value)
    return O.text(value)

def fits(rect,value,size=8):
    with fitz.open() as test:
        page=test.new_page(width=max(1000,rect.x1+10),height=max(1000,rect.y1+10))
        return page.insert_textbox(rect,value,fontname='helv',fontsize=size)>=0

def _clear(page,rectangles):
    for rect in rectangles:page.add_redact_annot(fitz.Rect(rect),fill=(1,1,1))
    if rectangles:page.apply_redactions(graphics=0)

def _identity_fields(doc,fields):
    aliases={'studentname':'student_name','nameofstudent':'student_name','studentfirstname':'student_name',
        'stfirstname':'student_name','studentlastname':'student_name','stlastname':'student_name',
        'dob':'dob','dateofbirth':'dob','birthdate':'dob','grade':'grade','studentgrade':'grade',
        'schoolyear':'school_year','iepstart':'iep_from','iepend':'iep_to'}
    for pi,page in enumerate(doc):
        for w in list(page.widgets() or []):
            if w.field_type!=fitz.PDF_WIDGET_TYPE_TEXT:continue
            name=re.sub('[^a-z]','',w.field_name.rsplit('.',1)[-1].lower())
            path=aliases.get(name)
            if not path:continue
            b={'page':pi,'rect':list(w.rect),'widget':w.field_name,'confirmed':True,'native':True}
            if 'firstname' in name:b['name_part']='first'
            elif 'lastname' in name:b['name_part']='last'
            fields.setdefault(path,[]).append(b)
        if not any(b['page']==pi for b in fields.get('student_name',[])):
            for label in ['STUDENT’S NAME','Student Name:','Student’s Name:','Student Name','Name of Student','Student:','Child’s Name:']:
                hits=[r for r in page.search_for(label) if r.y0<150 and r.x1<page.rect.width*.7]
                if not hits:continue
                r=hits[0];right=min(page.rect.width-35,r.x1+185)
                for w in page.get_text('words'):
                    if w[0]>r.x1+5 and abs(w[1]-r.y0)<5 and any(c.isalpha() for c in w[4]):right=min(right,w[0]-3)
                if right-r.x1>70:
                    fields.setdefault('student_name',[]).append({'page':pi,'rect':[r.x1+3,r.y0-1,right,r.y1+.5],'confirmed':True,'native':True})
                    break

@lru_cache(maxsize=32)
def _blank_original(source,layout_json):
    layout=json.loads(layout_json);chosen=layout['source_pages']
    with fitz.open(stream=source,filetype='pdf') as original:
        original.select([p-1 for p in chosen])
        for index,page in enumerate(original):
            page.remove_rotation();_clear(page,layout.get('clear',{}).get(str(chosen[index]-1),[]))
            for widget in page.widgets() or []:
                original.xref_set_key(widget.xref,'MK/R','0')
                if widget.field_type in (fitz.PDF_WIDGET_TYPE_CHECKBOX,fitz.PDF_WIDGET_TYPE_RADIOBUTTON):
                    widget.field_value='Off';widget.update()
                    original.xref_set_key(widget.xref,'V','/Off')
                    original.xref_set_key(widget.xref,'AS','/Off')
            rules=layout.get('restore_rules',{}).get(str(chosen[index]-1))
            if rules:
                x0,y0,x1,y1=rules['bounds']
                for y in rules.get('horizontal',[]):page.draw_line((x0,y),(x1,y),color=(.5,.5,.5),width=.4)
                for x in rules.get('vertical',[]):page.draw_line((x,y0),(x,y1),color=(.5,.5,.5),width=.4)
            for rect in layout.get('empty_boxes',{}).get(str(chosen[index]-1),[]):
                page.draw_rect(fitz.Rect(rect),color=(.3,.3,.3),fill=(1,1,1),width=.5)
        return original.tobytes(garbage=3,deflate=True)


def build_packet(record,candidate,template,source):
    layout=copy.deepcopy(template.get('mock_layout') or layouts()[template['id']])
    if layout['source_sha256']!=P.digest(source):raise ValueError('Native map does not match source PDF')
    chosen=layout['source_pages'];lookup={p-1:i for i,p in enumerate(chosen)}
    with fitz.open(stream=_blank_original(source,json.dumps(layout,sort_keys=True)),filetype='pdf') as original:
        fields={}
        for path,raw in layout['fields'].items():
            fields[path]=[]
            for value in raw if isinstance(raw,list) else [raw]:
                b={**value,'page':lookup[value['page']],'native':True,'confirmed':True,'format':'labelled'}
                page=original[b['page']];area=fitz.Rect(b['rect'])
                widgets=[w for w in page.widgets() or [] if w.field_type==fitz.PDF_WIDGET_TYPE_TEXT and all(abs(a-z)<3 for a,z in zip(w.rect,area))]
                if len(widgets)==1:b.update(widget=widgets[0].field_name,rect=list(widgets[0].rect))
                fields[path].append(b)
        _identity_fields(original,fields)
        covered=lambda path:any(path==key or path.startswith(key+'.') for key in fields)
        paths=[p for p,v in O.leaf_fields(record).items() if v not in ('',[],None,False) and not p.startswith('extensions.')]
        overflow=[]
        for key,values in fields.items():
            for b in values:
                if b.get('name_part'):continue
                if not all(fits(fitz.Rect(b['rect']),display_value(S.get_path(r,key))) for r in [record,candidate]):
                    if key not in overflow:overflow.append(key)
        continuation=overflow+[p for p in paths if not covered(p)]
        append=io.BytesIO();c=canvas.Canvas(append,pagesize=(612,792),invariant=1)
        style=ParagraphStyle('value',fontName='Helvetica',fontSize=10,leading=13)
        page_no=len(original)-1;y=0;labels=[template['state']+' IEP / source page '+str(p) for p in chosen]
        def new_page():
            nonlocal page_no,y
            if page_no>=len(original):c.showPage()
            page_no+=1;y=690
            c.setFont('Helvetica-Bold',13);c.drawString(40,753,template['state']+' IEP - continuation')
            c.setFont('Helvetica',10);c.drawString(40,732,record['student_name'])
            c.setFont('Helvetica',8);c.drawString(40,25,f'Page {page_no+1} | Additional plan details')
            labels.append('Continuation / additional plan details')
        if continuation:new_page()
        for path in continuation:
            value=display_value(S.get_path(record,path));future=display_value(S.get_path(candidate,path))
            p=Paragraph(escape(value).replace('\n','<br/>'),style)
            h=max(p.wrap(520,700)[1],Paragraph(escape(future).replace('\n','<br/>'),style).wrap(520,700)[1])+16
            label=Paragraph(escape(S.label_for(path).replace(' – ',' / ')),ParagraphStyle('label',fontName='Helvetica-Bold',fontSize=9,leading=11))
            lh=label.wrap(520,100)[1]
            if h+lh>610:raise ValueError('Continuation field exceeds a page: '+path)
            if y-h-lh-28<48:new_page()
            label.drawOn(c,42,y-lh);y-=lh+8
            c.setStrokeColorRGB(.75,.78,.8);c.rect(40,y-h,532,h,stroke=1,fill=0)
            p.drawOn(c,46,y-7-p.wrap(520,700)[1])
            for b in fields.get(path,[]):b['continuation_page']=page_no+1
            fields.setdefault(path,[]).append({'page':page_no,'rect':[45,792-y+4,568,792-y+h-3],'confirmed':True,'format':'labelled'})
            y-=h+22
        c.save()
        for path,values in fields.items():
            for b in values:
                if not b.get('native'):continue
                page=original[b['page']];rect=fitz.Rect(b['rect'])
                value=P.binding_text(page,rect,S.get_path(record,path),b)
                if b.get('widget'):
                    w=next(w for w in page.widgets() if w.field_name==b['widget']);w.field_value=value;w.text_fontsize=8
                    w.field_flags |= fitz.PDF_TX_FIELD_IS_MULTILINE
                    # Some XFA-derived forms retain their old /Ff and /DA in update().
                    original.xref_set_key(w.xref,'Ff',str(w.field_flags))
                    original.xref_set_key(w.xref,'DA','(/Helv 8 Tf 0 g)')
                    w.text_font='Helv';w.update()
                else:_clear(page,[b['rect']]);P._put_text(page,rect,value)
        for index,page in enumerate(original):
            for label in layout.get('restore_labels',{}).get(str(chosen[index]-1),[]):
                page.insert_text(label['at'],label['text'],fontname='hebo',fontsize=label.get('size',9))
        for pi,page in enumerate(original):
            old=page.mediabox;page.set_mediabox(fitz.Rect(0,0,old.width,old.height+20))
            page.insert_text((14,13),record['student_name']+(' | Practice record' if pi==0 else ''),fontsize=7,color=(.35,.4,.44))
        for values in fields.values():
            for b in values:
                if b.get('native'):b['rect'][1]+=20;b['rect'][3]+=20
        native=original.tobytes(garbage=3,deflate=True)
    writer=PdfWriter();writer.append(PdfReader(io.BytesIO(native)),import_outline=False)
    if continuation:writer.append(PdfReader(io.BytesIO(append.getvalue())),import_outline=False)
    P.ensure_form_tree(writer)
    target=io.BytesIO();writer.write(target)
    return target.getvalue(),fields,labels,len(chosen)
