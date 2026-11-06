"""Task-oriented presentation; all persistence and approval rules stay in services."""
import copy
import datetime as dt
from html import escape
import json
import uuid
import streamlit as st
import core
import document_tools as tools
import iep_schema as S
import integrations as I
import local_store as store
import ontology as O
import pdf_workspace as P
import pdf_viewer as V
import reviews as R
import workspace_ui as U

PRIMARY_TASKS = ['Read', 'Edit', 'Modifications', 'Review']
SECTION_PREFIXES = {
    'Student details': ('student_name','dob','grade','school_year','iep_from','iep_to','meta'),
    'Present levels (PLAAFP)': ('profile',), 'Annual goals': ('goals',),
    'Services & accommodations': ('services',), 'Transition': ('transition','transition_goals'),
    'Additional information': (),
}

def label(path):
    common={'student_name':'Student name','dob':'Date of birth','grade':'Grade','school_year':'School year','iep_from':'Plan start date','iep_to':'Plan end date','meta.eligibility':'Eligibility','meta.school':'School','meta.case_manager':'Case manager'}
    if path in common: return common[path]
    if path.startswith('extensions.'): return path.split('.',1)[1].replace('_',' ').capitalize()
    return S.label_for(path).replace('Student Profile – ', '').replace('The academic, developmental, and functional needs of the student','Learning and support needs')

def section_for(path):
    return next((name for name,prefixes in SECTION_PREFIXES.items() if any(path==p or path.startswith(p+'.') for p in prefixes)), 'Additional information')

def navigate(sid, task, review=None):
    st.session_state['pending_tool_'+sid]=task
    st.session_state['pending_main']='Student workspace'
    st.session_state['pending_student_section']='IEP'
    st.session_state.pop('active_import',None)
    st.session_state.pop('setup_section',None)
    if review: st.session_state['selected_review']=review
    st.rerun()

def open_student(sid,section='IEP',tool='Read'):
    st.session_state['pending_student']=sid
    st.session_state['pending_main']='Student workspace'
    st.session_state['pending_student_section']=section
    st.session_state['pending_tool_'+sid]=tool
    st.session_state.pop('active_import',None)
    st.session_state.pop('setup_section',None)
    st.rerun()

def caseload(students):
    records=[(sid,core.get_iep(sid)) for sid in students]
    pending=R.list_reviews(open_only=True)
    counts={sid:sum(r.get('student_id')==sid for r in pending) for sid in students}
    st.caption('All students in this local workspace. Select a name for their overview or open the IEP directly.')
    with st.container(horizontal=True):
        st.metric('Students',len(students),width=160)
        st.metric('Drafts to review',sum(counts.values()),width=160)
    with st.container(horizontal=True,vertical_alignment='bottom'):
        query=st.text_input('Find a student',placeholder='Name, school or case manager',width=360)
        show=st.selectbox('Show',['All students','Needs review'],width=190)
    case_filter,state_filter,template_filter='All profiles','All states','All templates'
    seeded=[r for _,r in records if r.get('extensions',{}).get('mock_cohort')]
    if seeded:
        with st.container(horizontal=True):
            case_filter=st.selectbox('Mock profile',['All profiles']+sorted({r['extensions']['mock_profile_type'] for r in seeded}),width=350)
            state_filter=st.selectbox('Template state',['All states']+sorted({r['extensions']['mock_template_state'] for r in seeded}),width=200)
            choices=['All templates']+sorted({r['extensions']['mock_template_id'] for r in seeded if state_filter=='All states' or r['extensions']['mock_template_state']==state_filter})
            template_filter=st.selectbox('NASET form',choices,format_func=lambda x:x if x=='All templates' else O.template(x)['title'],width=350)
        st.caption(f'{len(seeded)} practice records · 12 support profiles across NASET state templates.')
    visible=[(sid,r) for sid,r in records if (show!='Needs review' or counts[sid]) and query.casefold() in ' '.join([r['student_name'],r['meta']['school'],r['meta']['case_manager']]).casefold()
             and (case_filter=='All profiles' or r.get('extensions',{}).get('mock_profile_type')==case_filter)
             and (state_filter=='All states' or r.get('extensions',{}).get('mock_template_state')==state_filter)
             and (template_filter=='All templates' or r.get('extensions',{}).get('mock_template_id')==template_filter)]
    st.caption('Plan end dates come from the saved IEP. They are not verified review or compliance deadlines.')
    if not visible: st.info('No students match these filters. Clear the search or choose All students.')
    if len(visible)>20:
        page_count=(len(visible)+19)//20
        page=st.selectbox('Caseload page',range(page_count),format_func=lambda x:f'{x+1} of {page_count}',width=150)
        st.caption(f'Showing {page*20+1}–{min((page+1)*20,len(visible))} of {len(visible)} students')
        visible=visible[page*20:(page+1)*20]
    with st.container(key='caseload-list'):
        for sid,r in visible:
            with st.container(border=True):
                name,school,dates,action=st.columns([2,2,1.2,1.4],vertical_alignment='center')
                with name:
                    if st.button(r['student_name'],type='tertiary',key='profile_'+sid,icon=':material/person:'): open_student(sid,'Overview')
                    st.caption('Case manager: '+(r['meta']['case_manager'] or 'Not recorded'))
                    if r.get('extensions',{}).get('mock_profile_type'): st.caption(r['extensions']['mock_profile_type'])
                with school:
                    st.write(r['meta']['school'] or 'School not recorded')
                    st.caption('Grade '+(r['grade'] or 'not recorded'))
                with dates:
                    st.caption('Plan ends')
                    st.write(r['iep_to'] or 'Not recorded')
                with action:
                    if st.button('Open IEP',key='open_iep_'+sid,width='stretch',icon=':material/arrow_forward:'): open_student(sid)
                    if counts[sid]:
                        if st.button(f'Review {counts[sid]} draft'+('s' if counts[sid]!=1 else ''),key='review_student_'+sid,type='tertiary',icon=':material/edit_note:'): open_student(sid,tool='Review')
                    else: st.caption('No pending drafts')

