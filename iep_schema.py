"""
iep_schema.py - the Alabama IEP form (ALSDE, Feb. 2019) as structured data.

Every IEP in the app is stored as a dictionary with exactly this shape, so
each box on the paper form has its own field. That lets the AI change one
field at a time (e.g. "goals.0.goal") instead of guessing where text goes.
"""

import copy
import re

# Option lists copied from the form ---------------------------------------
SPECIAL_FACTORS = [
    ("behavior_impedes", "Does the student have behavior which impedes his/her learning or the learning of others?"),
    ("bip", "Does the student have a Behavioral Intervention Plan?"),
    ("limited_english", "Does the student have limited English proficiency?"),
    ("braille", "Does the student need instruction in Braille and the use of Braille?"),
    ("communication", "Does the student have communication needs?"),
    ("assistive_tech", "Does the student need assistive technology devices and/or services?"),
    ("specially_designed_pe", "Does the student require specially designed P.E.?"),
    ("alternate_assessment", "Has the IEP Team determined the student meets the participation criteria for the "
                             "Alabama Alternate Assessment and will be taught the alternate achievement standards?"),
    ("transition_services", "Are transition services addressed in this IEP?"),
]
TRANSPORT_MODES = ["Regular bus", "Bus for special needs", "Parent contract", "Other"]
TRANSPORT_NEEDS = ["Bus assistance: Adult support", "Bus assistance: Medical support",
                   "Preferential seating", "Behavioral Intervention Plan", "Wheelchair lift",
                   "Restraint system", "Other"]
NONACADEMIC_OPTIONS = ["YES", "YES, with supports", "NO"]
TRANSITION_ASSESSMENTS = ["Student Interview", "Career Awareness", "Interest Inventory",
                          "Parent Interview", "Student Portfolio", "Interest Learning Profile",
                          "Student Survey", "Vocational Assessment", "Career Aptitude", "Other"]
PATHWAYS = ["General Education Pathway", "Essentials Pathway",
            "Alternate Achievement Standards Pathway"]
EVALUATION_TYPES = ["Curriculum Based Assessment", "Teacher/Text Test", "Teacher Observation",
                    "Grades", "Data Collection", "State Assessment(s)", "Work Samples", "Other"]
SERVICE_CATEGORIES = [
    ("special_education", "Special Education"),
    ("related_services", "Related Services"),
    ("supplementary_aids", "Supplementary Aids and Services"),
    ("program_modifications", "Program Modifications"),
    ("assessment_accommodations", "Accommodations Needed for Assessments"),
    ("assistive_technology", "Assistive Technology"),
    ("support_for_personnel", "Support for Personnel"),
]
PROFILE_FIELDS = [
    ("strengths", "Strengths of the student"),
    ("parent_concerns", "Parental concerns for enhancing the education"),
    ("preferences_interests", "Student Preferences and/or Interests"),
    ("evaluation_results", "Results of the most recent evaluations"),
    ("needs", "The academic, developmental, and functional needs of the student"),
    ("other", "Other"),
    ("ei_transition_justification", "For the child transitioning from EI to Preschool, justify if the "
                                    "IEP will not be implemented on the child's 3rd birthday"),
]
POSTSECONDARY_AREAS = [
    ("education", "Postsecondary Education/Training Goal"),
    ("employment", "Employment/Occupation/Career Goal"),
    ("independent_living", "Community/Independent Living Goal"),
]
DEFAULT_PARTICIPANTS = [
    "Parent", "Parent", "General Education Teacher", "Special Education Teacher",
    "LEA Representative",
    "Someone Who Can Interpret the Instructional Implications of the Evaluation Results",
    "Student", "Career/Technical Education Representative", "Other Agency Representative",
]


def empty_service() -> dict:
    return {"service": "", "frequency": "", "amount": "", "begin": "", "end": "", "location": ""}


def empty_goal() -> dict:
    return {"area": "", "present_level": "", "goal": "", "mastery_date": "",
            "evaluation": [], "evaluation_other": "",
            "benchmarks": [{"text": "", "date": ""}, {"text": "", "date": ""}]}


