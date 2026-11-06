"""Course-scoped gradebook fixtures served by the local LTI platform."""
import local_store as store
import integrations as I
from mock_platform import ROLE

COURSES=[('applied','Mathematics','Emily Harper'),('communication','English language arts','Daniel Reed')]

def roster(pairs,version,provider):
    old=store.get('sis',provider)
    if old and old.get('generator')!=version:raise ValueError('Roster namespace belongs to another generator')
    data={'provider':provider,'generator':version,'synthetic':True,'standard':'OneRoster 1.2 mock roster',
          'synced_at':store.now(),'orgs':[],'academicSessions':[],'users':[],'courses':[],'classes':[],'enrollments':[]}
    for sid,record in pairs:
        uid=version+':'+sid
        school=version+':'+record['extensions']['mock_template_id']+':school'
        data['orgs'].append({'sourcedId':school,'name':record['meta']['school'],'type':'school','status':'active'})
        first,last=record['student_name'].split(' ',1)
        data['users'].append({'sourcedId':uid,'status':'active','role':'student','givenName':first,'familyName':last,'grades':[record['grade']]})
        for slug,title,teacher in COURSES:
            cid=uid+':'+slug;tid=school+':'+slug+':teacher'
            data['users'].append({'sourcedId':tid,'status':'active','role':'teacher','givenName':teacher.split()[0],'familyName':teacher.split()[1],'grades':[]})
            data['courses'].append({'sourcedId':cid+':course','status':'active','title':title,'org':{'sourcedId':school}})
            data['classes'].append({'sourcedId':cid,'status':'active','title':title,'classCode':slug,'classType':'scheduled','school':{'sourcedId':school},'course':{'sourcedId':cid+':course'},'grades':[record['grade']]})
            for person,role in [(uid,'student'),(tid,'teacher')]:
                data['enrollments'].append({'sourcedId':cid+':'+role,'status':'active','user':{'sourcedId':person},'class':{'sourcedId':cid},'school':{'sourcedId':school},'role':role,'primary':role=='teacher'})
    for key in ['orgs','users','courses','classes','enrollments']:
        # Replace this generator's old student-only enrollment scheme.
        previous=[r for r in (old or {}).get(key,[]) if key!='enrollments' or r.get('role')]
        merged={r['sourcedId']:r for r in previous};merged.update({r['sourcedId']:r for r in data[key]});data[key]=list(merged.values())
    store.put('sis',provider,data)
    return data

def seed_evidence(sid,record,case,version,provider):
    context=I.student_context(sid);uid=context['link']['sourced_id']
    for n,(slug,title,teacher) in enumerate(COURSES):
        course=next(c for c in context['classes'] if c['sourcedId']==uid+':'+slug);cid=course['sourcedId']
        tid=course['school']['sourcedId']+':'+slug+':teacher'
        members=[{'user_id':uid+':lti','lis_person_sourcedid':uid,'name':record['student_name'],'roles':[ROLE+'Learner'],'status':'Active'},
                 {'user_id':tid+':lti','lis_person_sourcedid':tid,'name':teacher,'roles':[ROLE+'Instructor'],'status':'Active'}]
        labels=['Multi-step problem solving','Independent practice review'] if n==0 else ['Reading response','Written explanation']
        comments=[case['observation_a' if n==0 else 'observation_b'],
                  'Follow-up task: '+('The agreed support was available. '+case['observation_a'] if n==0 else 'Support availability still varied by activity. '+case['observation_b'])]
        items=[];records=[]
        for j,label in enumerate(labels):
            key='assignment-'+str(j+1);url=I.BASE+'/lti/contexts/'+cid+'/lineitems/'+key
            result={'userId':uid+':lti','resultScore':([72,80] if n==0 else [70,74])[j], 'resultMaximum':100,
                    'scoringUserId':tid+':lti','comment':comments[j],
                    'https://example.org/iep/graded_at':('2026-10-16' if j==0 else '2026-10-30')+'T16:00:00Z'}
            items.append({'key':key,'label':label,'scoreMaximum':100,'results':[result]})
            records.append(I.lms_result_record(sid,uid,cid,title,{'id':url,'label':label},result,members))
        store.put('mock_gradebook',cid,{'course_id':cid,'generator':version,'synthetic':True,'items':items})
        store.put('lms',sid+'|'+cid,{'id':sid+'|'+cid,'student_id':sid,'course_id':cid,'sis_id':uid,
                  'records':records,'members':members,'synced_at':store.now(),'source':'Local platform gradebook fixture','generator':version})
        old=store.get('report',f'{version}:{sid}:observation:{n}')
        if old and old.get('generator')==version:
            old['superseded_by_lms']=True;store.put('report',old['id'],old)
    for n,role,author,text in [(2,'Student',record['student_name'],case['voice']),
                              (3,'Parent / caregiver','Alex '+record['student_name'].split(' ',1)[1],case['family'])]:
        key=f'{version}:{sid}:observation:{n}';cid=uid+':communication'
        store.put('report',key,{'id':key,'student_id':sid,'sis_id':uid,'kind':'report','course_id':cid,
            'course':'English language arts','reporter':author,'reporter_role':role,'accommodation':case['support'],
            'accommodation_instance_id':sid+':support-1','catalog_id':case['catalog_ids'][0],
            'usage':'Sometimes','delivery_status':'Preference reported' if n==2 else 'Home context',
            'effectiveness':'Insufficient evidence','observation':text,'period_start':'2026-10-05','period_end':'2026-10-30',
            'fetched_at':store.now(),'source':'Direct stakeholder report','synthetic':True,'generator':version})
    return I.evidence(sid)