def import_queue():
    items=[r for r in R.list_reviews(open_only=True) if r['student_id'] is None and r['kind']=='import']
    if not items: return
    st.subheader('Imports awaiting review')
    st.caption('These documents have not yet been added as student records.')
    for r in items:
        with st.container(border=True):
            st.write(r['candidate'].get('student_name') or r['title'])
            st.caption(r['title']+' · '+('Specialist review needed' if r['status']=='escalated' else 'Awaiting review'))
            if st.button('Review import',key='open_import_'+r['id'],icon=':material/rate_review:'):
                st.session_state['active_import']=r['id']
                st.session_state['pending_main']='Student workspace'
                st.session_state.pop('setup_section',None)
                st.rerun()

def student_overview(sid,record):
    st.subheader('Student overview')
    left,right=st.columns([1.5,1])
    with left:
        with st.container(border=True):
            st.markdown('**Student information**')
            fact('Date of birth',record['dob'])
            fact('Eligibility recorded in IEP',record['meta']['eligibility'])
            fact('School',record['meta']['school'])
            fact('Case manager',record['meta']['case_manager'])
        with st.expander('Present levels & student strengths'):
            st.markdown('**Strengths**');st.write(record['profile']['strengths'] or 'Not recorded')
            st.markdown('**Learning and support needs**');st.write(record['profile']['needs'] or 'Not recorded')
        with st.expander(f"Annual goals ({len(record['goals'])})"):
            for goal in record['goals']: st.markdown('**'+goal['area']+'**');st.write(goal['goal'])
    with right:
        with st.container(border=True):
            st.markdown('**Current IEP**')
            fact('Plan dates',' – '.join(x for x in [record['iep_from'],record['iep_to']] if x))
            st.caption('Recorded dates · no compliance determination')
            if st.button('Open current IEP',type='primary',width='stretch',icon=':material/arrow_forward:'): navigate(sid,'Read')
            pending=R.list_reviews(sid,open_only=True)
            st.caption(f"{len(pending)} {'draft' if len(pending)==1 else 'drafts'} awaiting review")
            if pending and st.button('Review drafts',width='stretch',icon=':material/edit_note:'): navigate(sid,'Review')

def student_documents(sid,actor):
    st.subheader('Student documents')
    with st.container(border=True):
        st.markdown('**Current IEP**')
        record=core.get_iep(sid)
        st.caption('School year '+(record['school_year'] or 'not recorded'))
        st.download_button('Download current IEP',U.export_current(sid,record),'iep-current.pdf','application/pdf',icon=':material/download:')
    section=st.segmented_control('Document library',['Supporting documents','IEP history'],default='Supporting documents',required=True,key='document_library_'+sid,persist_state='session')
    if section=='IEP history': tools.history(sid,actor)
    else: resources_workspace(sid,actor,'Supporting files')

def submit(sid,candidate,title,actor,document=None):
    rid=U.attempt(R.stage_change,sid,candidate,title,actor,document=document)
    if rid:
        st.session_state['flash']='Change saved as a draft. Review it before updating the IEP.'
        navigate(sid,'Review',rid)

def fact(title,value):
    st.markdown('<div class="plan-fact"><small>'+escape(title)+'</small><strong>'+escape(str(value or 'Not recorded'))+'</strong></div>',unsafe_allow_html=True)