def empty_iep() -> dict:
    return {
        # Not on the form, but the app needs them
        "meta": {"eligibility": "", "school": "", "case_manager": ""},
        # Page 1
        "student_name": "", "dob": "", "school_year": "", "grade": "",
        "iep_from": "", "iep_to": "",
        "profile": {k: "" for k, _ in PROFILE_FIELDS},
        # Page 2
        "special_factors": {k: None for k, _ in SPECIAL_FACTORS},  # True / False / None
        "transportation": {"mode": "Regular bus", "mode_other": "", "related_service": False,
                           "transport_rep_involved": False, "needs": [], "needs_details": ""},
        "nonacademic": {"participation": "YES", "description": ""},
        "progress_report_weeks": "",
        # Pages 3-4 (only when transition applies: age 14+/9th grade)
        "transition": {
            "applicable": False,
            "student_invited_date": "", "student_invited_via": "",
            "agencies_invited": False, "addressed_on_goal_page": False,
            "assessments": [], "assessment_other": "",
            "postsecondary": {k: {"assessments": [{"name": "", "date": ""}, {"name": "", "date": ""}],
                                  "long_term_goal": "", "other": ""}
                              for k, _ in POSTSECONDARY_AREAS},
            "middle_school_course": False,
            "exit_month": "", "exit_year": "", "pathway": "",
            "credits": {p: {"english": "", "math": "", "science": "", "social_studies": ""}
                        for p in PATHWAYS},
            "electives": "",
        },
        "transition_goals": {
            "present_level": "",
            **{k: {"goal": "", "mastery_date": "", "services": "", "activities": [], "people": ""}
               for k, _ in POSTSECONDARY_AREAS},
        },
        # Page 5 (one per goal)
        "goals": [],
        # Page 6
        "services": {k: {"needed": k == "special_education", "rows": []} for k, _ in SERVICE_CATEGORIES},
        # Page 7
        "transfer_of_rights_date": "",
        "esy_considered": None,
        "lre": {"attends_home_school": True, "home_school_explain": "",
                "all_with_nondisabled": True, "nondisabled_explain": "",
                "age_group": "6-21", "setting": ""},
        "copies": {"iep_given": None, "iep_sent_date": "", "rights_given": None,
                   "rights_sent_date": "", "amended_sent_date": ""},
        "participants": [{"position": p, "name": "", "date": ""} for p in DEFAULT_PARTICIPANTS],
        "not_in_attendance": [],
    }


# ---------------------------------------------------------------------------
# Merging (used when importing AI-extracted data, so the shape stays correct)
# ---------------------------------------------------------------------------
_WHOLE_IEP = object()


def conform(data, template=_WHOLE_IEP):
    """Return `data` reshaped to match the empty IEP: unknown keys dropped,
    missing keys filled, wrong types replaced with the default."""
    if template is _WHOLE_IEP:
        template = empty_iep()
    if isinstance(template, dict):
        if not isinstance(data, dict):
            return copy.deepcopy(template)
        return {k: conform(data.get(k), v) for k, v in template.items()}
    if isinstance(template, list):
        if not isinstance(data, list):
            return copy.deepcopy(template)
        return data  # list items are checked by the specific fixers below
    if template is None:  # yes/no fields
        return data if isinstance(data, bool) else None
    if isinstance(template, bool):
        return data if isinstance(data, bool) else template
    return "" if data is None else str(data)


def normalize(iep: dict) -> dict:
    """Make every list item have the right fields too."""
    iep = conform(iep)
    iep["goals"] = [conform(g, empty_goal()) for g in iep["goals"] if isinstance(g, dict)]
    for g in iep["goals"]:
        g["benchmarks"] = [conform(b, {"text": "", "date": ""}) for b in g["benchmarks"]
                           if isinstance(b, dict)]
        g["evaluation"] = [e for e in g["evaluation"] if isinstance(e, str)]
    for cat in iep["services"].values():
        cat["rows"] = [conform(r, empty_service()) for r in cat["rows"] if isinstance(r, dict)]
    for key in ("participants", "not_in_attendance"):
        iep[key] = [conform(p, {"position": "", "name": "", "date": ""})
                    for p in iep[key] if isinstance(p, dict)]
    for k, _ in POSTSECONDARY_AREAS:
        tg = iep["transition_goals"][k]
        tg["activities"] = [str(a) for a in tg["activities"] if a]
        ps = iep["transition"]["postsecondary"][k]
        ps["assessments"] = [conform(a, {"name": "", "date": ""}) for a in ps["assessments"]
                             if isinstance(a, dict)]
    return iep


