"""
core.py - all the AI and storage logic for the IEP Assistant.

- Each student's IEP is stored as structured data following the Alabama IEP
  form (see iep_schema.py) in data/students/<id>/iep.json.
- Every save keeps the old version in data/students/<id>/versions, so any
  change can be undone.
- Extra documents (evaluations, progress notes) are split into chunks and
  stored in ChromaDB, tagged with the student's ID, for question answering.
- The AI suggests changes to specific IEP fields. Nothing changes until the
  teacher approves.
"""

import copy
import datetime
import io
import json
import re
import shutil
import uuid
from pathlib import Path

import chromadb
import ollama
from pypdf import PdfReader

import iep_schema as S

# ---------------------------------------------------------------------------
# Settings - change these to match the models you pulled with Ollama.
# Check exact names at https://ollama.com/library
# ---------------------------------------------------------------------------
CHAT_MODEL = "qwen3:8b"           # try a smaller one (e.g. qwen3:4b) if this is slow
EMBED_MODEL = "nomic-embed-text"  # small model used only for search
MAX_DOC_CHARS = 32000             # how much of an uploaded file we send to the AI
OCR_DPI = 200                     # higher = better OCR on scans, but slower

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
STUDENTS_DIR = DATA_DIR / "students"
LOG_FILE = DATA_DIR / "change_log.json"
ACC_FILE = DATA_DIR / "accommodations.json"
STUDENTS_DIR.mkdir(parents=True, exist_ok=True)

_client = chromadb.PersistentClient(path=str(DATA_DIR / "chroma"))
_col = _client.get_or_create_collection("student_docs", metadata={"hnsw:space": "cosine"})

make_student_id = S.make_student_id


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _safe(name: str) -> str:
    return re.sub(r"[^\w.-]", "_", name)


# ---------------------------------------------------------------------------
# Talking to the model
# ---------------------------------------------------------------------------
def _chat(system: str, user: str, json_mode: bool = False, ctx: int = 16384) -> str:
    kwargs = {
        "model": CHAT_MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "options": {"temperature": 0.2, "num_ctx": ctx},  # room for a whole IEP
        "think": False,  # turn off Qwen's long "thinking" for speed
    }
    if json_mode:
        kwargs["format"] = "json"
    reply = ollama.chat(**kwargs)["message"]["content"]
    return re.sub(r"<think>.*?</think>", "", reply, flags=re.DOTALL).strip()


def _chat_json(system: str, user: str, ctx: int = 16384) -> dict:
    raw = _chat(system, user, json_mode=True, ctx=ctx)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------------------
# Students and their IEPs
# ---------------------------------------------------------------------------
def _folder(sid: str) -> Path:
    return STUDENTS_DIR / sid


def list_students() -> dict[str, str]:
    """Returns {student_id: student_name}, sorted by name."""
    found = {}
    for f in STUDENTS_DIR.glob("*/iep.json"):
        found[f.parent.name] = json.loads(f.read_text()).get("student_name") or f.parent.name
    return dict(sorted(found.items(), key=lambda kv: kv[1].lower()))


def get_iep(sid: str) -> dict:
    return S.normalize(json.loads((_folder(sid) / "iep.json").read_text()))


def create_student(iep: dict) -> str:
    iep = S.normalize(iep)
    if not iep["student_name"].strip():
        raise ValueError("The IEP has no student name.")
    sid = make_student_id(iep["student_name"])
    folder = _folder(sid)
    if (folder / "iep.json").exists():
        save_iep(sid, iep, note="Replaced with a newly imported IEP")
    else:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "iep.json").write_text(json.dumps(iep, indent=2))
    return sid


def save_iep(sid: str, iep: dict, note: str = "") -> bool:
    """Save a new version. The old one goes to the versions folder."""
    iep = S.normalize(iep)
    path = _folder(sid) / "iep.json"
    old = path.read_text()
    if json.loads(old) == iep:
        return True
    vdir = _folder(sid) / "versions"
    vdir.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    (vdir / f"{stamp}.json").write_text(old)
    (vdir / f"{stamp}.note").write_text(note)
    path.write_text(json.dumps(iep, indent=2))
    return True