def overview(sid, record):
    st.subheader('Plan at a glance')
    pending=R.list_reviews(sid,open_only=True)
    if pending:
        st.info(f"{len(pending)} {'change needs' if len(pending)==1 else 'changes need'} review.")
        if st.button('Review pending changes',type='primary',width='stretch',icon=':material/rate_review:'): navigate(sid,'Review')
    else: st.caption('No changes waiting for review.')
    fact('Plan dates', ' – '.join(x for x in [record['iep_from'],record['iep_to']] if x))
    fact('Case manager',record['meta']['case_manager'])
    fact('Annual goals',str(len(record['goals'])))
    with st.expander('Student strengths'):
        st.write(record['profile'].get('strengths') or 'No strengths recorded yet.')
    st.caption('Choose Edit draft for a direct edit, or Suggested modifications to discuss evidence and draft a change.')
    metadata=store.get('mock_student',sid)
    if metadata:
        with st.expander('Case and template provenance'):
            st.write(metadata['case_label']+' · '+metadata['state'])
            st.caption('Practice record built from the listed sources. The original NASET layout contains the plan; linked continuation pages hold overflow and additional details.')
            st.link_button('NASET reference form',metadata['naset']['url'],icon=':material/open_in_new:')
            st.link_button('Hong Kong example',metadata['edb']['url'],icon=':material/open_in_new:')
            st.download_button('Download provenance',json.dumps(metadata,indent=2),sid+'-provenance.json','application/json',icon=':material/download:')

def edit_panel(sid,record,actor):
    st.subheader('Propose an edit')
    st.caption('Select a section below or click a field on the PDF. Changes need review before they update the plan.')
    fields={p:v for p,v in O.leaf_fields(record).items() if not isinstance(v,(dict,list))}
    sections=[s for s in SECTION_PREFIXES if any(section_for(p)==s for p in fields)]
    selected_section=st.selectbox('Section',sections,key='edit_section_'+sid,persist_state='session')
    available=[p for p in fields if section_for(p)==selected_section]
    key='editor_field_'+sid
    if st.session_state.get(key) not in available: st.session_state[key]='student_name' if 'student_name' in available else available[0]
    field=st.selectbox('Field',available,format_func=label,key=key,persist_state='session')
    draft_key=f'edit_{sid}_{field}_{R.fingerprint(record)[:8]}'
    value=U.typed_value('Proposed wording',fields[field],draft_key)
    changed=value!=fields[field]
    if changed: st.caption('Unsaved draft · stays here while you switch tools.')
    if st.button('Save for review',type='primary',disabled=not changed,width='stretch',icon=':material/save:'):
        candidate=copy.deepcopy(record);S.set_path(candidate,field,value)
        submit(sid,candidate,'Edit: '+label(field),actor)
    with st.expander('Add a goal, service or team member'):
        st.caption('Use the form editor to add or remove rows.')
        if st.button('Open form editor',width='stretch',icon=':material/edit_note:'):
            st.session_state['pending_view_'+sid]='Form';st.rerun()
    with st.expander('PDF layout & advanced options'):
        st.caption('Only needed when a field is missing or appears in the wrong place.')
        mapping=st.checkbox('Select an area on the PDF',key='mapping_'+sid)
        selected=st.session_state.get('selected_region_'+sid)
        document=P.ensure_document(sid,record)
        if selected:
            st.caption(f"Selected area on page {selected['page']+1}.")
            if st.button('Use this area for the field',icon=':material/crop_free:'):
                mapped=U.attempt(P.set_binding,document,field,{'page':selected['page'],'rect':P.view_rectangle(document,selected['page'],selected['rect'],inverse=True)})
                if mapped: submit(sid,record,'Position field: '+label(field),actor,mapped)
        with st.expander('Enter exact coordinates'):
            pages=P.inspect_pdf(P.source_bytes(document))
            page=st.number_input('Page for field',1,len(pages),1,key='bind_page_'+sid)-1
            old=next((b['rect'] for b in document['bindings'].get(field,[]) if b['page']==page),[30.,60.,300.,120.])
            coords=[st.number_input(n,value=float(old[i]),key=f'coord_{sid}_{field}_{page}_{i}') for i,n in enumerate(['Left','Top','Right','Bottom'])]
            if st.button('Save field location for review',icon=':material/crop_free:'):
                mapped=U.attempt(P.set_binding,document,field,{'page':page,'rect':coords})
                if mapped: submit(sid,record,'Position field: '+label(field),actor,mapped)
        with st.expander('Replace the source PDF'):
            upload=st.file_uploader('Source PDF',type=['pdf'],key='attach_'+sid)
            if st.button('Review replacement PDF',disabled=upload is None,icon=':material/description:'):
                mapped=U.attempt(P.archive_source,upload.getvalue(),record,upload.name)
                if mapped: submit(sid,record,'Replace source PDF',actor,mapped)
        with st.expander('Edit structured data'):
            st.caption('For template administrators. Ordinary edits belong in the fields above.')
            raw=st.text_area('IEP JSON',json.dumps(record,indent=2),height=200,key='advanced_'+sid)
            if st.button('Validate and review data',icon=':material/rate_review:'):
                try:
                    import jsonschema
                    candidate=json.loads(raw)
                    jsonschema.validate(candidate,O.template_schema(document.get('template_id','custom')))
                    submit(sid,candidate,'Structured data edit',actor)
                except (ValueError,jsonschema.ValidationError) as exc: st.error(str(exc))
    return field