# ---------------------------------------------------------------------------
# Reading / writing one field by its path, e.g. "goals.0.goal"
# ---------------------------------------------------------------------------
def _parts(path: str) -> list:
    return [int(p) if p.isdigit() else p for p in path.split(".")]


def get_path(iep: dict, path: str):
    node = iep
    for p in _parts(path):
        node = node[p]
    return node


def set_path(iep: dict, path: str, value) -> None:
    parts = _parts(path)
    node = iep
    for p in parts[:-1]:
        node = node[p]
    old = node[parts[-1]]
    if isinstance(old, list) and isinstance(value, str):  # e.g. transition activities
        value = [v.strip(" -•\t") for v in value.splitlines() if v.strip()]
    node[parts[-1]] = value


def label_for(path: str) -> str:
    """Human-readable name of a field, for the change log and the screen."""
    p = _parts(path)
    names = dict(PROFILE_FIELDS)
    if p[0] == "profile" and len(p) > 1:
        return f"Student Profile – {names.get(p[1], p[1])}"
    if p[0] == "goals" and len(p) > 1:
        rest = {"area": "Area", "present_level": "Present level", "goal": "Measurable annual goal",
                "mastery_date": "Date of mastery", "benchmarks": "Benchmark",
                "evaluation": "Type(s) of evaluation"}
        extra = rest.get(p[2], p[2]) if len(p) > 2 else ""
        if len(p) > 3 and isinstance(p[3], int):
            extra += f" {p[3] + 1}"
        return f"Annual Goal {p[1] + 1}" + (f" – {extra}" if extra else "")
    if p[0] == "services" and len(p) > 1:
        return f"Services – {dict(SERVICE_CATEGORIES).get(p[1], p[1])}"
    if p[0] == "transition_goals" and len(p) > 1:
        return f"Transition Goal – {dict(POSTSECONDARY_AREAS).get(p[1], p[1].replace('_', ' ').title())}"
    return path.replace("_", " ").replace(".", " – ").title()


def text_fields(iep: dict, prefix: str = "") -> list[tuple[str, str]]:
    """Every text field with a value: [(path, value)]. Used to show the AI what it can change."""
    out = []
    if isinstance(iep, dict):
        for k, v in iep.items():
            if k in ("participants", "not_in_attendance", "copies", "credits"):
                continue
            out += text_fields(v, f"{prefix}{k}.")
    elif isinstance(iep, list) and all(isinstance(x, str) for x in iep) and prefix.endswith("activities."):
        if iep:
            out.append((prefix[:-1], "\n".join(iep)))
    elif isinstance(iep, list):
        for i, v in enumerate(iep):
            out += text_fields(v, f"{prefix}{i}.")
    elif isinstance(iep, str) and iep.strip():
        out.append((prefix[:-1], iep))
    return out


# ---------------------------------------------------------------------------
# Plain-text version in form order (for the AI and for search)
# ---------------------------------------------------------------------------
def _yn(v) -> str:
    return "YES" if v is True else "NO" if v is False else "not answered"


