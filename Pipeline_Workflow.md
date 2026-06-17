# Play Store Review Pipeline — Orchestration Workflow

How to append new review data and refresh the live dashboard end to end. Designed
to be run as an orchestrated workflow (e.g. in Multica AI): an orchestrator triggers
the deterministic scripts, then the two LLM agents, then publishes.

## Pipeline at a glance

```
 (0) INGEST        drop new crawl CSVs into  Data Raw/
        │
 (1) MERGE          merge_data.py        Data Raw/  ->  data final/*_combined.csv      [deterministic]
        │
 (2) CLASSIFY       classifier.py        data final/ ->  bad_reviews_classified.csv    [deterministic]
        │
 (3) ANALYZE        compute_analysis.py  data+classified -> report/competitive-analysis-<date>.md  [deterministic]
        │
 (4) REPORT         Reporter agent       analysis.md -> report/intel-report-<date>.md  [LLM agent]
        │
 (5) BUILD          build_dashboard.py   data+classified -> index.html + dashboard.html [deterministic]
        │
 (6) PUBLISH        git commit + push    repo -> GitHub Pages redeploys (~1 min)       [needs git auth]
```

Steps 1–3 and 5 are deterministic Python and are bundled in `run_pipeline.sh`.
Step 4 (Reporter) is an LLM agent. Step 6 needs your GitHub credentials.

## How to append new data

1. Crawl fresh reviews for one or more banks.
2. Save each export into `Data Raw/` named `<Stem>_reviews_<label>.csv`, where
   `<Stem>` is one of: `Allo_Bank, Bank_Jago, Blu_by_BCA_Digital, Jenius,
   Neobank_BNC, Sea_Bank, Superbank, Krom_Bank` and `<label>` is any new tag
   (e.g. `Jul26`). Do **not** overwrite older snapshots — keep them; the merge
   de-duplicates across all of them by `review_id`, newest file winning.
3. Run the pipeline (below). New reviews flow through automatically; unchanged
   reviews are de-duplicated away.

## Run it — deterministic core (one command)

```bash
./run_pipeline.sh            # merge -> classify -> analyze -> build
./run_pipeline.sh --publish  # the above, then copy into the repo, commit, push
```

Then run the **Reporter agent** (step 4) on the freshest
`report/competitive-analysis-<date>.md` to produce
`report/intel-report-<date>.md` (see `Reporter_Agent_Instruction.md`). The report
is an analyst deliverable; it is **not** required for the dashboard to update, so it
can run in parallel with or after the build.

## Stage contract

| # | Stage | Type | Command / agent | Input | Output |
|---|-------|------|-----------------|-------|--------|
| 1 | Merge | deterministic | `merge_data.py` | `Data Raw/<Stem>_reviews_*.csv` | `data final/<Stem>_reviews_combined.csv` |
| 2 | Classify | deterministic | `classifier.py` | `data final/*_combined.csv` | `Data Classified/*_classified_combined.csv` |
| 2b | Aggregate | deterministic | `aggregate_classified.py` | `Data Classified/` | `bad_reviews_classified.csv` |
| 3 | Analyze | deterministic | `compute_analysis.py` | combined + classified | `report/competitive-analysis-<date>.md` |
| 4 | Report | LLM agent | Reporter agent | analysis `.md` | `report/intel-report-<date>.md` |
| 5 | Build | deterministic | `build_dashboard.py` | combined + classified | `index.html`, `dashboard.html` |
| 6 | Publish | git | `run_pipeline.sh --publish` | repo working tree | GitHub Pages redeploy |

## Orchestrator rules

- **Order matters:** 1 → 2 → 3 → 5 are a strict chain (each reads the previous
  output). Step 4 depends only on step 3 and can run any time after it.
- **Idempotent:** every deterministic stage fully rebuilds its output from inputs.
  Re-running with no new data reproduces the same files — safe to retry.
- **Full re-classify each run** (not incremental): simpler and guarantees the
  classifier and dashboard never drift. Cost is trivial (rule-based, ~90k rows).
- **Stop on error:** `run_pipeline.sh` uses `set -euo pipefail` — if any stage
  fails, the chain halts before publishing stale output. Fix and re-run.
- **Quality gate (optional):** after step 2, check the Uncategorized rate. If it
  jumps materially above its baseline (~15%), a new complaint pattern has appeared —
  pause and tune `classifier.py` keywords (see `Classifier_Agent_Instruction.md`)
  before publishing.

## Publish & auth notes

- Step 6 pushes to `git@github.com:redisunarta/id-digital-bank-playstore.git`. It
  needs your GitHub SSH key / credentials on the machine running the pipeline; it
  cannot run unattended without them.
- On push, GitHub Pages rebuilds and the public dashboard updates at
  `https://redisunarta.github.io/id-digital-bank-playstore/` within ~1 minute.
- Raw data and reports stay local — `.gitignore` keeps `Data Raw/`, `data final/`,
  `*.csv`, and `report/` out of the public repo. Only code + `index.html` ship.

## Files

```
merge_data.py            stage 1
classifier.py            stage 2
compute_analysis.py      stage 3  (Analyst)
build_dashboard.py       stage 5
run_pipeline.sh          stages 1-3,5 (+ optional publish)
agents/Reporter_Agent_Instruction.md   stage 4
Pipeline_Workflow.md     this file
```
