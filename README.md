# 📘 IEP Assistant
### IBM NorthAmerica AI Challenge — Team GoBiByte

> An agentic AI tool that helps special education teachers dramatically reduce the time it takes to create, update, and manage Individualized Education Plans (IEPs) for every student in their class.

---

## 🎯 The Problem

Special education teachers spend an estimated **3–5 hours per student** creating or updating an IEP — a legally mandated document that governs every service, goal, accommodation, and placement decision for a student with a disability. A typical caseload is 10–20 students.

That means teachers spend **up to 100 hours per year on paperwork** instead of students.

The pain points we heard directly from teachers:

- IEP forms are long, complex, and filled with legal/compliance requirements
- Goals must be specific, measurable, and tied to evaluation data — hard to draft from scratch
- Supporting documents (evaluations, progress notes) are scattered across files and emails
- Prior Written Notices (PWNs) — legally required letters to parents — take hours to write
- Accommodation decisions are often made from memory rather than evidence
- Meeting invitations, summaries, and follow-up emails are all manual
- Medicaid billing, ADL tracking, and safety plans add further paperwork overhead

---

## 💡 The Solution

**IEP Assistant** is a locally-hosted agentic AI application that:

1. **Reads** existing IEP documents (PDF or TXT) and maps them into a structured Alabama ALSDE form
2. **Suggests** specific, measurable goal updates, service changes, and accommodations based on teacher observations
3. **Answers questions** about any student's IEP using the document and any uploaded supporting files
4. **Generates** Prior Written Notices, meeting summaries, parent invitation emails, and goal-based classroom activities — all in one click
5. **Tracks** every decision with a full audit log and version history

> **Human-in-the-loop by design.** The AI only ever *suggests*. Nothing changes until the teacher explicitly approves. Every change is logged and reversible.