def evidence_cards(items):
    for item in items:
        course=item.get('course')
        author=item.get('reporter')
        role=item.get('reporter_role')
        title=' · '.join(str(v) for v in [author,role,course] if v) or item.get('source') or item.get('citation') or 'Supporting information'
        st.markdown('**'+title+'**')
        if item.get('kind')=='lti_result':
            grade=f"{item['score']:g} / {item.get('maximum',1):g}" if isinstance(item.get('score'),(int,float)) else 'Not graded'
            st.write(item.get('label','Assignment')+' — '+grade)
        text=item.get('observation') or item.get('text') or item.get('label') or item.get('description')
        if text: st.write(text)
        stamp=('Graded '+item['graded_at'][:10]) if item.get('graded_at') else ('Synced '+item['fetched_at'][:10]) if item.get('kind')=='lti_result' and item.get('fetched_at') else item.get('period_end')
        details=[item.get('source'),stamp,item.get('citation')]
        st.caption(' · '.join(str(v) for v in details if v))

def review_inbox(actor='',role='Case manager',sid=None,compact=False,include_imports=False,imports_only=False,review_id=None):
    generation=st.session_state.get('workspace_generation')
    st.subheader('Review changes')
    include_closed=st.checkbox('Show completed reviews',key=f'closed_{sid}')
    items=R.list_reviews(None if include_imports else sid,open_only=not include_closed)
    if include_imports: items=[r for r in items if r.get('student_id') in (None,sid)]
    if imports_only: items=[r for r in items if r.get('student_id') is None and r['kind']=='import']
    if review_id: items=[r for r in items if r['id']==review_id]
    if not items:
        st.success('You’re up to date. No changes waiting for review.')
        st.caption('Edits, imports and AI suggestions will appear here before the plan changes.')
        return
    ids=[r['id'] for r in items]; key=f'review_{sid}'
    preferred=st.session_state.pop('selected_review',None)
    if preferred in ids: st.session_state[key]=preferred
    if st.session_state.get(key) not in ids: st.session_state[key]=ids[0]
    rid=st.selectbox('Change to review',ids,key=key,format_func=lambda x:next(r['title'] for r in items if r['id']==x))
    item=R.get(rid); scope=rid+str(item['revision'])
    status={'pending':'Awaiting review','escalated':'Specialist review needed','approved':'Approved','rejected':'Rejected'}[item['status']]
    st.markdown('<span class="status-pill">'+status+'</span>',unsafe_allow_html=True)
    delta=P.changes(item['base'],item['candidate'])
    if item['assignee']: st.caption('Assigned to '+item['assignee']+' · '+item['required_role'])
    step=st.segmented_control('Review step',['Compare','Decide'],default='Compare',required=True,key='review_step_'+scope)
    if step=='Compare':
        st.caption(f"{len(delta)} {'field changed' if len(delta)==1 else 'fields changed'}. Removed text is struck through in red; added text is green.")
        if item['findings']:
            with st.expander(f"Check {len(item['findings'])} import findings",expanded=True):
                for finding in item['findings']: st.write('• '+finding)
        if delta:
            selected=st.selectbox('Changed field',delta,format_func=lambda d:label(d['path']),key=scope+'_diff')
            st.session_state['review_active_field']=selected['path']
            st.markdown(R.diff_html(selected['before'],selected['after']),unsafe_allow_html=True)
            document=item.get('document') or {}
            bindings=document.get('bindings',{}).get(P.binding_key(document,selected['path']),[]) if document else []
            if sid and bindings and st.button('Show this field on PDF',key=scope+'_locate',icon=':material/description:'):
                st.session_state['pending_page_'+sid]=bindings[0]['page']
                st.session_state['pending_view_'+sid]='PDF'
                st.rerun()
        if item.get('evidence'):
            with st.expander('Information behind this change'): evidence_cards(item['evidence'])
        if item.get('source_text'):
            with st.expander('Read extracted source text'): st.text(item['source_text'])
        if item['status'] in R.OPEN:
            with st.expander('Correct this draft'):
                fields=U.field_choices(item['candidate'])
                field=st.selectbox('Field to correct',list(fields),format_func=label,key=scope+'_field')
                value=U.typed_value('Revised wording',fields[field],scope+'_value_'+field)
                if st.button('Save correction',key=scope+'_correct',icon=':material/save:'):
                    candidate=copy.deepcopy(item['candidate']);S.set_path(candidate,field,value)
                    try: R.update_candidate(rid,candidate,actor,item['revision']);U.notice('Correction saved. Review the updated draft.')
                    except Exception as exc: st.error(str(exc))
            if item.get('document'):
                with st.expander('Adjust a PDF field location'):
                    field=st.selectbox('Field to place',list(U.field_choices(item['candidate'])),format_func=label,key=scope+'_mapping_field')
                    page=st.number_input('PDF page to place field',1,len(P.inspect_pdf(P.source_bytes(item['document']))),1,key=scope+'_map_page')-1
                    mapped=U.binding_controls(item['document'],field,page,scope+'_map_'+field+str(page))
                    if mapped:
                        R.update_candidate(rid,item['candidate'],actor,item['revision'],mapped);U.notice('PDF location saved.')
        st.button('Continue to decision',type='primary',width='stretch',key=scope+'_next',
                  on_click=lambda: st.session_state.update({'review_step_'+scope:'Decide'}),icon=':material/arrow_forward:')
    else:
        if item['status'] not in R.OPEN:
            st.success('This review is complete. The activity log records the decision.')
        else:
            st.caption('Approval updates the student’s plan and keeps its previous version.')
            reviewer=st.text_input('Reviewer name',key='reviewer_name',persist_state='session')
            reviewer_role=st.selectbox('Reviewer role',R.ROLES,key='reviewer_role',persist_state='session')
            if item['status']=='escalated': st.info('Required role: '+item['required_role']+(('. Assigned to '+item['assignee']+'.') if item['assignee'] else '.'))
            st.caption('Names and roles are self-selected in this local demo.')
            confirmed=st.checkbox('I checked the source, changes, findings and any added pages.',key=scope+'_confirm')
            note=st.text_area('Decision note (optional)',key=scope+'_note',height=85)
            can_decide=(item['status']!='escalated' or reviewer_role in (item['required_role'],'Administrator')) and (not item['assignee'] or reviewer.strip().casefold()==item['assignee'].casefold() or reviewer_role=='Administrator')
            if not reviewer.strip(): st.caption('Enter your name to record a decision.')
            elif not can_decide: st.caption('This decision needs the assigned reviewer and required role, or an Administrator.')
            elif not confirmed: st.caption('Confirm your review to enable approval.')
            if st.button('Approve import' if item['kind']=='import' else 'Approve changes',type='primary',disabled=not confirmed or not reviewer.strip() or not can_decide,width='stretch',key=scope+'_approve',icon=':material/check_circle:'):
                try:
                    student=R.decide(rid,'approved',reviewer,reviewer_role,confirmed,note,item['revision'],expected_generation=generation)
                    if student:
                        st.session_state['pending_student']=student
                        st.session_state['pending_student_section']='IEP'
                    st.session_state.pop('active_import',None)
                    U.notice('Approved. The updated IEP and previous version have been saved.')
                except Exception as exc: st.error(str(exc))
            if st.button('Reject this draft',disabled=not reviewer.strip() or not can_decide,width='stretch',key=scope+'_reject',icon=':material/cancel:'):
                try: R.decide(rid,'rejected',reviewer,reviewer_role,note=note,revision=item['revision'],expected_generation=generation);U.notice('Draft rejected. The student’s plan is unchanged.')
                except Exception as exc: st.error(str(exc))
            with st.expander('Request another reviewer'):
                assignee=st.text_input('Reviewer to assign',key=scope+'_assignee')
                required=st.selectbox('Role needed',R.ROLES,index=1,key=scope+'_role')
                reason=st.text_area('What needs their attention?',key=scope+'_reason')
                if st.button('Assign review',key=scope+'_escalate',icon=':material/person_add:'):
                    try: R.escalate(rid,reviewer,reason,assignee,required);U.notice('Review assigned in the local inbox.')
                    except Exception as exc: st.error(str(exc))
    if not compact and item.get('document'):
        with st.expander('Compare the original PDF',expanded=True): U.show_pdf_diff(item,scope)
    with st.expander('Review activity'): st.dataframe(item['events'],hide_index=True,width='stretch')
    return item

