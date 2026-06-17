#!/usr/bin/env python3
"""
merge_data.py
-------------
Append + de-duplicate raw Play Store crawl exports into the canonical
`data final/<Bank>_reviews_combined.csv` files that the rest of the pipeline reads.

How "append new data" works:
  1. Drop a new crawl export for a bank into `Data Raw/`, named
     `<Stem>_reviews_<label>.csv` (e.g. `Bank_Jago_reviews_Jul26.csv`).
  2. Run `python merge_data.py`.
  3. All snapshots for each bank are unioned and de-duplicated by `review_id`,
     with the NEWEST file winning on conflicts (so edited reviews update).

Idempotent: re-running with no new files reproduces the same combined files.
"""

import csv, glob, os, sys
from collections import OrderedDict

csv.field_size_limit(10**7)
HERE = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(HERE, "Data Raw")
OUT_DIR = os.path.join(HERE, "data final")

# stem -> (display app_name, app_id if known else "")
BANKS = {
    "Allo_Bank":          ("Allo Bank",          ""),
    "Bank_Jago":          ("Bank Jago",          "com.jago.digitalBanking"),
    "Blu_by_BCA_Digital": ("Blu by BCA Digital", ""),
    "Jenius":             ("Jenius",             ""),
    "Neobank_BNC":        ("Neobank BNC",        ""),
    "Sea_Bank":           ("Sea Bank",           ""),
    "Superbank":          ("Superbank",          ""),
    "Krom_Bank":          ("Krom Bank",          ""),
}

HEADER = ["app_name", "app_id", "reviewer_name", "review_date", "review_content",
          "star_rating", "review_link", "reviewer_language", "review_title",
          "thumbs_up", "app_version", "review_id"]


def read_rows(path):
    with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        cleaned = (line.replace("\x00", "") for line in fh)
        for row in csv.DictReader(cleaned):
            yield row


def snapshot_files(stem):
    """All raw snapshots for a bank, oldest -> newest (newest wins on dedup)."""
    pats = [f"{stem}_reviews_*.csv", f"{stem}_reviews.csv"]
    files = []
    for p in pats:
        for f in glob.glob(os.path.join(RAW_DIR, p)):
            base = os.path.basename(f).lower()
            if "combined" in base or "classified" in base:
                continue
            files.append(f)
    files = sorted(set(files), key=lambda f: os.path.getmtime(f))
    return files


def normalize(row, app_name, app_id):
    out = {k: (row.get(k) or "").strip() for k in HEADER}
    out["app_name"] = row.get("app_name") or app_name
    out["app_id"] = row.get("app_id") or app_id
    return out


def main():
    if not os.path.isdir(RAW_DIR):
        sys.exit(f"Missing folder: {RAW_DIR}")
    os.makedirs(OUT_DIR, exist_ok=True)
    grand_unique = grand_dupes = 0

    for stem, (app_name, app_id) in BANKS.items():
        files = snapshot_files(stem)
        if not files:
            print(f"  {app_name:18s} no raw files, skipped")
            continue
        merged = OrderedDict()
        no_id = []
        seen = dupes = 0
        for f in files:                       # oldest -> newest
            for row in read_rows(f):
                seen += 1
                rid = (row.get("review_id") or "").strip()
                rec = normalize(row, app_name, app_id)
                if rid:
                    if rid in merged:
                        dupes += 1
                    merged[rid] = rec         # newest file overwrites
                else:
                    no_id.append(rec)
        out_path = os.path.join(OUT_DIR, f"{stem}_reviews_combined.csv")
        with open(out_path, "w", encoding="utf-8", newline="") as out:
            w = csv.DictWriter(out, fieldnames=HEADER)
            w.writeheader()
            for rec in merged.values():
                w.writerow(rec)
            for rec in no_id:
                w.writerow(rec)
        unique = len(merged) + len(no_id)
        grand_unique += unique
        grand_dupes += dupes
        print(f"  {app_name:18s} {len(files)} snapshot(s) · {seen:6d} rows -> "
              f"{unique:6d} unique ({dupes} duplicates merged)")
    print(f"\nOK  data final/ rebuilt · {grand_unique:,} unique reviews · "
          f"{grand_dupes:,} duplicates collapsed")


if __name__ == "__main__":
    main()