> **Privacy-first.** All AI runs locally via [Ollama](https://ollama.com). No student data ever leaves the machine.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Teacher's Browser                         │
│                   Streamlit UI  (app.py)                        │
│                                                                  │
│  Tabs: Ask │ Summary │ Update IEP │ IEP Form │ Accommodations   │
│            │  PWN    │  Contact   │ Activities│    History       │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                    ┌──────▼──────┐
                    │   core.py   │  ← All AI + storage logic
                    └──────┬──────┘
           ┌───────────────┼────────────────┐
           │               │                │
    ┌──────▼──────┐  ┌──────▼──────┐  ┌────▼────────────┐
    │   Ollama    │  │  ChromaDB   │  │  Local JSON     │
    │  (local LLM)│  │  (RAG /     │  │  data/students/ │
    │             │  │  vector DB) │  │  per-student    │
    │ qwen3:8b    │  │             │  │  IEP + versions │
    │ nomic-embed │  │ student docs│  │  + change log   │
    └─────────────┘  └─────────────┘  └─────────────────┘
           │
    ┌──────▼──────┐
    │ iep_schema  │  ← Alabama ALSDE IEP form as structured JSON
    │   .py       │     (every field individually addressable)
    └─────────────┘
           │
    ┌──────▼──────┐
    │ export_pdf  │  ← ReportLab PDF that mirrors the paper form
    │   .py       │     + supplemental Medicaid/ADL/Safety page
    └─────────────┘
```

### Key design decisions

| Decision | Reason |
|---|---|
| **Structured field-level IEP schema** | AI changes one named field at a time (`goals.0.goal`) rather than generating a wall of text — more precise, easier to review |
| **Local LLM via Ollama** | Student PII never leaves the school network; works without internet |
| **RAG on supporting docs** | Teacher can upload evaluations / progress notes; AI answers are grounded in that evidence |
| **Suggest → Approve flow** | IDEA compliance requires human judgment; the tool assists, not decides |
| **Versioned JSON storage** | Every save keeps the previous version; any change can be undone in one click |
| **Evidence-based accommodations dataset** | Recommendations pulled from a CC0 Hugging Face dataset with evidence levels, not just LLM guesses |

---

## ✨ Features

### For the teacher, right now
| Feature | Tab |
|---|---|
| Ask any question about a student's IEP, grounded in the document | 💬 Ask |
| AI-generated student summary (strengths, goals, services, key dates) | 📝 Summary |
| Describe what you observed → AI suggests specific IEP field updates | ✏️ Update IEP |
| Edit every field of the full 7-page Alabama IEP form | 📄 IEP form |
| Evidence-based accommodation recommendations from a public dataset | 🧩 Accommodations |
| Generate a IDEA-compliant Prior Written Notice in one click | 📋 PWN |
| Build a parent meeting invitation with `mailto:` link + post-meeting summary email | 📧 Contact |
| Auto-generate classroom activities and worksheet ideas for each annual goal | 🎯 Activities |
| Full version history with restore and per-decision change log | 🕓 History |

### Supplemental fields (new)
- **Medicaid (MCAID)**: consent on file, billing number, services billed
- **Activities of Daily Living (ADL)**: per-skill current level and goal (10 skills)
- **Safety monitoring**: risk level, elopement risk, medical alerts, emergency protocol

### Class-level
- **Dashboard in sidebar**: all students sorted by IEP expiry urgency (🔴 <30d · 🟡 <90d · 🟢 OK)

---

## 🛠️ Tech Stack

| Component | Technology |
|---|---|
| UI | [Streamlit](https://streamlit.io) |
| LLM (chat + reasoning) | [Ollama](https://ollama.com) · `qwen3:8b` |
| Embeddings (RAG search) | Ollama · `nomic-embed-text` |
| Vector database | [ChromaDB](https://www.trychroma.com) (local, persistent) |
| PDF generation | [ReportLab](https://www.reportlab.com) |
| PDF reading + OCR | pypdf · pymupdf · Tesseract |
| Accommodations dataset | [Hugging Face CC0](https://huggingface.co/datasets/robworks-software/k12-special-education-accommodations) |
| Storage | Local JSON files (no database server required) |
| Language | Python 3.10+ |

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- [Ollama](https://ollama.com/download) installed and running
- (Optional) [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) for scanned PDF imports

### Installation

```bash
# 1. Clone the repo
git clone https://github.com/shashanksnaik07/North_America_AI_Challenge.git
cd North_America_AI_Challenge

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Start Ollama and pull the required models
ollama serve                        # keep this running in a separate terminal
ollama pull qwen3:8b                # ~5 GB chat model
ollama pull nomic-embed-text        # ~274 MB embedding model

# 4. (Optional) Pre-cache AI responses for the sample students
#    Run this once so demo tabs load instantly
python precache_demo.py

# 5. Launch the app
streamlit run app.py
```

Then open **http://localhost:8501** in your browser.

### First steps
1. Click **⚡ Load sample students** in the sidebar to load Jordan Ellis (autism, 9th grade) and Maya Lopez (SLD + ADHD, 4th grade)
2. Explore the **💬 Ask** tab — AI-suggested questions are pre-loaded
3. Try **📝 Summary** — the summary loads instantly from cache
4. Go to **✏️ Update IEP** → describe something you observed → see AI suggestions
5. Click **📄 IEP form** → expand the new **Supplemental** section to try Medicaid/ADL/Safety fields

> ⚠️ **Use fake/test data only. Never enter real student information.**
> The sample students (Jordan Ellis, Maya Lopez) are entirely fictional.

---

## 📁 Project Structure

```
North_America_AI_Challenge/
├── app.py                  # Streamlit UI — all 9 tabs
├── core.py                 # AI + storage logic (LLM calls, RAG, versioning)
├── iep_schema.py           # Alabama ALSDE IEP form as structured JSON
├── export_pdf.py           # ReportLab PDF generation (IEP + PWN + supplemental)
├── prepare_dataset.py      # Downloads CC0 accommodations dataset from Hugging Face
├── precache_demo.py        # Pre-generates AI responses for demo students
├── requirements.txt
├── samples/
│   ├── jordan_ellis.json   # Fictional sample — autism, 9th grade, transition plan
│   └── maya_lopez.json     # Fictional sample — SLD + ADHD, 4th grade
└── data/                   # Created at runtime (git-ignored)
    ├── students/           # Per-student IEP JSON + version history
    ├── chroma/             # ChromaDB vector store for supporting docs
    ├── accommodations.json # Downloaded dataset cache
    └── demo_cache/         # Pre-cached AI responses
```

---

## 🔭 Future Work

### Near-term (next sprint)
- [ ] **Arizona IEP form** — replace Alabama ALSDE template with Arizona's form (in progress, awaiting form from AZ Autism Charter School partner)
- [ ] **Progress monitoring** — log weekly data against benchmarks, flag goals at risk automatically
- [ ] **Multi-user / school server** — shared deployment so case manager and gen-ed teacher see the same IEP
- [ ] **Email integration** — send meeting invitations and PWNs directly from the app (SMTP / Gmail OAuth)

### Medium-term
- [ ] **IEP meeting mode** — real-time AI note-taking during the IEP meeting, auto-populate decisions
- [ ] **State compliance checker** — validate IEP against state regulations before PDF export
- [ ] **Parent portal** — read-only view for parents to review goals and progress
- [ ] **Goal progress graphs** — visual benchmark tracking over time per student

### Longer-term
- [ ] **Districtwide analytics** — anonymised aggregate view for administrators (goal attainment rates by disability category, service gaps)
- [ ] **Multilingual support** — translate parent-facing documents (invitations, PWN, summaries) into Spanish and other languages
- [ ] **Integrations** — connect with Student Information Systems (PowerSchool, Infinite Campus) to pull demographics and schedule data

---

## 👥 Team GoBiByte

Built for the **IBM North America AI Challenge** hackathon.

Special thanks to **Harpreet** and the educators at AZ Autism Charter School for their invaluable feedback and guidance on what teachers actually need.

---

## 🤖 AI Assistance Disclosure

This project was built with AI assistance in the following ways:

| Area | Tool / Model | How it was used |
|---|---|---|
| Development assistance | IBM Bob (AI coding assistant) | Code generation, debugging, and architectural guidance during the hackathon |
| Runtime AI (in the app) | Ollama `qwen3:8b` (local LLM) | Powers all in-app features: IEP import, summaries, Q&A, suggestions, PWN, activities |
| Runtime embeddings | Ollama `nomic-embed-text` | Vector embeddings for RAG over supporting documents |

All AI-generated code was reviewed, understood, and intentionally integrated by the team. The core architectural decisions — structured field-level IEP schema, human-in-the-loop approval flow, local-only LLM for privacy — were made by the team and reflect our understanding of the problem domain. Team members can explain every section of the codebase.

---

## ⚖️ License & Compliance Notes

- All AI runs **locally**. No student data is sent to external APIs.
- Sample student data (Jordan Ellis, Maya Lopez) is **entirely fictional** — for testing only.
- The accommodations dataset is sourced from Hugging Face under **CC0 (public domain)**.
- IEP form structure is based on the **Alabama ALSDE IEP form (Feb. 2019)**.
- Generated documents are marked **DRAFT** and require review by the IEP team before use.
- This tool is a **decision-support aid**, not a replacement for qualified special education professionals.