def acrobat_workspace(sid,record,actor,role):
    if 'pending_tool_'+sid in st.session_state: st.session_state['active_tool_'+sid]=st.session_state.pop('pending_tool_'+sid)
    tool=st.session_state.setdefault('active_tool_'+sid,'Read')
    if tool in ('Ask','Suggest updates','Accommodations','Summary'):
        tool='Read' if tool=='Summary' else 'Modifications'
        st.session_state['active_tool_'+sid]=tool
    if 'pending_field_'+sid in st.session_state:
        field=st.session_state.pop('pending_field_'+sid)
        st.session_state['editor_field_'+sid]=field
        st.session_state['edit_section_'+sid]=section_for(field)
    if 'pending_view_'+sid in st.session_state: st.session_state['document_view_'+sid]=st.session_state.pop('pending_view_'+sid)
    count=len(R.list_reviews(sid,open_only=True))
    with st.container(horizontal=True,vertical_alignment='center',key='workspace-tasks'):
        for task,icon in [('Read','description'),('Edit','edit'),('Modifications','auto_fix_high'),('Review','fact_check')]:
            title={'Read':'View IEP','Edit':'Edit draft','Modifications':'Suggested modifications','Review':'Review drafts'}[task]
            if task=='Review' and count: title+=f' ({count})'
            if st.button(title,icon=f':material/{icon}:',type='primary' if tool==task else 'secondary',key='task_'+sid+task): navigate(sid,task)
    with st.container(key='document-layout-read' if tool=='Read' else 'document-layout'):
        canvas,pane=st.columns([2.1,1],gap='medium')
        item=None;field=None
        with pane:
            with st.container(key='inspector'):
                if tool=='Read': overview(sid,record)
                elif tool=='Edit': field=edit_panel(sid,record,actor)
                elif tool=='Review': item=review_inbox(actor,role,sid,compact=True)
                else:
                    st.subheader('Suggested modifications' if tool=='Modifications' else 'Plan history')
                    if tool=='Modifications': tools.modifications(sid,actor)
                    else: tools.history(sid,actor)
        with canvas:
            document=(item or {}).get('document') or P.ensure_document(sid,record)
            if tool=='Review' and item and not item.get('document'):
                st.info('This source has no readable PDF. Compare the extracted information in Review.')
                st.text(item.get('source_text') or 'No text could be extracted. Review the source file before approving.')
                return
            source=P.source_bytes(document);scope=sid+document['sha256'][:8]+st.session_state.get('workspace_generation','initial')
            navigation_key='pdf_navigation_'+scope
            if 'pending_page_'+sid in st.session_state:
                st.session_state[navigation_key]={'page':st.session_state.pop('pending_page_'+sid),'token':uuid.uuid4().hex}
            with st.container(horizontal=True,vertical_alignment='bottom'):
                view=st.segmented_control('View',['PDF','Form'],default='PDF',required=True,key='document_view_'+sid,persist_state='session')
                if view=='PDF':
                    zoom=st.selectbox('Zoom',[100,125,150,200],format_func=lambda x:'Fit width' if x==100 else f'{x}%',key='zoom_'+sid,width=125,persist_state='session')
                with st.popover('Download',icon=':material/download:'):
                    try: st.download_button('Proposed IEP' if item else 'Current IEP',P.render_document(document,item['candidate'] if item else record)[0],'iep-proposed.pdf' if item else 'iep.pdf','application/pdf',width='stretch',icon=':material/download:')
                    except ValueError as exc: st.error(str(exc))
                    st.download_button('Unchanged original',P.source_bytes(document.get('original_source',document)),document['filename'],'application/pdf',width='stretch',icon=':material/download:')
            if view=='Form':
                if tool=='Review' and item:
                    st.subheader('Proposed changes')
                    for d in P.changes(item['base'],item['candidate']):
                        st.markdown('**'+label(d['path'])+'**');st.markdown(R.diff_html(d['before'],d['after']),unsafe_allow_html=True)
                else: tools.form(sid,actor)
                return
            highlighted_fields=[];color='green';redlines=[]
            if item:
                version=st.segmented_control('Compare PDF',['Changes','Proposed','Current / source'],default='Changes',required=True,key='compare_redline_'+item['id'])
                delta=P.changes(item['base'],item['candidate'])
                highlighted_fields=list({P.binding_key(document,d['path']) for d in delta}-{None})
                if version=='Changes':
                    preview_record=None if item['kind']=='import' else item['base']
                    redlines=V.review_redlines(document,item['base'],item['candidate'])
                elif version=='Current / source':
                    preview_record=None if item['kind']=='import' else item['base'];color='red'
                else:
                    preview_record=item['candidate']
                st.caption('Red strike-through: removed · Green underline: added · Expand a marked field for the full change.'
                           if version=='Changes' else 'Green: proposed changes' if color=='green' else 'Red: current/source locations')
                missing=sum(not P.binding_key(document,d['path']) for d in delta)
                if missing: st.warning(f'{missing} changed fields need a PDF location. Check them in Form view; downloads include them on added pages.')
            else:
                preview_record=record
            if document['origin']=='generated baseline': st.caption('Preview created from the saved IEP. Imported PDFs keep their original layout.')
            V.continuation_notice(document)
            show_fields=tool=='Edit'
            selected=st.session_state.get('selected_region_'+sid)
            mode='map' if tool=='Edit' and st.session_state.get('mapping_'+sid) else 'select' if tool=='Edit' else 'read'
            with st.spinner('Preparing document pages…'):
                try: content_id,pages=V.document_preview(source,document,preview_record,append_unmapped=not bool(item))
                except ValueError as exc:
                    st.error(str(exc));content_id,pages=V.document_preview(source,document)
            result=V.viewer(pages=pages,content_id=content_id,document_key=scope,
                initial_page=document.get('default_page',0),navigation=st.session_state.get(navigation_key),
                show_fields=show_fields,active_field=field,zoom=zoom,viewport_height=710,
                highlighted_fields=[] if redlines else highlighted_fields,color=color,redlines=redlines,
                selection=selected if tool=='Edit' else None,
                mode=mode,key='document_canvas_'+scope,default=None)
            if result and result['event']!=st.session_state.get('handled_canvas_event_'+sid):
                st.session_state['handled_canvas_event_'+sid]=result['event']
                if result.get('field') and result['field'] in O.leaf_fields(record):
                    st.session_state['pending_field_'+sid]=result['field'];navigate(sid,'Edit')
                elif result.get('rect'): st.session_state['selected_region_'+sid]=result;st.rerun()