def list_versions(sid: str) -> list[dict]:
    vdir = _folder(sid) / "versions"
    if not vdir.exists():
        return []
    out = []
    for f in sorted(vdir.glob("*.json"), reverse=True):
        when = datetime.datetime.strptime(f.stem, "%Y%m%d-%H%M%S-%f")
        note = f.with_suffix(".note")
        out.append({"when": when.strftime("%b %d, %I:%M:%S %p"),
                    "note": note.read_text() if note.exists() else "",
                    "iep": S.normalize(json.loads(f.read_text()))})
    return out


def delete_student(sid: str) -> None:
    _col.delete(where={"student_id": sid})
    shutil.rmtree(_folder(sid), ignore_errors=True)


def load_sample(path: Path) -> str:
    return create_student(json.loads(Path(path).read_text()))


def get_profile(sid: str) -> dict:
    iep = get_iep(sid)
    return {
        "name": iep["student_name"], "dob": iep["dob"], "grade": iep["grade"],
        "eligibility": iep["meta"]["eligibility"], "school": iep["meta"]["school"],
        "case_manager": iep["meta"]["case_manager"], "goals": len(iep["goals"]),
        "dates": f"{iep['iep_from']} – {iep['iep_to']}" if iep["iep_from"] else "",
        "transition": iep["transition"]["applicable"],
    }


def get_dashboard() -> list[dict]:
    """Return a summary row for every student — used by the class dashboard."""
    rows = []
    today = datetime.date.today()
    for sid, name in list_students().items():
        try:
            iep = get_iep(sid)
        except Exception:  # noqa: BLE001
            continue
        # Next benchmark date across all goals
        next_bm_date, next_bm_text = None, ""
        for g in iep["goals"]:
            for bm in g["benchmarks"]:
                if bm.get("text") and bm.get("date"):
                    try:
                        d = datetime.datetime.strptime(bm["date"], "%m/%d/%Y").date()
                        if next_bm_date is None or d < next_bm_date:
                            next_bm_date = d
                            next_bm_text = bm["text"][:60] + ("…" if len(bm["text"]) > 60 else "")
                    except ValueError:
                        pass
        # IEP expiry
        iep_to_date = None
        if iep["iep_to"]:
            try:
                iep_to_date = datetime.datetime.strptime(iep["iep_to"], "%m/%d/%Y").date()
            except ValueError:
                pass
        days_to_expiry = (iep_to_date - today).days if iep_to_date else None
        # Urgency: red < 30 days, yellow < 90 days, green otherwise
        if days_to_expiry is None:
            urgency = "—"
        elif days_to_expiry < 0:
            urgency = "🔴 Expired"
        elif days_to_expiry < 30:
            urgency = f"🔴 {days_to_expiry}d"
        elif days_to_expiry < 90:
            urgency = f"🟡 {days_to_expiry}d"
        else:
            urgency = f"🟢 {days_to_expiry}d"
        rows.append({
            "sid": sid,
            "name": name,
            "grade": iep["grade"],
            "eligibility": iep["meta"]["eligibility"],
            "goals": len(iep["goals"]),
            "iep_to": iep["iep_to"],
            "days_to_expiry": days_to_expiry,
            "urgency": urgency,
            "next_benchmark": next_bm_date.strftime("%b %d, %Y") if next_bm_date else "—",
            "next_bm_text": next_bm_text,
            "case_manager": iep["meta"]["case_manager"],
        })
    rows.sort(key=lambda r: (r["days_to_expiry"] is None, r["days_to_expiry"] or 9999))
    return rows


