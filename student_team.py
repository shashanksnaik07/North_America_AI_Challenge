"""Name choices drawn from the student's plan and course-linked evidence."""
import core
import integrations as I

REPORT_ROLES=['Parent / caregiver','Student','Teacher','Related service provider','Case manager']


def names(sid, role, course_id=None, record=None):
    record=record if record is not None else core.get_iep(sid)
    found=[]
    def add(value):
        value=str(value or '').strip()
        if value and value.casefold() not in {name.casefold() for name in found}: found.append(value)
    if role=='Case manager': add(record['meta'].get('case_manager'))
    if role=='Student': add(record.get('student_name'))
    evidence=I.evidence(sid) if sid else []
    context=I.student_context(sid) if sid and course_id else None
    course=next((c['title'] for c in (context or {}).get('classes',[]) if c['sourcedId']==course_id),'')
    # Prefer instructors actually attributed to this course's graded work.
    for item in evidence:
        if item.get('reporter_role')==role and (role!='Teacher' or not course_id or item.get('course_id')==course_id):
            add(item.get('reporter'))
    tokens={
        'Parent / caregiver':('parent','caregiver','guardian'),
        'Student':('student',), 'Case manager':('case manager',),
        'Teacher':('teacher','instructor'),
        'Related service provider':('therapist','speech','occupational','related service','psycholog'),
        'Specialist':('specialist','psycholog','therapist','speech','evaluation'),
        'Administrator':('administrator','principal','lea representative'),
    }
    for person in record.get('participants',[])+record.get('not_in_attendance',[]):
        position=person.get('position','').casefold()
        if not any(token in position for token in tokens.get(role,())): continue
        if role=='Teacher' and course_id and (not course or course.casefold() not in position): continue
        add(person.get('name'))
    # Shared practice staff are offered only for the generated mock cohort.
    if record.get('extensions',{}).get('mock_cohort'):
        if role=='Specialist': add('Jamie Chen')
        elif role=='Administrator': add('Robin Davis')
    return found
