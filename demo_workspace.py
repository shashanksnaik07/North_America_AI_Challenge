"""Recording presets and reversible workspace snapshots."""
import streamlit as st
import demo_snapshots as snapshots
import local_store as store
import workspace_state as W


def sync_session():
    generation=W.generation()
    if st.session_state.get('workspace_generation',generation)!=generation:
        st.session_state.clear()
        st.session_state['flash']='Workspace reset. Temporary drafts and review confirmations were cleared.'
    st.session_state['workspace_generation']=generation


def panel():
    import workspace_design as D
    import workspace_ui as U
    st.subheader('Demo & reset')
    setup=store.get('demo_setup','video',{})
    if setup:
        st.write('Recording students')
        for student in setup['students']:
            with st.container(horizontal=True,vertical_alignment='center'):
                st.write('**'+student['name']+'** — '+student['purpose'])
                if st.button('Open student',icon=':material/person:',key='demo_open_'+student['id']):
                    D.open_student(student['id'],'Overview')
    saved=snapshots.list_snapshots()
    if saved:
        default=next((i for i,item in enumerate(saved) if item['label']==setup.get('snapshot_label','Demo start')),0)
        chosen=st.selectbox('Starting snapshot',saved,index=default,format_func=lambda item:f"{item['label']} · {item['created'][:19]}")
        st.caption(f"{chosen['students']} students · {chosen['reviews']} review records · {chosen['supporting_chunks']} supporting-document chunks")
        st.write('Reset restores the entire local workspace: IEPs, PDFs, history, drafts, reports, grades, rosters and supporting documents. A backup of the current take is saved automatically.')
        confirmed=st.checkbox('Reset all application data to this snapshot',key='confirm_reset_'+chosen['id'])
        if st.button('Reset for next take',icon=':material/restart_alt:',type='primary',disabled=not confirmed):
            with st.spinner('Backing up this take and restoring the starting snapshot…'):
                result=U.attempt(snapshots.restore,chosen['id'])
            if result:
                st.session_state.clear()
                st.session_state['workspace_generation']=W.generation()
                st.session_state['flash']='Restored '+chosen['label']+'. Your previous take was backed up.'
                st.rerun()
    else: st.info('Save a snapshot before beginning a recording.')
    with st.expander('Save another starting point',icon=':material/save:'):
        with st.form('save_snapshot'):
            label=st.text_input('Snapshot name',placeholder='Demo start')
            if st.form_submit_button('Save snapshot',icon=':material/save:'):
                with st.spinner('Saving the workspace…'): result=U.attempt(snapshots.capture,label)
                if result: U.notice('Snapshot saved: '+result['label'])