def to_sections(iep: dict) -> list[tuple[str, str]]:
    """The IEP as (section title, text) pairs, in the order of the paper form."""
    s = []
    s.append(("Student information", "\n".join([
        f"Student's name: {iep['student_name']}", f"DOB: {iep['dob']}",
        f"School year: {iep['school_year']}", f"Grade: {iep['grade']}",
        f"IEP initiation/duration dates: from {iep['iep_from']} to {iep['iep_to']}",
        f"Eligibility: {iep['meta']['eligibility']}", f"School: {iep['meta']['school']}",
        f"Case manager: {iep['meta']['case_manager']}",
    ])))
    s.append(("Student Profile", "\n".join(
        f"{label}: {iep['profile'][k] or 'Not stated'}" for k, label in PROFILE_FIELDS
        if k != "ei_transition_justification" or iep["profile"][k])))
    s.append(("Special Instructional Factors", "\n".join(
        f"{q} {_yn(iep['special_factors'][k])}" for k, q in SPECIAL_FACTORS)))
    t = iep["transportation"]
    s.append(("Transportation, Nonacademic Activities and Progress Reporting", "\n".join([
        f"Mode of transportation: {t['mode']}{' – ' + t['mode_other'] if t['mode_other'] else ''}",
        f"Transportation as a related service: {_yn(t['related_service'])}",
        f"Transportation needs: {', '.join(t['needs']) or 'none'} {t['needs_details']}".strip(),
        f"Nonacademic/extracurricular participation with nondisabled peers: "
        f"{iep['nonacademic']['participation']} {iep['nonacademic']['description']}".strip(),
        f"Progress reports sent to parents with report cards every {iep['progress_report_weeks'] or '__'} weeks.",
    ])))
    tr = iep["transition"]
    if tr["applicable"]:
        lines = [f"Transition assessments used: {', '.join(tr['assessments']) or 'none'}"]
        for k, label in POSTSECONDARY_AREAS:
            ps = tr["postsecondary"][k]
            used = "; ".join(f"{a['name']} ({a['date']})" for a in ps["assessments"] if a["name"])
            lines.append(f"{label}: {ps['long_term_goal'] or 'Not stated'}"
                         + (f" [assessments: {used}]" if used else ""))
        lines += [f"Anticipated exit: {tr['exit_month']} {tr['exit_year']}",
                  f"Pathway: {tr['pathway'] or 'Not selected'}"]
        s.append(("Transition", "\n".join(lines)))
        tg = iep["transition_goals"]
        lines = [f"Present level (transition): {tg['present_level']}"]
        for k, label in POSTSECONDARY_AREAS:
            g = tg[k]
            lines.append(f"{label}: {g['goal']} (mastery: {g['mastery_date']}); "
                         f"services: {g['services']}; activities: "
                         + "; ".join(f"{i}. {a}" for i, a in enumerate(g["activities"], 1))
                         + f"; people/agency: {g['people']}")
        s.append(("Annual Transition Goals", "\n".join(lines)))
    else:
        s.append(("Transition", "Transition pages not applicable (student is under 14 and not in 9th grade)."))
    for i, g in enumerate(iep["goals"], 1):
        bm = "\n".join(f"  Benchmark {j}: {b['text']} (mastery: {b['date']})"
                       for j, b in enumerate(g["benchmarks"], 1) if b["text"])
        ev = ", ".join(g["evaluation"]) + (f" ({g['evaluation_other']})" if g["evaluation_other"] else "")
        s.append((f"Annual Goal {i}: {g['area']}", "\n".join([
            f"Area: {g['area']}", f"Present level: {g['present_level']}",
            f"Measurable annual goal: {g['goal']}", f"Date of mastery: {g['mastery_date']}",
            f"Type(s) of evaluation: {ev or 'none checked'}", bm,
        ]).strip()))
    lines = []
    for k, label in SERVICE_CATEGORIES:
        cat = iep["services"][k]
        if not cat["rows"]:
            lines.append(f"{label}: {'Needed (none listed)' if cat['needed'] else 'Not needed'}")
            continue
        lines.append(f"{label}:")
        for r in cat["rows"]:
            lines.append(f"  - {r['service']} | frequency: {r['frequency']} | amount: {r['amount']} | "
                         f"{r['begin']} to {r['end']} | location: {r['location']}")
    s.append(("Special Education and Related Services", "\n".join(lines)))
    lre = iep["lre"]
    s.append(("Transfer of Rights, ESY and Least Restrictive Environment", "\n".join([
        f"Date informed of transfer of rights: {iep['transfer_of_rights_date'] or 'n/a'}",
        f"Extended school year considered: {_yn(iep['esy_considered'])}",
        f"Attends school he/she would attend if nondisabled: {_yn(lre['attends_home_school'])} "
        f"{lre['home_school_explain']}".strip(),
        f"Receives all special education services with nondisabled peers: {_yn(lre['all_with_nondisabled'])} "
        f"{lre['nondisabled_explain']}".strip(),
        f"Least restrictive environment ({lre['age_group']}): {lre['setting']}",
    ])))
    people = "; ".join(f"{p['position']}: {p['name']}" for p in iep["participants"] if p["name"])
    s.append(("IEP Team", f"Attended: {people or 'not recorded'}"))
    return s


def to_text(iep: dict) -> str:
    return "\n\n".join(f"== {title} ==\n{body}" for title, body in to_sections(iep))


def make_student_id(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")