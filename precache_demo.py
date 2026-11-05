"""
precache_demo.py - pre-generate AI responses for both sample students and
save them as JSON so the demo runs instantly without Ollama wait times.

Run ONCE before your demo:
    python precache_demo.py

The app reads these cache files at startup automatically.
Cache files are stored in data/demo_cache/<sid>_<type>.json
"""

import json
from pathlib import Path

import core
import iep_schema as S

CACHE_DIR = core.DATA_DIR / "demo_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def save(sid: str, key: str, value) -> None:
    (CACHE_DIR / f"{sid}_{key}.json").write_text(json.dumps({"value": value}, indent=2))
    print(f"  ✓ {sid} / {key}")


def load(sid: str, key: str):
    f = CACHE_DIR / f"{sid}_{key}.json"
    return json.loads(f.read_text())["value"] if f.exists() else None


def precache_student(sid: str, name: str) -> None:
    print(f"\n→ Caching {name} ({sid})")

    # 1. Summary
    print("  summary…")
    summary = core.summarize(sid)
    save(sid, "summary", summary)

    # 2. AI-suggested questions
    print("  questions…")
    questions = core.ai_questions(sid)
    save(sid, "ai_questions", questions)

    # 3. PWN
    print("  pwn…")
    pwn = core.generate_pwn(sid)
    save(sid, "pwn", pwn)

    # 4. Activities
    print("  activities…")
    activities = core.generate_activities(sid)
    save(sid, "activities", activities)


if __name__ == "__main__":
    students = core.list_students()
    if not students:
        print("No students found. Run the app and click 'Load sample students' first.")
    else:
        for sid, name in students.items():
            precache_student(sid, name)
        print(f"\n✅ Done. Cached {len(students)} student(s) in {CACHE_DIR}")
        print("   Restart the app — AI responses will load instantly.")