def resources_workspace(sid,actor,section=None):
    if section is None:
        section=st.segmented_control('Resources',['Course reports','Supporting files','Templates','Connections'],default='Course reports',required=True,key='resource_section',persist_state='session')
    if section=='Templates':
        U.templates_workspace(actor);return
    if not sid:
        st.info('Select or add a student to view their reports and files. Templates are available without a student.');return
    if section=='Connections':
        connections(sid,actor);return
    if section=='Supporting files':
        st.subheader('Supporting files')
        st.caption('Add evaluations, progress notes or other context for questions and suggested changes.')
        with st.form('supporting_files_'+sid):
            upload=st.file_uploader('Choose a PDF or text file',type=['pdf','txt'])
            if st.form_submit_button('Add supporting file',type='primary',icon=':material/attach_file:'):
                if upload is None: st.error('Choose a file first.')
                else:
                    text=U.attempt(core.extract_text,upload.name,upload.getvalue())
                    if text and U.attempt(core.add_supporting_doc,sid,upload.name,text): U.notice('File added. It is available to Suggested modifications.')
        for name in core.list_supporting_docs(sid): st.write('📄 '+name)
        if not core.list_supporting_docs(sid): st.caption('No supporting files yet.')
        return
    course_reports(sid,actor)

def connections(sid,actor):
    st.subheader('Connect school information')
    st.caption('Demo setup · These connections use synthetic data, not a live school system.')
    context=I.student_context(sid)
    if context: st.success(f"Connected to {context['user']['givenName']} {context['user']['familyName']} · {len(context['classes'])} courses")
    with st.container(border=True):
        st.markdown('**1. Choose a student information system**')
        provider=st.selectbox('School system',list(I.PROVIDERS),format_func=I.PROVIDERS.get,key='provider_'+sid)
        if st.button('Refresh roster',type='primary',icon=':material/sync:'):
            if U.attempt(I.sync_sis,provider): st.success('Roster refreshed. Match the student below.')
        snapshot=store.get('sis',provider)
        if snapshot:
            st.markdown('**2. Match this student**')
            students=[u for u in snapshot['users'] if u['role']=='student' and u['status']=='active']
            chosen=st.selectbox('Roster student',students,format_func=lambda u:f"{u['givenName']} {u['familyName']} · {u['sourcedId']}")
            if st.button('Connect student',icon=':material/link:'):
                try: I.link_student(sid,provider,chosen['sourcedId']);U.notice('Student connected. Open Course reports to view course information.')
                except Exception as exc: st.error(str(exc))
            with st.expander('Technical details'): st.json(snapshot)
    if context and st.button('Review school and grade updates',icon=':material/rate_review:'):
        candidate=core.get_iep(sid);candidate['grade']=next(iter(context['user'].get('grades',[])),candidate['grade'])
        schools={o['sourcedId']:o['name'] for o in context['orgs']}
        if context['classes']: candidate['meta']['school']=schools.get(context['classes'][0]['school']['sourcedId'],'')
        rid=U.attempt(R.stage_change,sid,candidate,'School and grade from roster',actor,evidence=[context])
        if rid: navigate(sid,'Review',rid)
    with st.expander('About these demo connections'):
        st.write('SIS rosters use a OneRoster 1.2 subset. LTI 1.3 launches, NRPS membership and AGS results provide permitted course context. They do not expose all LMS content. Course reports are entered in this app.')
        st.download_button('Export canonical IEP data',json.dumps(O.canonical(core.get_iep(sid),sid,evidence=I.evidence(sid)),indent=2),'iep-canonical.json','application/json',icon=':material/download:')