# ---------------------------------------------------------------------------
# Uploaded files
# ---------------------------------------------------------------------------
def extract_text(filename: str, data: bytes) -> str:
    """Get plain text out of a PDF or TXT file. Scanned PDFs (pictures of
    pages, no real text inside) are read with OCR."""
    if not filename.lower().endswith(".pdf"):
        return data.decode("utf-8", errors="ignore")
    reader = PdfReader(io.BytesIO(data))
    text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
    if len(text.strip()) >= 100 * max(1, len(reader.pages)) // 4:
        return text
    return ocr_pdf(data)


def ocr_pdf(data: bytes) -> str:
    """Turn each page into an image and read it with Tesseract OCR."""
    try:
        import pymupdf
        import pytesseract
        from PIL import Image
    except ImportError as e:
        raise ValueError("This PDF is a scan and needs OCR. Install it with: "
                         "pip install pymupdf pytesseract") from e
    try:
        pytesseract.get_tesseract_version()
    except Exception as e:  # noqa: BLE001
        raise ValueError("This PDF is a scan and needs the Tesseract OCR program. "
                         "On Mac run: brew install tesseract  (then restart the app)") from e
    pages = []
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for i, page in enumerate(doc, 1):
            pix = page.get_pixmap(dpi=OCR_DPI)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            pages.append(f"--- Page {i} ---\n{pytesseract.image_to_string(img)}")
    text = "\n\n".join(pages)
    if len(text.strip()) < 50:
        raise ValueError("OCR found almost no text. The scan may be too blurry.")
    return text


def import_iep(text: str, name: str = "") -> dict:
    """Use the AI to copy an IEP (any layout) into the Alabama template fields.
    The teacher should check the result - extraction is never perfect."""
    if not text.strip():
        raise ValueError("No text found. Is this a scanned PDF? (needs OCR)")
    skeleton = S.empty_iep()
    skeleton["goals"] = [S.empty_goal()]
    for k in skeleton["services"]:
        skeleton["services"][k]["rows"] = [S.empty_service()]
    for k in ("participants", "not_in_attendance", "copies"):
        skeleton.pop(k)
    skeleton["transition"].pop("credits")

    data = _chat_json(
        "You copy information from an IEP document into a JSON form. Copy facts exactly. "
        "Never invent information: leave a field as \"\" (or null for yes/no) if the document "
        "doesn't say. Use true/false for yes/no questions. Add one goals entry per annual goal "
        "and one row per service. Respond with JSON only.",
        f"""Fill in this JSON form using the IEP document below.
- meta.eligibility = the disability category(ies).
- goals = each annual goal with its area, present level, goal text, evaluation types and benchmarks.
- services = put each service in the right category: special_education, related_services,
  supplementary_aids (classroom accommodations), program_modifications,
  assessment_accommodations (testing accommodations), assistive_technology, support_for_personnel.
- transition.applicable = true only if the student is 14+ or in 9th grade or above.

FORM:
{json.dumps(skeleton)}

IEP DOCUMENT:
{text[:MAX_DOC_CHARS]}""",
        ctx=32768,  # long scanned IEPs need a bigger window
    )
    if not data:
        raise ValueError("The AI couldn't read this document. Try a text-based PDF or TXT.")
    iep = S.normalize(data)
    for cat in iep["services"].values():  # drop empty rows the AI left in
        cat["rows"] = [r for r in cat["rows"] if r["service"].strip()]
        if cat["rows"]:
            cat["needed"] = True
    iep["goals"] = [g for g in iep["goals"] if g["goal"].strip()]
    if name.strip():  # the teacher's typed name wins (scans often have names blacked out)
        iep["student_name"] = name.strip()
    if not iep["student_name"].strip():
        raise ValueError("Couldn't find the student's name in the file. Type it in the "
                         "'Student name' box and import again.")
    return iep


def _embed(texts: list[str]) -> list[list[float]]:
    return ollama.embed(model=EMBED_MODEL, input=texts)["embeddings"]


