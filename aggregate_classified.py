#!/usr/bin/env python3
"""
aggregate_classified.py
-----------------------
Concatenate the per-bank classifier outputs in `Data Classified/` into the single
`bad_reviews_classified.csv` that build_dashboard.py and compute_analysis.py read.

Run after classifier.py, before build_dashboard.py / compute_analysis.py.
Idempotent: always rebuilds the aggregate from the per-bank combined files.
"""
import csv, glob, os

csv.field_size_limit(10**7)
HERE = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(HERE, "Data Classified")
OUT = os.path.join(HERE, "bad_reviews_classified.csv")

HEADER = ["review_id", "bank", "review_date", "star_rating", "review_content",
          "category", "subcategory", "severity", "subcategories", "confidence"]


def main():
    files = sorted(glob.glob(os.path.join(SRC_DIR, "*_classified_combined.csv")))
    if not files:
        raise SystemExit(f"No *_classified_combined.csv in {SRC_DIR}")
    total = 0
    with open(OUT, "w", encoding="utf-8", newline="") as out:
        w = csv.DictWriter(out, fieldnames=HEADER, extrasaction="ignore")
        w.writeheader()
        for f in files:
            with open(f, encoding="utf-8-sig", errors="replace", newline="") as fh:
                for row in csv.DictReader((l.replace("\x00", "") for l in fh)):
                    w.writerow({k: row.get(k, "") for k in HEADER})
                    total += 1
    print(f"OK  wrote {OUT}  ·  {total:,} classified rows from {len(files)} banks")


if __name__ == "__main__":
    main()
