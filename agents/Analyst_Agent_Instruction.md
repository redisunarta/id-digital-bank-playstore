# Play Store Competitive Intelligence — ANALYST Agent

The Analyst turns the classified review data into a deterministic, numbers-first
analysis file. A separate **Reporter** agent consumes this file to write the memo —
so the section numbering and metric definitions here are a contract the Reporter
depends on. Do not renumber sections or rename metrics without updating the Reporter.

---

## 0. Data contract

### 0.1 Inputs
- `data final/<Bank>_reviews_combined.csv` — full review export. Columns:
  `app_name, app_id, reviewer_name, review_date, review_content, star_rating,
   review_link, reviewer_language, review_title, thumbs_up, app_version, review_id`
- `bad_reviews_classified.csv` — classifier output (1–3★ only). Columns:
  `review_id, bank, review_date, star_rating, category, subcategory, severity,
   subcategories, confidence`
- 7 banks: Allo Bank, Bank Jago, blu by BCA, Jenius, Neobank BNC, SeaBank, Superbank.

### 0.2 Taxonomy (use these exact names — no synonyms)
Parents: Access & Account · Transactions · Funds & Security · Loans & Limits ·
App Performance · Customer Service · General Feedback · Other.
Severity tiers: **Financial harm · Access blocker · Experience · Unknown**.

### 0.3 Metric glossary — every rate states its denominator
- **Total reviews / Avg rating / Star mix** — from combined files, all stars.
- **Negative rate** = (1–3★ reviews ÷ total reviews) × 100. *Denominator: all reviews.*
- **Blocking-failure share** = (bad reviews with severity = `Access blocker` ÷ total
  bad reviews) × 100. Also report the absolute and the % of *all* reviews. *Always
  state which denominator a quoted number uses.*
- **Financial-harm share** = (severity `Financial harm` ÷ total bad reviews) × 100.
- **Category/subcategory share** = (primary-label count ÷ total bad reviews) × 100.
- **Prevalence (mention count)** = number of bad reviews whose multi-label
  `subcategories` field contains that subcategory. Use prevalence — not primary
  count — when describing how widespread a pain is.
- **Version risk** — flag version *v* for bank *b* if `n(v) ≥ 30` **and**
  `avg_rating(v) ≤ trailing-12m avg_rating(b) − 0.5★`. Report the gap in ★.
- **5★ surge (fake-review flag)** — flag month *m* if `5★_count(m) ≥ 3 ×
  trailing-6-month median` **and** the month's avg rating jumps ≥ +0.5★. Directional
  only; never assert manipulation — say "anomalous 5★ surge, cause unverified."
- **Confidence** — carry the classifier's `confidence`, and additionally tag any
  finding `n < 10` as **directional only**; `n ≥ 100` as **robust**.

### 0.4 Revealed vs stated preference (label every unmet-need claim)
- **Revealed** (user tried, it failed/retried): Login & Auth, OTP, Registration &
  KYC, Transfer & Payment, Failed/Pending, Withdraw & Top-up, Crash/Bug,
  Connectivity, Money Missing, Account Blocked, Loan/Paylater rejected.
- **Stated** (opinion / request): Usability/UX, Fees complaints, Credit Limit
  ("want higher limit"), Update preferences, General Dissatisfaction.
- The classifier does **not** detect explicit feature requests as a field. Any
  "unmet need" is therefore *inferred*. Label each as revealed or stated; never
  claim you counted feature requests.

### 0.5 Hard data limits — respect explicitly
- **No developer-reply data exists.** Do not compute "CS reply rate." The available
  measure is **CS-complaint rate** = share of bad reviews in Customer Service.
- Review population is self-selected (unhappy users + loyal advocates).
- Indonesian corpus underrepresents elderly, lower-literacy, and rural users.
- Review data alone is **not** causal.

---

## 1. Role
Compute and show figures from the inputs above; do **not** write prose
recommendations (that is the Reporter's job). Every number must be reproducible from
the named files. If a figure can't be computed from available columns, write
`not computable from current data` — never estimate to fill a slot.

## 2. Method
Compute from the CSVs (code/SQL preferred over eyeballing). Apply the §0.3 formulas
exactly and state the denominator inline with every rate. Round rates to whole %,
ratings to 2 decimals. Where `n` is small, attach the §0.3 confidence tag. Be
deterministic: the same inputs must yield the same figures.

## 3. Output — numbered sections (the Reporter consumes these by number)

**Section 1 — Dataset summary & data sufficiency.** Per bank: total reviews, date
range, # bad reviews, % classified, % Uncategorized. State global gaps up front:
no reply data; sample skew; any bank with thin recent volume.

**Section 2 — Per-app metric table.** One row per bank: avg ★, negative rate,
review volume, top-3 complaint subcategories (with prevalence %), severity mix
(Financial harm / Access blocker / Experience %).

**Section 3 — Blocking-failure analysis.** Per bank: blocking-failure share (state
denominator), the dominant blocking mechanism (subcategory + prevalence), and trend
vs prior period. Rank banks by blocking-failure share. *(Reporter §4 input.)*

**Section 4 — Version risk & anomaly detection.** List flagged versions (§0.3 rule)
with the ★ gap and n. List 5★-surge flags (§0.3) per bank/month. Mark all
directional. If none, write "no version signal" / "no 5★ anomaly."

**Section 5 — Market-gap / category analysis.** Cross-app view: for each parent
category, which banks are worst/best, and which pains are *category-wide* (present
across ≥5 banks) vs *app-specific*. Give total prevalence per category. Label each
gap revealed vs stated (§0.4). *(Reporter §3 input.)*

**Section 6 — Unmet-need signals.** Top inferred unmet needs with prevalence, a
revealed/stated label, and a one-line basis. Explicitly note these are inferred, not
counted feature requests.

**Section 7 — Confidence ledger.** Which findings are robust vs directional; any
bank/period where data is too thin to support a claim.

## 4. Output file
Write to `wiki/research/knowledge/playstore/competitive-analysis-<YYYY-MM-DD>.md`.
This file is the sole input the Reporter reads.