def course_reports(sid,actor):
    st.subheader('Grades & course feedback')
    st.caption('Review assignment grades and instructor comments alongside student and family reports.')
    context=I.student_context(sid)
    if not context or not context['classes']:
        st.info('Connect a school roster to choose the student’s courses.')
        if st.button('Set up a connection',type='primary',icon=':material/link:'):
            st.session_state['setup_section']='Connections';st.rerun()
        return
    items=I.evidence(sid)
    course_filter=st.selectbox('Filter by course',['All courses']+[c['title'] for c in context['classes']],key='evidence_course_'+sid)
    visible=[r for r in items if course_filter=='All courses' or r.get('course')==course_filter]
    graded=[r for r in visible if r['kind']=='lti_result']
    st.markdown('**LMS assignments**')
    if graded:
        rows=[{'Course':r['course'],'Assignment':r.get('label','Assignment'),
               'Grade':f"{r['score']:g} / {r.get('maximum',1):g}" if isinstance(r.get('score'),(int,float)) else 'Not graded',
               'Instructor':r.get('reporter','Author not provided by LMS'),
               'Date':(r.get('graded_at') or '')[:10] or 'Not supplied','Comment':r.get('observation','')} for r in graded]
        st.dataframe(rows,hide_index=True,width='stretch')
        st.caption('Assignment results are context, not a measure of accommodation effectiveness. Dates are shown only when supplied by the platform.')
        st.markdown('**Instructor feedback by assignment**')
        evidence_cards([r for r in graded if r.get('observation')])
    else:st.info('No LMS grades are available for this course selection. Refresh a course to retrieve shared assignments and comments.')
    direct=[r for r in visible if r['kind']=='report']
    if direct:
        with st.expander('Student, family & other reports',expanded=True):evidence_cards(direct)
    aggregation=I.aggregate_reports(sid)
    if items:
        if st.button('Use these reports to draft an update',type='primary',icon=':material/edit_note:'):navigate(sid,'Modifications')
    if aggregation:
      with st.expander('Accommodation report summary'):
        for group in aggregation:
            with st.container(border=True):
                st.markdown('**'+group['Accommodation']+'**')
                st.caption(f"{group['Reports']} reports · {group['Courses']}")
                st.write('Observed outcomes: '+group['Outcomes'])
                if group['Mixed observations']: st.caption('Observations differ across courses. Review the examples before drawing conclusions.')
    with st.expander('Add a classroom report',expanded=not bool(aggregation)):
        with st.form('course_report_'+sid):
            course=st.selectbox('Course',context['classes'],format_func=lambda c:c['title'])
            reporter=st.text_input('Your name',value=actor)
            reporter_role=st.selectbox('Your role',['Teacher','Parent / caregiver','Student','Related service provider','Case manager'])
            accommodation=st.text_input('Accommodation used',placeholder='For example, extended time')
            usage=st.selectbox('How often was it used?',['Every opportunity','Most opportunities','Sometimes','Not used'])
            effectiveness=st.selectbox('What did you observe?',['Helpful','Mixed','Not helpful','Insufficient evidence'])
            start=st.date_input('Reporting period starts',value=dt.date.today().replace(day=1))
            end=st.date_input('Reporting period ends',value=dt.date.today())
            observation=st.text_area('Examples and observations',placeholder='Describe the task, how the accommodation was used, and what you noticed.')
            if st.form_submit_button('Save report',type='primary',icon=':material/save:'):
                if U.attempt(I.submit_report,sid,course['sourcedId'],reporter,accommodation,usage,effectiveness,observation,start,end,reporter_role): U.notice('Report saved. It is now available to Suggested modifications.')
    with st.expander('Refresh course information'):
        course=st.selectbox('Course to refresh',context['classes'],format_func=lambda c:c['title'])
        st.caption('Retrieves grades, assignment comments and course membership shared by the connected LMS.')
        if st.button('Refresh course',icon=':material/sync:'):
            records=U.attempt(I.sync_lms,sid,course['sourcedId'])
            if records is not None: U.notice(f'Course refreshed. {len(records)} results available.')
    with st.expander(f'All reports & course evidence ({len(items)})'):
        evidence_cards(items)
        st.download_button('Download reports',json.dumps(items,indent=2),'course-evidence.json','application/json',icon=':material/download:')