def chunk_text(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, current = [], ""
    for p in paragraphs:
        if current and len(current) + len(p) > size:
            chunks.append(current)
            current = current[-overlap:] + "\n" + p
        else:
            current = f"{current}\n\n{p}" if current else p
    if current:
        chunks.append(current)
    final = []
    for c in chunks:
        while len(c) > size * 2:
            final.append(c[: size * 2])
            c = c[size * 2 - overlap :]
        final.append(c)
    return final


def add_supporting_doc(sid: str, filename: str, text: str) -> int:
    """Evaluations, progress notes, emails... searchable when answering questions."""
    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("No text found. Is this a scanned PDF? (needs OCR)")
    embeddings = _embed(chunks)
    _col.delete(where={"$and": [{"student_id": sid}, {"source": filename}]})
    _col.add(
        ids=[f"{sid}-{uuid.uuid4().hex}" for _ in chunks],
        documents=chunks, embeddings=embeddings,
        metadatas=[{"student_id": sid, "source": filename, "chunk": i} for i in range(len(chunks))],
    )
    return len(chunks)


def list_supporting_docs(sid: str) -> list[str]:
    metas = _col.get(where={"student_id": sid}, include=["metadatas"])["metadatas"] or []
    return sorted({m["source"] for m in metas})


def retrieve(sid: str, query: str, k: int = 4) -> list[tuple[str, dict]]:
    """Search this student's extra documents. The where-filter keeps students separate."""
    available = len(_col.get(where={"student_id": sid})["ids"])
    if available == 0:
        return []
    res = _col.query(query_embeddings=_embed([query]), n_results=min(k, available),
                     where={"student_id": sid}, include=["documents", "metadatas"])
    return list(zip(res["documents"][0], res["metadatas"][0]))


# ---------------------------------------------------------------------------
# Summary, questions, answers
# ---------------------------------------------------------------------------
def _context(sid: str, query: str = "") -> tuple[str, list]:
    """The whole IEP (it is small enough) plus matching extra documents."""
    iep_text = S.to_text(get_iep(sid))
    docs = retrieve(sid, query) if query else []
    extra = "\n\n".join(f"[D{i}] (from {m['source']})\n{d}" for i, (d, m) in enumerate(docs, 1))
    return iep_text + (f"\n\n== Other documents ==\n{extra}" if extra else ""), docs


def summarize(sid: str) -> str:
    text, _ = _context(sid)
    return _chat(
        "You help special education teachers read IEPs. Use ONLY the IEP given. "
        "If something is not in it, write 'Not stated'. Never invent details.",
        f"""Summarize this IEP for a busy teacher in plain English. Use these headings:

## Who this student is
## Strengths and needs
## Annual goals (each goal, how it's measured, next benchmark)
## Accommodations in class
## Accommodations on tests
## Services (type, how often, how long, where)
## Transition plan (only if the IEP has one)
## Key dates
## Things to watch

IEP:
{text}""",
    )


def answer(sid: str, question: str) -> tuple[str, list]:
    text, docs = _context(sid, question)
    reply = _chat(
        "You answer teacher questions about ONE student's IEP. Use ONLY the text given. "
        "After each fact, name where it came from in brackets, using the section title, "
        "e.g. [Student Profile] or [Annual Goal 2], or [D1] for other documents. "
        "If the answer is not there, say: \"I couldn't find that in this student's IEP.\" "
        "Do not guess.",
        f"{text}\n\nQUESTION: {question}",
    )
    return reply, docs


QUESTION_BY_ELIGIBILITY = {
    "learning disability": "What reading or writing supports does {f} need in class?",
    "adhd": "What helps {f} stay focused during independent work?",
    "health impairment": "What helps {f} stay focused during independent work?",
    "autism": "How should I prepare {f} for schedule changes or group work?",
    "speech": "What communication supports does {f} need?",
    "emotional": "What triggers and behavior supports should I know about for {f}?",
    "hearing": "What hearing supports or equipment does {f} use?",
    "visual": "What vision supports or materials does {f} need?",
    "intellectual": "How are assignments modified for {f}?",
}


def suggested_questions(sid: str) -> list[str]:
    """Quick questions built from the IEP itself - no AI call needed."""
    iep = get_iep(sid)
    f = iep["student_name"].split()[0] if iep["student_name"] else "this student"
    elig = iep["meta"]["eligibility"].lower()
    qs = []
    for key, q in QUESTION_BY_ELIGIBILITY.items():
        q = q.format(f=f)
        if key in elig and q not in qs:
            qs.append(q)
    qs += [f"What are {f}'s annual goals and the next benchmark dates?",
           f"What accommodations does {f} get on tests?"]
    if iep["transition"]["applicable"]:
        qs.append(f"What is {f}'s transition plan after high school?")
    qs += [f"What services does {f} receive, how often and where?",
           f"What are the parents' main concerns about {f}?",
           f"What are {f}'s strengths I can build on?"]
    return qs[:6]


def ai_questions(sid: str) -> list[str]:
    iep = get_iep(sid)
    data = _chat_json(
        "You help special education teachers. Respond with JSON only.",
        f"""Read this IEP for {iep['student_name']}. Write 5 short, specific questions a
teacher would want answered before working with this student tomorrow.
Only ask questions this IEP can answer. Return: {{"questions": ["..."]}}

IEP:
{S.to_text(iep)}""",
    )
    return [q for q in data.get("questions", []) if isinstance(q, str)][:5]


# ---------------------------------------------------------------------------
# Suggesting and applying IEP changes
# ---------------------------------------------------------------------------
CATEGORY_KEYS = [k for k, _ in S.SERVICE_CATEGORIES]


def _make_change(iep: dict, field: str, new_value: str, reason: str, source: str) -> dict | None:
    try:
        current = S.get_path(iep, field)
    except (KeyError, IndexError, TypeError):
        return None
    if isinstance(current, list):
        current = "\n".join(str(x) for x in current)
    if not isinstance(current, str) or not str(new_value).strip():
        return None
    return {"action": "change", "field": field, "section": S.label_for(field),
            "current_text": current or "(empty)", "suggested_text": str(new_value).strip(),
            "reason": reason, "source": source}


def _make_service(iep: dict, category: str, row: dict, reason: str, source: str) -> dict | None:
    if category not in CATEGORY_KEYS or not str(row.get("service", "")).strip():
        return None
    full = S.empty_service()
    full.update({k: str(v) for k, v in row.items() if k in full})
    full["begin"] = full["begin"] or iep["iep_from"]
    full["end"] = full["end"] or iep["iep_to"]
    return {"action": "add_service", "category": category,
            "section": f"Add to {dict(S.SERVICE_CATEGORIES)[category]}",
            "current_text": "(new row)", "suggested_text": full["service"], "payload": full,
            "reason": reason, "source": source}


def _make_goal(iep: dict, g: dict, reason: str, source: str) -> dict | None:
    if not str(g.get("goal", "")).strip():
        return None
    goal = S.empty_goal()
    goal.update({k: g[k] for k in ("area", "present_level", "goal") if isinstance(g.get(k), str)})
    goal["evaluation"] = [e for e in g.get("evaluation", []) if e in S.EVALUATION_TYPES] or ["Data Collection"]
    goal["mastery_date"] = iep["iep_to"]
    bms = [b for b in g.get("benchmarks", []) if isinstance(b, str) and b.strip()]
    goal["benchmarks"] = [{"text": b, "date": ""} for b in bms] or goal["benchmarks"]
    return {"action": "add_goal", "section": f"New Annual Goal: {goal['area']}",
            "current_text": "(new goal)", "suggested_text": goal["goal"], "payload": goal,
            "reason": reason, "source": source}


def suggest_updates(sid: str, teacher_note: str) -> list[dict]:
    """The AI only SUGGESTS. Nothing changes unless the teacher approves."""
    iep = get_iep(sid)
    fields = "\n".join(f"{path}: {value}" for path, value in S.text_fields(iep)
                       if not path.startswith(("meta", "dob", "school_year", "lre.age_group")))
    try:
        refs = recommend_accommodations(sid, extra_text=teacher_note, k=6)
    except Exception:  # noqa: BLE001 - the dataset is optional
        refs = []
    ref_text = "\n".join(
        f"[A{i}] {a.get('name')} (evidence: {a.get('evidence_level')}, "
        f"{'testing' if a.get('assessment_use') else ''} {'class' if a.get('instructional_use') else ''}): "
        f"{a.get('description')}" for i, a in enumerate(refs, 1)) or "None."
    _, docs = _context(sid, teacher_note)
    doc_text = "\n".join(f"[D{i}] {d[:600]}" for i, (d, _) in enumerate(docs, 1)) or "None."

    data = _chat_json(
        "You help special education teachers draft IEP updates for IEP team review, using the "
        "Alabama IEP form. Base every suggestion on the teacher's note. Goals must be specific "
        "and measurable. Do not invent student data. Only use a reference accommodation if it "
        "fits the note. Respond with JSON only.",
        f"""CURRENT IEP FIELDS (field path: value):
{fields}

OTHER STUDENT DOCUMENTS:
{doc_text}

REFERENCE ACCOMMODATIONS (public dataset):
{ref_text}

TEACHER NOTE:
{teacher_note}

Suggest 1 to 4 changes. Each suggestion is ONE of these:
1. Change a field:  {{"action": "change", "field": "<exact field path from the list>", "new_value": "...", "reason": "...", "source": "teacher note"}}
2. Add a service or accommodation row:  {{"action": "add_service", "category": "<one of {CATEGORY_KEYS}>", "service": "...", "frequency": "...", "amount": "...", "location": "...", "reason": "...", "source": "A1 or teacher note"}}
3. Add a new annual goal:  {{"action": "add_goal", "area": "...", "present_level": "...", "goal": "...", "evaluation": ["Data Collection"], "benchmarks": ["...", "..."], "reason": "...", "source": "teacher note"}}

Use "supplementary_aids" for classroom accommodations and "assessment_accommodations" for testing.
Return: {{"suggestions": [ ... ]}}""",
    )

    out = []
    for s in data.get("suggestions", []):
        if not isinstance(s, dict):
            continue
        reason, source = str(s.get("reason", "")), str(s.get("source", "teacher note"))
        a = re.match(r"A(\d+)", source)
        if a and 1 <= int(a.group(1)) <= len(refs):
            source = f"dataset: {refs[int(a.group(1)) - 1].get('name', '')}"
        action = s.get("action")
        if action == "change":
            item = _make_change(iep, str(s.get("field", "")), s.get("new_value", ""), reason, source)
        elif action == "add_service":
            item = _make_service(iep, s.get("category", ""), s, reason, source)
        elif action == "add_goal":
            item = _make_goal(iep, s, reason, source)
        else:
            item = None
        if item:
            out.append(item)
    return out


def apply_suggestion(sid: str, s: dict, teacher: str) -> str:
    """Write an approved suggestion into the IEP (old version is kept)."""
    iep = get_iep(sid)
    text = s["suggested_text"].strip()
    if s["action"] == "change":
        S.set_path(iep, s["field"], text)
    elif s["action"] == "add_service":
        row = {**s["payload"], "service": text}
        iep["services"][s["category"]]["rows"].append(row)
        iep["services"][s["category"]]["needed"] = True
    elif s["action"] == "add_goal":
        iep["goals"].append({**s["payload"], "goal": text})
    else:
        raise ValueError(f"Unknown action {s['action']}")
    save_iep(sid, iep, note=f"Approved: {s['section']}")
    log_decision(sid, s, "approved", teacher)
    return f"IEP updated: {s['section']}."


# ---------------------------------------------------------------------------
# Accommodations dataset (Hugging Face, CC0)
# ---------------------------------------------------------------------------
_ABBREVIATIONS = {
    "sld": "specific learning disability", "ohi": "other health impairment",
    "aut": "autism", "ed": "emotional disturbance", "ebd": "emotional disturbance",
    "sli": "speech or language impairment", "id": "intellectual disability",
    "tbi": "traumatic brain injury", "vi": "visual impairment",
    "hi": "hearing impairment", "oi": "orthopedic impairment", "md": "multiple disabilities",
}
_KEY_TERMS = ["adhd", "autism", "reading", "dyslexia", "processing", "anxiety",
              "attention", "math", "writing", "behavior", "hearing", "vision",
              "visual", "speech", "language", "executive function", "sensory",
              "fine motor", "memory", "social"]
_cache: dict = {}


def _norm(s) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[_\-/]+", " ", str(s).lower())).strip()


def _as_list(v) -> list:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return list(v)
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
        return [x.strip() for x in re.split(r"[,;|]", v) if x.strip()]
    return [v]


def load_accommodations() -> list[dict]:
    """Load the dataset; download it the first time if needed."""
    if "acc" in _cache:
        return _cache["acc"]
    if not ACC_FILE.exists():
        import prepare_dataset
        prepare_dataset.download_and_convert()
    _cache["acc"] = json.loads(ACC_FILE.read_text()).get("accommodations", [])
    return _cache["acc"]


def recommend_accommodations(sid: str, extra_text: str = "", k: int = 8) -> list[dict]:
    """Score each dataset accommodation against this student's IEP."""
    accs = load_accommodations()
    iep = get_iep(sid)
    text = _norm(S.to_text(iep) + " " + extra_text)
    eligibility = _norm(f"{iep['meta']['eligibility']} {extra_text}")

    results = []
    for a in accs:
        score, why = 0, []
        for d in _as_list(a.get("applicable_disabilities")):
            d = _norm(d)
            d = _ABBREVIATIONS.get(d, d)
            if d and d in eligibility:
                score += 3
                why.append(d)
        about = _norm(f"{a.get('recommended_for', '')} {a.get('description', '')}")
        for t in _KEY_TERMS:
            if t in text and t in about:
                score += 1
                why.append(t)
        if score == 0:
            continue
        if str(a.get("evidence_level", "")).lower() == "strong":
            score += 1
        short_name = " ".join(_norm(re.sub(r"\(.*?\)", "", a.get("name", ""))).split()[:2])
        results.append({**a, "score": score, "matched_on": sorted(set(why)),
                        "already_in_iep": bool(short_name) and short_name in text})
    results.sort(key=lambda r: (r["already_in_iep"], -r["score"]))
    return results[:k]


def accommodation_to_suggestion(sid: str, a: dict) -> dict:
    iep = get_iep(sid)
    cat = str(a.get("category", "")).lower()
    if "assistive" in cat:
        category = "assistive_technology"
    elif a.get("assessment_use") and not a.get("instructional_use"):
        category = "assessment_accommodations"
    else:
        category = "supplementary_aids"
    reason = (f"Recommended in the accommodations dataset for "
              f"{', '.join(a.get('matched_on', [])) or 'this profile'} "
              f"(evidence: {a.get('evidence_level', 'unknown')}). {a.get('description', '')}")
    return _make_service(iep, category, {"service": a.get("name", ""), "frequency": "Daily",
                                         "amount": "As needed", "location": "All classrooms"},
                         reason, f"dataset: {a.get('name', '')}")


# ---------------------------------------------------------------------------
# Change log - every approve / reject / edit is recorded
# ---------------------------------------------------------------------------
def _read_log() -> list[dict]:
    return json.loads(LOG_FILE.read_text()) if LOG_FILE.exists() else []


def log_decision(sid: str, suggestion: dict, decision: str, teacher: str) -> None:
    log = _read_log()
    entry = {k: v for k, v in suggestion.items() if k != "payload"}
    log.append({"time": _now(), "student_id": sid, "teacher": teacher or "unknown",
                "decision": decision, **entry})
    LOG_FILE.write_text(json.dumps(log, indent=2))


def get_log(sid: str) -> list[dict]:
    return [e for e in reversed(_read_log()) if e["student_id"] == sid]


def blank_iep(name: str) -> dict:
    iep = S.empty_iep()
    iep["student_name"] = name
    return copy.deepcopy(iep)


# ---------------------------------------------------------------------------
# Prior Written Notice (PWN)
# ---------------------------------------------------------------------------
def generate_pwn(sid: str) -> str:
    """Generate a Prior Written Notice document for the current IEP.

    A PWN is required by IDEA every time the school proposes or refuses to
    initiate or change the identification, evaluation, placement, or provision
    of FAPE for a child. This draft must be reviewed and signed by the team.
    """
    iep = get_iep(sid)
    text = S.to_text(iep)
    return _chat(
        "You are a special education compliance specialist. "
        "Write a Prior Written Notice (PWN) that meets IDEA requirements. "
        "Use ONLY the information in the IEP provided. "
        "Never invent facts. Mark any missing required field with [MISSING]. "
        "The document must be professional, plain English, and parent-friendly.",
        f"""Write a Prior Written Notice (PWN) for the IEP below.

Structure the document with these sections:
## Prior Written Notice
**Student:** [name]  **Date:** [iep_from]  **School:** [school]

### Action Proposed by the IEP Team
Summarise what the team is proposing or changing (placement, goals, services).

### Description of Each Proposed Action
List each proposed change or service in plain language.

### Why the Team is Proposing These Actions
Explain the reasons, referencing evaluation results and student needs from the IEP.

### Description of Other Options Considered
Briefly note alternatives considered and why they were rejected.

### Description of Each Evaluation Procedure, Test, or Report Used
List the assessments or data used to make these decisions.

### Sources of Information Used by the Team
List the documents, reports, and evaluations referenced.

### Other Factors Relevant to the Proposal
Note any additional relevant information.

### Parent's Right to Respond
Include a standard statement: Parents have the right to request mediation or a due
process hearing if they disagree with this notice. Contact [school] for more information.

---
IEP:
{text}""",
    )


# ---------------------------------------------------------------------------
# Goal-based Activities & Worksheets
# ---------------------------------------------------------------------------
def generate_activities(sid: str) -> list[dict]:
    """For each annual goal, generate classroom activity ideas and a worksheet prompt.

    Returns a list of dicts: {goal_area, goal_text, activities, worksheet_prompt}
    """
    iep = get_iep(sid)
    if not iep["goals"]:
        return []

    goals_text = "\n\n".join(
        f"Goal {i} – {g['area']}:\n"
        f"Present level: {g['present_level']}\n"
        f"Goal: {g['goal']}\n"
        f"Next benchmark: {g['benchmarks'][0]['text'] if g['benchmarks'] and g['benchmarks'][0]['text'] else 'none'}"
        for i, g in enumerate(iep["goals"], 1)
    )
    name = iep["student_name"].split()[0] if iep["student_name"] else "the student"
    eligibility = iep["meta"]["eligibility"]

    data = _chat_json(
        "You are a special education curriculum specialist. "
        "Generate practical, evidence-based classroom activities and worksheet ideas "
        "tailored to a student's specific IEP goals. "
        "Be concrete and immediately usable by a teacher. "
        "Respond with JSON only.",
        f"""Student: {name}  |  Eligibility: {eligibility}

For each goal below, provide:
- 3 short classroom activity ideas (1-2 sentences each, immediately actionable)
- 1 worksheet/printable idea the teacher can create or find

Return JSON:
{{
  "activities": [
    {{
      "goal_area": "...",
      "goal_text": "...",
      "activities": ["activity 1", "activity 2", "activity 3"],
      "worksheet_prompt": "Describe a worksheet that directly practices this goal."
    }}
  ]
}}

GOALS:
{goals_text}""",
    )
    return data.get("activities", [])
