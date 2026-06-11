# Indonesian Digital Bank — Play Store Review Intelligence

A small pipeline that turns Google Play Store reviews of Indonesia's digital banks
into a competitive-intelligence dashboard and a set of analyst/reporter agents.

It covers seven apps — **Allo Bank, Bank Jago, blu by BCA, Jenius, Neobank BNC,
SeaBank, Superbank** — across ~327k reviews, with ~89k negative (1–3★) reviews
rule-classified into a complaint taxonomy.

> Data files (raw and processed CSVs) are **not** included in this repo — they
> contain reviewer names and are large. See [Data layout](#data-layout).

## Pipeline

```
crawl  →  classify            →  analyze / report        →  visualize
(CSV)     classifier.py           compute_analysis.py        build_dashboard.py
          bad_reviews_*.csv       agents/Analyst + Reporter  dashboard.html
```

1. **Crawl** — Play Store reviews exported per bank (one CSV per app).
2. **Classify** — `classifier.py` applies a deterministic rule/lexicon model to the
   1–3★ reviews, assigning a category, subcategory, severity, and multi-label set.
3. **Analyze & report** — the agent instructions in `agents/` define a Classifier →
   Analyst → Reporter chain that produces a numbers-first analysis and a decision memo.
4. **Visualize** — `build_dashboard.py` aggregates everything into a single
   self-contained `dashboard.html`.

## The dashboard

Open `dashboard.html` in any browser (needs internet for the Chart.js CDN). Three tabs:

- **Competitive Benchmark** — ratings, volume, star distribution, and rating-by-version
  across all banks, with a sortable benchmark matrix.
- **Bad Reviews (1–3★)** — negative-rate by bank and over time, complaint mix
  (category/subcategory, share/count), complaint trend, severity split, and a
  complaint co-occurrence heatmap.
- **Review Examples** — a searchable sample of real review text with filters for
  date, bank, category, subcategory, and any complaint.

Regenerate after re-crawling or re-classifying:

```bash
python build_dashboard.py
```

## Complaint taxonomy

Six parent categories over 1–3★ reviews, each with subcategories, plus a severity tier:

| Parent | Severity lens |
|---|---|
| Access & Account (login, OTP, KYC, blocked) | Access blocker / Financial harm |
| Transactions (transfer, failed/pending, withdraw, card) | Access blocker |
| Funds & Security (money missing, fraud, fees, data/privacy) | Financial harm |
| Loans & Limits (loan/paylater application, credit limit) | Access blocker |
| App Performance (crash/bug, update, connectivity, usability) | Experience |
| Customer Service (support response) | Experience |

Full keyword lexicon and rules are in `agents/Classifier_Agent_Instruction.md`.
Classifier quality vs an LLM zero-shot check is in `docs/validation_report.md`.

## Repository layout

```
build_dashboard.py      aggregates data → dashboard.html
classifier.py           rule/lexicon classifier for 1–3★ reviews
compute_analysis.py     analysis computations
compute_validation.py   classifier-vs-LLM validation
dashboard.html          generated dashboard (self-contained)
agents/                 Classifier, Analyst, and Reporter agent instructions
docs/                   validation report
```

## Data layout

The scripts expect (relative to the repo root, git-ignored):

```
data final/<Bank>_reviews_combined.csv   full export, all stars (tab 1)
bad_reviews_classified.csv               classifier output, 1–3★ (tab 2 & 3)
```

Combined CSV columns: `app_name, app_id, reviewer_name, review_date,
review_content, star_rating, review_link, reviewer_language, review_title,
thumbs_up, app_version, review_id`.

Classified CSV columns: `review_id, bank, review_date, star_rating, category,
subcategory, severity, subcategories, confidence`.

## Notes & caveats

- Reviews are self-selected (skew to unhappy users and loyal advocates) and the
  Indonesian corpus underrepresents elderly, lower-literacy, and rural users.
- The dashboard embeds a sample of public review **text** (no reviewer names).
- Findings are correlational — review data alone is not causal evidence.

## License

MIT — see [LICENSE](LICENSE). Created by Redi Sunarta.
