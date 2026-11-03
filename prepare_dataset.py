"""
prepare_dataset.py - downloads the accommodations dataset from Hugging Face
ONCE and saves it as data/accommodations.json, so the app works offline after.

Run it yourself:   python prepare_dataset.py
(The app also runs it automatically the first time if the file is missing.)

Dataset: https://huggingface.co/datasets/robworks-software/k12-special-education-accommodations
License: CC0 (public domain). It has NO student data - it's a reference table
of 50 accommodations plus 13 IDEA disability categories.
"""

import json
from pathlib import Path

REPO_ID = "robworks-software/k12-special-education-accommodations"
DATA_DIR = Path(__file__).parent / "data"
RAW_DIR = DATA_DIR / "hf_raw"
OUT_FILE = DATA_DIR / "accommodations.json"


def _read_any(path: Path):
    import pandas as pd
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".jsonl":
        return pd.read_json(path, lines=True)
    if suffix == ".json":
        try:
            return pd.read_json(path)
        except ValueError:
            return pd.read_json(path, lines=True)
    return None


def _clean(value):
    """Turn numpy arrays / numpy types into plain Python so json can save them."""
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, float) and value != value:  # NaN
        return None
    return value


def convert(raw_dir: Path = RAW_DIR, out_file: Path = OUT_FILE) -> int:
    """Read every data file, keep the rows that look like accommodations."""
    import pandas as pd

    frames, disabilities = [], []
    for path in sorted(raw_dir.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        df = _read_any(path)
        if df is None or df.empty:
            continue
        if "applicable_disabilities" in df.columns and "name" in df.columns:
            frames.append(df)
        elif "disabilities" in str(path).lower():
            disabilities.append(df)

    if not frames:
        raise RuntimeError(f"No accommodation table found in {raw_dir}")

    acc = pd.concat(frames, ignore_index=True)
    if "id" in acc.columns:
        acc = acc.drop_duplicates(subset="id")
    records = [{k: _clean(v) for k, v in row.items()} for row in acc.to_dict("records")]

    dis_records = []
    if disabilities:
        dis = pd.concat(disabilities, ignore_index=True)
        dis_records = [{k: _clean(v) for k, v in r.items()} for r in dis.to_dict("records")]

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(
        {"accommodations": records, "disabilities": dis_records}, indent=2, default=str
    ))
    return len(records)


def download_and_convert() -> int:
    from huggingface_hub import snapshot_download
    snapshot_download(repo_id=REPO_ID, repo_type="dataset", local_dir=str(RAW_DIR))
    return convert()


if __name__ == "__main__":
    n = download_and_convert()
    print(f"Saved {n} accommodations to {OUT_FILE}")