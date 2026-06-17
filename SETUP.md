# Setup & Operations

Everything you need to run, refresh, and publish the dashboard. macOS instructions.

## 1. Prerequisites

- **Python 3** (standard library only — no pip installs needed for the pipeline).
- **Node.js** (only if you re-run the crawlers `crawl_reviews.js` / `crawl_krom.js`).
- **Git**.

Folders the scripts expect at the repo root (all git-ignored, not committed):

```
Data Raw/        raw per-bank crawl snapshots:  <Stem>_reviews_<label>.csv
data final/      merged per-bank files:         <Stem>_reviews_combined.csv  (generated)
Data Classified/ classifier output per bank:    <Stem>_classified_combined.csv (generated)
report/          analysis + intel reports (generated)
```

Bank stems: `Allo_Bank, Bank_Jago, Blu_by_BCA_Digital, Jenius, Neobank_BNC,
Sea_Bank, Superbank, Krom_Bank`.

## 2. One-time GitHub auth (so you never re-authenticate)

You already have an SSH key (`~/.ssh/id_ed25519`) registered on GitHub. To make macOS
remember it across reboots and new terminals:

```bash
# add a github block to your SSH config (only if missing)
grep -q "Host github.com" ~/.ssh/config 2>/dev/null || cat >> ~/.ssh/config <<'EOF'
Host github.com
  AddKeysToAgent yes
  UseKeychain yes
  IdentityFile ~/.ssh/id_ed25519
EOF

# store the key + passphrase in the macOS keychain (asked once)
ssh-add --apple-use-keychain ~/.ssh/id_ed25519

# verify
ssh -T git@github.com
```

A successful check prints:
`Hi redisunarta! You've successfully authenticated, but GitHub does not provide shell access.`
That "but..." line is normal — GitHub never gives shell access. After this, `git push`
runs silently.

## 3. Refresh the dashboard with new data

1. Crawl fresh reviews and drop each export into `Data Raw/` named
   `<Stem>_reviews_<label>.csv` (e.g. `Bank_Jago_reviews_Jul26.csv`). Keep the old
   snapshots — the merge de-duplicates across all of them by `review_id`.
2. Run the pipeline:

```bash
./run_pipeline.sh            # merge -> classify -> aggregate -> analyze -> build
./run_pipeline.sh --publish  # the above, then commit + push (Pages redeploys)
```

Stages (see `Pipeline_Workflow.md` for the full contract):

| Step | Script | Output |
|------|--------|--------|
| Merge | `merge_data.py` | `data final/*_combined.csv` |
| Classify | `classifier.py` | `Data Classified/*_classified_combined.csv` |
| Aggregate | `aggregate_classified.py` | `bad_reviews_classified.csv` |
| Analyze | `compute_analysis.py` | `report/competitive-analysis-<date>.md` |
| Build | `build_dashboard.py` | `index.html` + `dashboard.html` |

The Reporter agent (memo) is a separate LLM step on the analysis file — not part of
the shell script. See `agents/Reporter_Agent_Instruction.md`.

## 4. Adding a new bank

1. Add the stem to the `BANKS` dict in `merge_data.py` and `build_dashboard.py`
   (give it a display name + a distinct hex color in `build_dashboard.py`).
2. Add it to `input_files` in `classifier.py` and to `BANKS` / `FILE_MAP` /
   `DISPLAY_NAMES` in `compute_analysis.py`.
3. Add a `BANK_ALIAS` entry in `build_dashboard.py` mapping the classifier's bank
   label to the display name.
4. Drop its raw snapshot into `Data Raw/` and run `./run_pipeline.sh --publish`.

## 5. Publish manually (without the pipeline)

```bash
cd id-digital-bank-playstore
git add index.html dashboard.html
git commit -m "Update dashboard"
git push
```

GitHub Pages redeploys in ~1 minute at
`https://redisunarta.github.io/id-digital-bank-playstore/`.

### Push troubleshooting

- **`! [rejected] ... (fetch first)`** — the remote has commits you don't. Run
  `git pull --rebase origin main` then `git push`. If it says "unrelated histories",
  add `--allow-unrelated-histories` to the pull. If you're sure local is
  authoritative, `git push --force-with-lease`.
- **`Host key verification failed` / auth prompts** — redo section 2.

## 6. Notes

- `node_modules/`, raw/processed CSVs, and `report/` are git-ignored — only code and
  the built `index.html`/`dashboard.html` are committed (the repo is public).
- The dashboard loads Chart.js from a CDN, so viewers need an internet connection.
