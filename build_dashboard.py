#!/usr/bin/env python3
"""
build_dashboard.py
------------------
Builds a single self-contained `dashboard.html` with two tabs:

  Tab 1  Competitive Benchmark  — ratings/volume across banks (all stars)
  Tab 2  Bad Reviews            — 1-3 star complaints by category/severity

Data sources (in this folder):
  - data final/<Bank>_reviews_combined.csv   full review export (tab 1)
  - bad_reviews_classified.csv               classifier output  (tab 2)

Usage:
    python build_dashboard.py

Re-run after re-crawling / re-classifying; it overwrites dashboard.html.
"""

import csv, glob, json, os, sys
from collections import defaultdict, Counter
from datetime import datetime, date, timedelta

csv.field_size_limit(10**7)
HERE = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(HERE, "data final")
CLASSIFIED = os.path.join(HERE, "bad_reviews_classified.csv")
COMBINED_SUFFIX = "_reviews_combined.csv"

# stem -> (display name, color)
BANKS = {
    "Allo_Bank":          ("Allo Bank",   "#EF4444"),
    "Bank_Jago":          ("Bank Jago",   "#F59E0B"),
    "Blu_by_BCA_Digital": ("blu by BCA",  "#0EA5E9"),
    "Jenius":             ("Jenius",      "#14B8A6"),
    "Neobank_BNC":        ("Neobank BNC", "#8B5CF6"),
    "Sea_Bank":           ("SeaBank",     "#22C55E"),
    "Superbank":          ("Superbank",   "#EC4899"),
    "Krom_Bank":          ("Krom Bank",   "#4F46E5"),
}
# classifier file uses slightly different bank spellings -> canonical display
BANK_ALIAS = {
    "Allo Bank": "Allo Bank", "Bank Jago": "Bank Jago",
    "Blu by BCA Digital": "blu by BCA", "blu by BCA": "blu by BCA",
    "Jenius": "Jenius", "Neobank BNC": "Neobank BNC",
    "Sea Bank": "SeaBank", "SeaBank": "SeaBank", "Superbank": "Superbank",
    "Krom Bank": "Krom Bank", "Krom_Bank": "Krom Bank",
}

MAX_VERSIONS = 12
MIN_VER_COUNT = 30
DAILY_DAYS = 210   # days of daily-granularity data to embed (covers 3m/6m windows)

# ---- taxonomy (must mirror the Classifier Agent instruction) ----
PARENTS = ["Access & Account", "Transactions", "Funds & Security", "Loans & Limits",
           "App Performance", "Customer Service", "General Feedback", "Other"]
PARENT_COLORS = {
    "Access & Account": "#2563eb", "Transactions": "#0891b2", "Funds & Security": "#dc2626",
    "Loans & Limits": "#d97706", "App Performance": "#7c3aed", "Customer Service": "#db2777",
    "General Feedback": "#65a30d", "Other": "#9ca3af",
}
# subcategory display order (parent order), incl. the two soft buckets
SUBS_ORDER = [
    "Login & Auth", "OTP / Verification", "Registration & KYC", "Account Blocked/Frozen",
    "Transfer & Payment", "Failed / Pending Transaction", "Withdraw & Top-up", "Card",
    "Money Missing / Balance", "Fraud & Scam", "Fees & Charges", "Data & Privacy",
    "Loan / Paylater Application", "Credit Limit",
    "Crash / Bug / Slow", "Update Issues", "Connectivity / Server", "Usability / UX",
    "Support Response & Resolution",
    "General Dissatisfaction", "Uncategorized",
]
SUB_PARENT = {
    "Login & Auth": "Access & Account", "OTP / Verification": "Access & Account",
    "Registration & KYC": "Access & Account", "Account Blocked/Frozen": "Access & Account",
    "Transfer & Payment": "Transactions", "Failed / Pending Transaction": "Transactions",
    "Withdraw & Top-up": "Transactions", "Card": "Transactions",
    "Money Missing / Balance": "Funds & Security", "Fraud & Scam": "Funds & Security",
    "Fees & Charges": "Funds & Security", "Data & Privacy": "Funds & Security",
    "Loan / Paylater Application": "Loans & Limits", "Credit Limit": "Loans & Limits",
    "Crash / Bug / Slow": "App Performance", "Update Issues": "App Performance",
    "Connectivity / Server": "App Performance", "Usability / UX": "App Performance",
    "Support Response & Resolution": "Customer Service",
    "General Dissatisfaction": "General Feedback", "Uncategorized": "Other",
}
SUB_SEV = {
    "Account Blocked/Frozen": "Financial harm", "Money Missing / Balance": "Financial harm",
    "Fraud & Scam": "Financial harm", "Fees & Charges": "Financial harm",
    "Data & Privacy": "Financial harm",
    "Login & Auth": "Access blocker", "OTP / Verification": "Access blocker",
    "Registration & KYC": "Access blocker", "Transfer & Payment": "Access blocker",
    "Failed / Pending Transaction": "Access blocker", "Withdraw & Top-up": "Access blocker",
    "Card": "Access blocker", "Loan / Paylater Application": "Access blocker",
    "Credit Limit": "Access blocker",
    "Crash / Bug / Slow": "Experience", "Update Issues": "Experience",
    "Connectivity / Server": "Experience", "Usability / UX": "Experience",
    "Support Response & Resolution": "Experience", "General Dissatisfaction": "Experience",
    "Uncategorized": "Unknown",
}
SEV_ORDER = ["Financial harm", "Access blocker", "Experience", "Unknown"]
SEV_COLORS = {"Financial harm": "#dc2626", "Access blocker": "#f59e0b",
              "Experience": "#3b82f6", "Unknown": "#9ca3af"}
CONCRETE_SUBS = [s for s in SUBS_ORDER if s not in ("General Dissatisfaction", "Uncategorized")]


def read_rows(path):
    with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        cleaned = (line.replace("\x00", "") for line in fh)
        for row in csv.DictReader(cleaned):
            yield row


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except Exception:
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
        except Exception:
            return None


# ---------------------------------------------------------------------------
def build_tab1():
    banks_out, bank_meta, monthly, versions, daily = [], {}, {}, {}, {}
    for stem, (name, color) in BANKS.items():
        path = os.path.join(RAW_DIR, stem + COMBINED_SUFFIX)
        if not os.path.exists(path):
            print(f"WARN missing {path}", file=sys.stderr)
            continue
        banks_out.append(name)
        total = 0
        star_counts = [0, 0, 0, 0, 0]
        thumbs_total = 0
        first_d = last_d = None
        m_agg = defaultdict(lambda: {"n": 0, "sum": 0, "stars": [0, 0, 0, 0, 0]})
        d_agg = defaultdict(lambda: {"n": 0, "sum": 0, "stars": [0, 0, 0, 0, 0]})
        v_agg = defaultdict(lambda: {"n": 0, "sum": 0})
        for row in read_rows(path):
            try:
                rating = int(float(row.get("star_rating") or 0))
            except Exception:
                rating = 0
            if rating < 1 or rating > 5:
                continue
            d = parse_date(row.get("review_date"))
            if d is None:
                continue
            total += 1
            star_counts[rating - 1] += 1
            try:
                tu = int(float(row.get("thumbs_up") or 0))
            except Exception:
                tu = 0
            thumbs_total += tu
            first_d = d if first_d is None or d < first_d else first_d
            last_d = d if last_d is None or d > last_d else last_d
            mkey = f"{d.year:04d}-{d.month:02d}"
            ma = m_agg[mkey]
            ma["n"] += 1
            ma["sum"] += rating
            ma["stars"][rating - 1] += 1
            da = d_agg[d.isoformat()]
            da["n"] += 1
            da["sum"] += rating
            da["stars"][rating - 1] += 1
            ver = (row.get("app_version") or "").strip()
            if ver:
                va = v_agg[ver]
                va["n"] += 1
                va["sum"] += rating
        avg = round(sum((i + 1) * c for i, c in enumerate(star_counts)) / total, 3) if total else 0
        bank_meta[name] = {"color": color, "total": total, "avg": avg, "stars": star_counts,
                           "thumbs": thumbs_total,
                           "first": first_d.isoformat() if first_d else None,
                           "last": last_d.isoformat() if last_d else None}
        monthly[name] = [{"m": k, "n": v["n"], "avg": round(v["sum"] / v["n"], 3), "stars": v["stars"]}
                         for k, v in sorted(m_agg.items())]
        vlist = [{"v": k, "n": v["n"], "avg": round(v["sum"] / v["n"], 3)}
                 for k, v in v_agg.items() if v["n"] >= MIN_VER_COUNT]
        vlist.sort(key=lambda x: x["n"], reverse=True)
        versions[name] = vlist[:MAX_VERSIONS]
        cut = (last_d - timedelta(days=DAILY_DAYS)).isoformat() if last_d else "9999"
        daily[name] = [{"d": k, "n": v["n"], "avg": round(v["sum"] / v["n"], 3), "stars": v["stars"]}
                       for k, v in sorted(d_agg.items()) if k >= cut]
    return banks_out, bank_meta, monthly, versions, daily


def build_tab2():
    sub_idx = {s: i for i, s in enumerate(CONCRETE_SUBS)}
    bad_monthly = defaultdict(lambda: defaultdict(Counter))   # bank -> month -> sub -> n
    bad_daily = defaultdict(lambda: defaultdict(Counter))     # bank -> date -> sub -> n
    cooc = defaultdict(Counter)                               # bank -> "i,j" -> n
    total = 0
    skipped = Counter()
    if not os.path.exists(CLASSIFIED):
        print(f"WARN missing {CLASSIFIED}", file=sys.stderr)
        return {"total": 0, "monthly": {}, "cooc": {}}
    for r in read_rows(CLASSIFIED):
        bank = BANK_ALIAS.get((r.get("bank") or "").strip())
        if bank is None:
            skipped[(r.get("bank") or "").strip()] += 1
            continue
        d = parse_date(r.get("review_date"))
        if d is None:
            continue
        mkey = f"{d.year:04d}-{d.month:02d}"
        sub = (r.get("subcategory") or "").strip() or "Uncategorized"
        if sub not in SUB_PARENT:
            sub = "Uncategorized"
        bad_monthly[bank][mkey][sub] += 1
        bad_daily[bank][d.isoformat()][sub] += 1
        total += 1
        sc = (r.get("subcategories") or "").strip()
        items = [p.strip() for p in sc.split("|") if p.strip()] if sc else []
        items = sorted({s for s in items if s in sub_idx}, key=lambda s: sub_idx[s])
        for a in range(len(items)):
            i = sub_idx[items[a]]
            cooc[bank][f"{i},{i}"] += 1
            for b in range(a + 1, len(items)):
                cooc[bank][f"{i},{sub_idx[items[b]]}"] += 1
    if skipped:
        print("WARN unmapped bank labels:", dict(skipped), file=sys.stderr)
    return {
        "total": total,
        "parents": PARENTS,
        "parent_colors": PARENT_COLORS,
        "subs_order": SUBS_ORDER,
        "concrete_subs": CONCRETE_SUBS,
        "sub_parent": SUB_PARENT,
        "sub_sev": SUB_SEV,
        "sev_order": SEV_ORDER,
        "sev_colors": SEV_COLORS,
        "monthly": {b: {m: dict(c) for m, c in mm.items()} for b, mm in bad_monthly.items()},
        "daily": {b: {k: dict(v) for k, v in days.items()
                      if k >= (date.fromisoformat(max(days)) - timedelta(days=DAILY_DAYS)).isoformat()}
                  for b, days in bad_daily.items() if days},
        "cooc": {b: dict(c) for b, c in cooc.items()},
    }


EX_RECENT = 45     # most-recent kept per bank x subcategory
EX_THUMBS = 8      # extra top-thumbs kept per group
EX_CAP = 50        # hard cap per group


def build_examples():
    """Join classifier labels to combined review text; keep a capped sample
    per (bank, subcategory) of the most-recent plus most-helpful reviews."""
    if not os.path.exists(CLASSIFIED):
        return []
    meta = {}
    for r in read_rows(CLASSIFIED):
        bank = BANK_ALIAS.get((r.get("bank") or "").strip())
        if not bank:
            continue
        sub = (r.get("subcategory") or "").strip() or "Uncategorized"
        meta[r["review_id"]] = {
            "bank": bank, "date": (r.get("review_date") or "")[:10],
            "cat": r.get("category") or "Other", "sub": sub,
            "subs": [p.strip() for p in (r.get("subcategories") or "").split("|") if p.strip()],
        }
    recs = []
    for stem in BANKS:
        path = os.path.join(RAW_DIR, stem + COMBINED_SUFFIX)
        if not os.path.exists(path):
            continue
        for r in read_rows(path):
            rid = r.get("review_id")
            m = meta.get(rid)
            if not m:
                continue
            try:
                star = int(float(r.get("star_rating") or 0))
            except Exception:
                star = 0
            try:
                th = int(float(r.get("thumbs_up") or 0))
            except Exception:
                th = 0
            content = (r.get("review_content") or "").strip().replace("\n", " ").replace("\r", " ")
            if len(content) > 400:
                content = content[:397] + "..."
            recs.append({**m, "star": star, "thumbs": th, "content": content})
    groups = defaultdict(list)
    for rec in recs:
        groups[(rec["bank"], rec["sub"])].append(rec)
    sample = []
    for lst in groups.values():
        lst.sort(key=lambda x: x["date"], reverse=True)
        keep = lst[:EX_RECENT]
        seen = {id(x) for x in keep}
        for x in sorted(lst, key=lambda x: x["thumbs"], reverse=True)[:EX_THUMBS]:
            if id(x) not in seen and len(keep) < EX_CAP:
                keep.append(x)
        sample.extend(keep[:EX_CAP])
    sample.sort(key=lambda x: x["date"], reverse=True)
    return [{"b": r["bank"], "d": r["date"], "s": r["star"], "c": r["cat"],
             "sc": r["sub"], "m": r["subs"], "t": r["content"], "th": r["thumbs"]}
            for r in sample]


def build():
    banks_out, bank_meta, monthly, versions, daily = build_tab1()
    if not banks_out:
        sys.exit("No combined review files found in 'data final/'.")
    bad = build_tab2()
    examples = build_examples()
    data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "banks": banks_out,
        "bank_meta": bank_meta,
        "monthly": monthly,
        "daily": daily,
        "versions": versions,
        "bad": bad,
        "examples": examples,
    }
    html = HTML_TEMPLATE.replace("/*__DATA__*/", json.dumps(data, ensure_ascii=False))
    out = os.path.join(HERE, "dashboard.html")
    for name in ("dashboard.html", "index.html"):
        with open(os.path.join(HERE, name), "w", encoding="utf-8") as fh:
            fh.write(html)
    grand = sum(m["total"] for m in bank_meta.values())
    print(f"OK  wrote {out}")
    print(f"    {len(banks_out)} banks · {grand:,} reviews · {bad['total']:,} classified bad reviews"
          f" · {len(examples):,} example reviews · generated {data['generated_at']}")


# ---------------------------------------------------------------------------
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Digital Bank Reviews — Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root{--bg:#faf8f3;--card:#fffdfa;--ink:#3c372e;--muted:#8c8475;--line:#e7e0d3;
    --accent:#b45309;--good:#3b6d11;--bad:#a32d2d;
    --serif:Georgia,'Iowan Old Style','Times New Roman',serif;--shadow:none;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font-size:14px;line-height:1.45;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
  header{background:var(--card);border-bottom:1px solid var(--line);padding:16px 24px 0;}
  .htop{display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:12px;}
  header h1{margin:0;font-size:22px;font-weight:500;font-family:var(--serif);}
  header .sub{color:var(--muted);font-size:12.5px;margin-top:3px;}
  .tabnav{display:flex;gap:4px;margin-top:14px;}
  .tabnav button{border:0;background:transparent;padding:10px 16px;cursor:pointer;font:inherit;
    color:var(--muted);border-bottom:2px solid transparent;font-weight:500;}
  .tabnav button.active{color:var(--accent);border-bottom-color:var(--accent);}
  .wrap{max-width:1280px;margin:0 auto;padding:20px 24px 60px;}
  .controls{display:flex;gap:14px;flex-wrap:wrap;align-items:center;background:var(--card);
    border:1px solid var(--line);border-radius:4px;padding:12px 16px;margin-bottom:22px;}
  .controls label{font-size:12px;color:var(--muted);margin-right:6px;}
  select{font:inherit;padding:6px 10px;border:1px solid var(--line);border-radius:4px;background:var(--card);color:var(--ink);}
  .seg{display:inline-flex;border:1px solid var(--line);border-radius:4px;overflow:hidden;}
  .seg button{border:0;background:var(--card);padding:6px 12px;cursor:pointer;font:inherit;color:var(--muted);}
  .seg button.active{background:var(--accent);color:#fff;}
  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin-bottom:20px;}
  .kpi{background:var(--card);border:1px solid var(--line);border-radius:4px;padding:14px 16px;}
  .kpi .l{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;} .kpi .v{font-size:26px;font-weight:500;margin-top:5px;font-family:var(--serif);}
  .kpi .d{font-size:12px;margin-top:2px;}
  .card{background:var(--card);border:1px solid var(--line);border-radius:4px;padding:18px 20px;margin-bottom:22px;}
  .card h2{margin:0 0 3px;font-size:17px;font-weight:500;font-family:var(--serif);} .card .hint{color:var(--muted);font-size:12px;margin-bottom:14px;}
  .card .tools{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px;}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:20px;}
  @media(max-width:900px){.grid2{grid-template-columns:1fr;}}
  table{width:100%;border-collapse:collapse;font-size:13px;}
  th,td{padding:8px 10px;text-align:left;border-bottom:1px solid var(--line);vertical-align:middle;}
  th{font-size:11.5px;text-transform:uppercase;letter-spacing:.03em;color:var(--muted);cursor:pointer;user-select:none;white-space:nowrap;}
  th.sorted::after{content:" \25BC";font-size:9px;} th.sorted.asc::after{content:" \25B2";}
  td.num,th.num{text-align:right;}
  .dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px;vertical-align:middle;}
  .bankname{font-weight:500;white-space:nowrap;}
  .stk{display:inline-flex;height:9px;width:120px;border-radius:5px;overflow:hidden;vertical-align:middle;background:#eee;}
  .stk i{height:100%;}
  .delta-up{color:var(--good);} .delta-dn{color:var(--bad);}
  canvas{max-width:100%;}
  .chartbox{position:relative;height:300px;} .chartbox.sm{height:240px;} .chartbox.tall{height:340px;}
  .foot{color:var(--muted);font-size:11.5px;text-align:center;margin-top:30px;}
  [hidden]{display:none!important;}
  /* heatmap */
  .heat{border-collapse:collapse;font-size:11px;}
  .heat td,.heat th{border:1px solid #eef1f5;padding:4px 6px;text-align:center;}
  .heat th.rowh{text-align:right;white-space:nowrap;color:var(--ink);font-weight:500;text-transform:none;letter-spacing:0;cursor:default;}
  .heat th.colh{height:120px;white-space:nowrap;color:var(--ink);font-weight:500;text-transform:none;letter-spacing:0;cursor:default;}
  .heat th.colh div{transform:rotate(-90deg);width:18px;}
  .heat td.diag{background:#f3ece0;font-weight:500;}
  .heatwrap{overflow-x:auto;}
  .exl{font-size:11px;color:var(--muted);margin-right:4px;}
  #exTable td{vertical-align:top;}
  #exTable .ex-text{max-width:460px;font-size:12.5px;}
  .chip{display:inline-block;background:#f3ece0;color:#7c5320;border-radius:4px;padding:1px 7px;font-size:10.5px;margin:1px 2px 1px 0;white-space:nowrap;}
  .stars{color:#c2683f;letter-spacing:1px;white-space:nowrap;}
  .catpill{display:inline-block;border-radius:6px;padding:1px 7px;font-size:11px;color:#fff;white-space:nowrap;}
</style>
</head>
<body>
<header>
  <div class="htop">
    <div><h1>Digital Bank Reviews — Dashboard</h1>
      <div class="sub" id="subtitle">Google Play Store · Indonesia</div></div>
    <div class="sub" id="genstamp"></div>
  </div>
  <div class="tabnav">
    <button data-tab="1" class="active">Competitive Benchmark</button>
    <button data-tab="2">Bad Reviews (1–3★)</button>
    <button data-tab="3">Review Examples</button>
  </div>
</header>

<div class="wrap">

  <div class="controls" id="controls">
    <div><label>Window</label>
      <span class="seg" id="winSeg">
        <button data-w="3">3m</button><button data-w="6">6m</button>
        <button data-w="12">12m</button><button data-w="24" class="active">24m</button>
        <button data-w="0">All</button>
      </span></div>
    <div><label>Granularity</label>
      <span class="seg" id="granSeg">
        <button data-g="day">Daily</button><button data-g="month" class="active">Monthly</button>
        <button data-g="quarter">Quarterly</button>
      </span></div>
    <div style="margin-left:auto"><label>Banks</label><span id="bankToggles"></span></div>
  </div>

  <!-- ============ TAB 1 ============ -->
  <div id="tab1" class="tabpanel">
    <div class="kpis" id="kpis"></div>

    <div class="card">
      <h2>Benchmark matrix</h2>
      <div class="hint">Per bank over the selected window. Click any column header to sort.</div>
      <table id="matrix"><thead><tr>
        <th data-k="bank">Bank</th><th data-k="avg" class="num">Avg ★</th>
        <th data-k="total" class="num">Reviews</th><th data-k="pos" class="num">% 4–5★</th>
        <th data-k="neg" class="num">% 1–2★</th><th data-k="delta" class="num">Δ rating</th>
        <th data-k="stars">Star mix</th><th data-k="spark">Trend</th>
      </tr></thead><tbody></tbody></table>
    </div>

    <div class="grid2">
      <div class="card"><h2>Average rating over time</h2>
        <div class="hint">Weighted average per bank.</div>
        <div class="chartbox"><canvas id="ratingLine"></canvas></div></div>
      <div class="card"><h2>Review volume over time</h2>
        <div class="hint">Reviews per period for the selected bank.</div>
        <select id="volBank" style="margin-bottom:10px"></select>
        <div class="chartbox"><canvas id="volumeLine"></canvas></div></div>
    </div>

    <div class="grid2">
      <div class="card"><h2>Star distribution</h2>
        <div class="hint">Share of 1–5★ within the window.</div>
        <div class="chartbox"><canvas id="starDist"></canvas></div></div>
      <div class="card"><h2>Rating by app version</h2>
        <div class="hint">Spot bad releases. Top versions by volume.</div>
        <select id="verBank" style="margin-bottom:10px"></select>
        <div class="chartbox sm"><canvas id="verChart"></canvas></div></div>
    </div>
  </div>

  <!-- ============ TAB 2 ============ -->
  <div id="tab2" class="tabpanel" hidden>
    <div class="kpis" id="badKpis"></div>

    <div class="grid2">
      <div class="card"><h2>Negative review rate by bank</h2>
        <div class="hint">1–3★ reviews as % of that bank's total reviews (window).</div>
        <div class="chartbox"><canvas id="negRateBar"></canvas></div></div>
      <div class="card"><h2>Negative rate over time</h2>
        <div class="hint">Share of reviews that are 1–3★, per period.</div>
        <div class="chartbox"><canvas id="negRateLine"></canvas></div></div>
    </div>

    <div class="card">
      <h2>Complaint mix by bank</h2>
      <div class="hint">What 1–3★ reviewers complain about. Includes Uncategorized & General.</div>
      <div class="tools">
        <span class="seg" id="mixLevel"><button data-l="parent" class="active">Category</button>
          <button data-l="sub">Subcategory</button></span>
        <span class="seg" id="mixValue"><button data-v="share" class="active">Share %</button>
          <button data-v="count">Count</button></span>
      </div>
      <div class="chartbox tall"><canvas id="mixChart"></canvas></div>
    </div>

    <div class="grid2">
      <div class="card"><h2>Complaint trend over time</h2>
        <div class="hint">Bad reviews per category per period.</div>
        <select id="trendBank" style="margin-bottom:10px"></select>
        <div class="chartbox"><canvas id="trendChart"></canvas></div></div>
      <div class="card"><h2>Severity split by bank</h2>
        <div class="hint">Share of complaints by severity tier.</div>
        <div class="chartbox"><canvas id="sevChart"></canvas></div></div>
    </div>

    <div class="card">
      <h2>Complaint co-occurrence</h2>
      <div class="hint">How often two complaint types appear in the same review (all-time). Diagonal = total mentions. Top 12 by volume.</div>
      <select id="coocBank" style="margin-bottom:10px"></select>
      <div class="heatwrap" id="coocWrap"></div>
    </div>
  </div>

  <!-- ============ TAB 3 ============ -->
  <div id="tab3" class="tabpanel" hidden>
    <div class="card">
      <h2>Review examples</h2>
      <div class="hint">A sample of actual 1–3★ review text (up to ~50 most-recent/most-helpful per bank × subcategory). Filter and search below.</div>
      <div class="tools">
        <span><label class="exl">From</label><input id="exFrom" type="date"></span>
        <span><label class="exl">To</label><input id="exTo" type="date"></span>
        <select id="exBank"></select>
        <select id="exStar"><option value="">All ★</option><option value="1">1★</option><option value="2">2★</option><option value="3">3★</option></select>
        <select id="exCat"></select>
        <select id="exSub"></select>
        <select id="exAny"></select>
        <span class="seg" id="exSort"><button data-s="recent" class="active">Recent</button><button data-s="thumbs">Helpful</button></span>
      </div>
      <div class="tools">
        <input id="exSearch" type="search" placeholder="Search review text…" style="flex:1;min-width:220px;padding:6px 10px;border:1px solid var(--line);border-radius:8px">
        <button id="exReset" style="border:1px solid var(--line);background:#fff;border-radius:8px;padding:6px 12px;cursor:pointer;font:inherit;color:var(--muted)">Reset</button>
      </div>
      <table id="exTable"><thead><tr>
        <th data-k="d">Date</th><th data-k="b">Bank</th><th data-k="s" class="num">★</th>
        <th data-k="c">Category</th><th data-k="sc">Subcategory</th>
        <th>Complaints</th><th>Review</th><th data-k="th" class="num">👍</th>
      </tr></thead><tbody></tbody></table>
      <div class="hint" id="exCount" style="margin-top:10px"></div>
    </div>
  </div>

  <div class="foot" id="foot"></div>
</div>

<script>
const DATA = /*__DATA__*/;
const BM = DATA.bank_meta, BANKS = DATA.banks, BAD = DATA.bad;
const COLORS = Object.fromEntries(BANKS.map(b=>[b, BM[b].color]));
const SUBPAL=['#3b82f6','#60a5fa','#1d4ed8','#93c5fd','#06b6d4','#22d3ee','#0e7490','#67e8f9',
  '#ef4444','#f87171','#b91c1c','#fca5a5','#d97706','#fbbf24','#7c3aed','#a78bfa','#5b21b6','#c4b5fd',
  '#db2777','#65a30d','#9ca3af'];
const SUBCOLOR=Object.fromEntries(BAD.subs_order.map((s,i)=>[s,SUBPAL[i%SUBPAL.length]]));
let state={win:24,gran:'month',tab:'1',active:new Set(BANKS),matrixSort:{k:'avg',asc:false},
  mixLevel:'parent',mixValue:'share'};

/* ---------- shared helpers ---------- */
function latestMonth(){let l='0000-00';BANKS.forEach(b=>DATA.monthly[b].forEach(m=>{if(m.m>l)l=m.m;}));return l;}
function monthsBack(n){if(n===0)return'0000-00';let[y,mo]=latestMonth().split('-').map(Number);
  mo-=(n-1);while(mo<=0){mo+=12;y-=1;}return `${String(y).padStart(4,'0')}-${String(mo).padStart(2,'0')}`;}
function inWindow(m){return m>=state._cut;}
function periodKey(m){if(state.gran==='month'||state.gran==='day')return m;let[y,mo]=m.split('-').map(Number);return `${y}-Q${Math.floor((mo-1)/3)+1}`;}
function shown(){return BANKS.filter(b=>state.active.has(b));}
function srcRows(bank){return state.gran==='day'?((DATA.daily&&DATA.daily[bank])||[]).map(r=>({m:r.d,n:r.n,avg:r.avg,stars:r.stars})):DATA.monthly[bank];}
function badSrc(bank){return state.gran==='day'?((BAD.daily&&BAD.daily[bank])||{}):(BAD.monthly[bank]||{});}
function setGran(g){state.gran=g;document.querySelectorAll('#granSeg button').forEach(x=>x.classList.toggle('active',x.dataset.g===g));}
function toRGBA(c,a){
  if(Array.isArray(c))return c.map(x=>toRGBA(x,a));
  if(typeof c!=='string')return c;
  if(c.startsWith('rgb')){const n=c.match(/[\d.]+/g);return `rgba(${n[0]},${n[1]},${n[2]},${a})`;}
  let h=c.replace('#','');if(h.length===8)h=h.slice(0,6);if(h.length===3)h=h.split('').map(x=>x+x).join('');
  return `rgba(${parseInt(h.slice(0,2),16)},${parseInt(h.slice(2,4),16)},${parseInt(h.slice(4,6),16)},${a})`;}
const LH={
  onHover:(e,item,legend)=>{const ch=legend.chart,isLine=ch.config.type==='line';
    ch.data.datasets.forEach((ds,i)=>{if(!ds._cap){ds._cap=1;ds._ob=ds.borderColor;ds._og=ds.backgroundColor;ds._ow=ds.borderWidth;}
      const dim=i!==item.datasetIndex;
      ds.borderColor=dim?toRGBA(ds._ob,0.12):ds._ob;
      ds.backgroundColor=dim?toRGBA(ds._og,0.12):ds._og;
      if(isLine)ds.borderWidth=dim?ds._ow:Math.max(ds._ow||2,3);});
    ch.update('none');},
  onLeave:(e,item,legend)=>{const ch=legend.chart;
    ch.data.datasets.forEach(ds=>{if(ds._cap){ds.borderColor=ds._ob;ds.backgroundColor=ds._og;ds.borderWidth=ds._ow;}});
    ch.update('none');}};
function baseOpts(scales,indexAxis){return{responsive:true,maintainAspectRatio:false,indexAxis:indexAxis||'x',
  interaction:{mode:'index',intersect:false},
  plugins:{legend:{position:'bottom',labels:{boxWidth:10,font:{size:10}},onHover:LH.onHover,onLeave:LH.onLeave}},
  scales:Object.assign({x:{grid:{display:false},ticks:{font:{size:10},maxRotation:0,autoSkip:true,maxTicksLimit:12,
      callback:function(v){const l=this.getLabelForValue(v);return(state.gran==='day'&&typeof l==='string'&&l.length>=10)?l.slice(5):l;}}},
    y:{grid:{color:'#eef1f5'},ticks:{font:{size:10}}}},scales)};}

/* ====================== TAB 1 ====================== */
function agg(bank){
  const rows=srcRows(bank).filter(m=>inWindow(m.m));
  let n=0,sumw=0,stars=[0,0,0,0,0];const pmap={};
  rows.forEach(m=>{n+=m.n;sumw+=m.avg*m.n;m.stars.forEach((c,i)=>stars[i]+=c);
    const p=periodKey(m.m);if(!pmap[p])pmap[p]={p,n:0,sumw:0};pmap[p].n+=m.n;pmap[p].sumw+=m.avg*m.n;});
  const series=Object.values(pmap).sort((a,b)=>a.p<b.p?-1:1).map(o=>({p:o.p,n:o.n,avg:o.n?o.sumw/o.n:null}));
  return{n,avg:n?sumw/n:0,stars,series};
}
function allPeriods(){const s=new Set();BANKS.forEach(b=>srcRows(b).forEach(m=>{if(inWindow(m.m))s.add(periodKey(m.m));}));return[...s].sort();}
function deltaOf(a){const s=a.series.filter(x=>x.avg!=null);if(s.length<2)return 0;const h=Math.floor(s.length/2);return avgOf(s.slice(h))-avgOf(s.slice(0,h));}
function avgOf(arr){let n=0,sw=0;arr.forEach(x=>{n+=x.n;sw+=x.avg*x.n;});return n?sw/n:0;}
function signed(x){return(x>=0?'+':'')+x.toFixed(2);}

function renderKPIs(){
  const A={};BANKS.forEach(b=>A[b]=agg(b));const sh=shown();
  let tot=0,sumw=0;sh.forEach(b=>{tot+=A[b].n;sumw+=A[b].avg*A[b].n;});
  const overall=tot?sumw/tot:0;
  const r=sh.filter(b=>A[b].n>0).sort((a,b)=>A[b].avg-A[a].avg);
  const best=r[0],worst=r[r.length-1];
  let mover=null,md=0;sh.forEach(b=>{const d=deltaOf(A[b]);if(Math.abs(d)>Math.abs(md)){md=d;mover=b;}});
  const k=[['Total reviews',tot.toLocaleString(),''],['Overall avg ★',overall.toFixed(2),''],
    ['Top rated',best?`${best} · ${A[best].avg.toFixed(2)}★`:'—',''],
    ['Lowest rated',worst?`${worst} · ${A[worst].avg.toFixed(2)}★`:'—',''],
    ['Biggest mover',mover||'—',mover?signed(md)+' ★':'']];
  document.getElementById('kpis').innerHTML=k.map(([l,v,d])=>
    `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div>
     <div class="d ${d.startsWith('+')?'delta-up':d.startsWith('-')?'delta-dn':''}">${d}</div></div>`).join('');
}
function renderMatrix(){
  const A={};BANKS.forEach(b=>A[b]=agg(b));
  let rows=shown().map(b=>{const a=A[b],t=a.n||1;
    return{bank:b,avg:a.avg,total:a.n,pos:(a.stars[3]+a.stars[4])/t*100,neg:(a.stars[0]+a.stars[1])/t*100,
      delta:deltaOf(a),stars:a.stars,series:a.series};});
  const{k,asc}=state.matrixSort;
  rows.sort((x,y)=>{if(k==='bank')return asc?x.bank.localeCompare(y.bank):y.bank.localeCompare(x.bank);
    let xv=x[k],yv=y[k];if(k==='stars'||k==='spark'){xv=x.avg;yv=y.avg;}return asc?xv-yv:yv-xv;});
  const tb=document.querySelector('#matrix tbody');
  tb.innerHTML=rows.map(r=>{const t=r.total||1;
    const seg=r.stars.map((c,i)=>`<i style="width:${c/t*100}%;background:${['#dc2626','#f97316','#eab308','#84cc16','#16a34a'][i]}"></i>`).join('');
    const dc=r.delta>0.001?'delta-up':r.delta<-0.001?'delta-dn':'';
    return `<tr><td class="bankname"><span class="dot" style="background:${COLORS[r.bank]}"></span>${r.bank}</td>
      <td class="num"><b>${r.avg.toFixed(2)}</b></td><td class="num">${r.total.toLocaleString()}</td>
      <td class="num">${r.pos.toFixed(0)}%</td><td class="num">${r.neg.toFixed(0)}%</td>
      <td class="num ${dc}">${signed(r.delta)}</td><td><span class="stk">${seg}</span></td>
      <td><canvas width="120" height="30" data-bank="${r.bank}"></canvas></td></tr>`;}).join('');
  rows.forEach(r=>drawSpark(tb.querySelector(`canvas[data-bank="${CSS.escape(r.bank)}"]`),r.series.map(s=>s.avg),COLORS[r.bank]));
  document.querySelectorAll('#matrix th').forEach(th=>{th.classList.toggle('sorted',th.dataset.k===k);th.classList.toggle('asc',th.dataset.k===k&&asc);});
}
function drawSpark(cv,vals,col){if(!cv)return;const ctx=cv.getContext('2d'),w=cv.width,h=cv.height;ctx.clearRect(0,0,w,h);
  const v=vals.filter(x=>x!=null);if(v.length<2)return;const mn=Math.min(...v),mx=Math.max(...v),rg=(mx-mn)||1;
  ctx.beginPath();v.forEach((y,i)=>{const px=i/(v.length-1)*(w-4)+2,py=h-2-((y-mn)/rg)*(h-6);i?ctx.lineTo(px,py):ctx.moveTo(px,py);});
  ctx.strokeStyle=col;ctx.lineWidth=1.6;ctx.stroke();}

let ratingChart,volumeChart,starChart,verChart;
function renderTab1Charts(){
  const periods=allPeriods(),sh=shown(),A={};sh.forEach(b=>A[b]=agg(b));
  const rds=sh.map(b=>{const m=Object.fromEntries(A[b].series.map(s=>[s.p,s.avg]));
    return{label:b,data:periods.map(p=>m[p]??null),borderColor:COLORS[b],backgroundColor:COLORS[b],tension:.3,spanGaps:true,pointRadius:0,borderWidth:2};});
  ratingChart&&ratingChart.destroy();
  ratingChart=new Chart(ratingLine,{type:'line',data:{labels:periods,datasets:rds},options:baseOpts({y:{min:1,max:5,ticks:{stepSize:1}}})});
  const labels=['1★','2★','3★','4★','5★'],cols=['#dc2626','#f97316','#eab308','#84cc16','#16a34a'];
  const sds=labels.map((lab,i)=>({label:lab,backgroundColor:cols[i],data:sh.map(b=>{const t=A[b].n||1;return A[b].stars[i]/t*100;})}));
  starChart&&starChart.destroy();
  starChart=new Chart(starDist,{type:'bar',data:{labels:sh,datasets:sds},options:baseOpts({x:{stacked:true,max:100,ticks:{callback:v=>v+'%'}},y:{stacked:true}},'y')});
  renderVolChart();renderVerChart();
}
function renderVolChart(){const b=volBank.value,periods=allPeriods(),m=Object.fromEntries(agg(b).series.map(s=>[s.p,s.n]));
  volumeChart&&volumeChart.destroy();
  volumeChart=new Chart(volumeLine,{type:'line',data:{labels:periods,datasets:[{label:b+' — reviews',data:periods.map(p=>m[p]??0),borderColor:COLORS[b],backgroundColor:COLORS[b]+'22',tension:.3,fill:true,pointRadius:0,borderWidth:2}]},options:Object.assign(baseOpts({y:{beginAtZero:true}}),{plugins:{legend:{display:false}}})});}
function renderVerChart(){const b=verBank.value,vs=(DATA.versions[b]||[]).slice().sort((a,c)=>verCmp(a.v,c.v));
  verChart&&verChart.destroy();
  verChart=new Chart(verChart_cv(),{type:'bar',data:{labels:vs.map(v=>v.v),datasets:[{label:'Avg ★',data:vs.map(v=>v.avg),backgroundColor:vs.map(v=>v.avg>=4?'#16a34a':v.avg>=3?'#eab308':'#dc2626')}]},
    options:Object.assign(baseOpts({y:{min:1,max:5,ticks:{stepSize:1}}}),{plugins:{legend:{display:false},tooltip:{callbacks:{afterLabel:c=>`${vs[c.dataIndex].n.toLocaleString()} reviews`}}}})});}
function verChart_cv(){return document.getElementById('verChart');}
function verCmp(a,b){const pa=a.split('.').map(n=>parseInt(n)||0),pb=b.split('.').map(n=>parseInt(n)||0);
  for(let i=0;i<Math.max(pa.length,pb.length);i++){if((pa[i]||0)!==(pb[i]||0))return(pa[i]||0)-(pb[i]||0);}return 0;}

function renderTab1(){renderKPIs();renderMatrix();renderTab1Charts();}

/* ====================== TAB 2 ====================== */
function badAgg(bank){
  const mm=badSrc(bank);const subC={},parC={},sevC={};let badN=0;
  for(const m in mm){if(!inWindow(m))continue;for(const s in mm[m]){const c=mm[m][s];
    subC[s]=(subC[s]||0)+c;badN+=c;
    const p=BAD.sub_parent[s]||'Other';parC[p]=(parC[p]||0)+c;
    const v=BAD.sub_sev[s]||'Unknown';sevC[v]=(sevC[v]||0)+c;}}
  return{subC,parC,sevC,badN};
}
function badPeriods(bank){const mm=badSrc(bank),pm={};
  for(const m in mm){if(!inWindow(m))continue;const p=periodKey(m);if(!pm[p])pm[p]={bad:0,par:{}};
    for(const s in mm[m]){const c=mm[m][s];pm[p].bad+=c;const par=BAD.sub_parent[s]||'Other';pm[p].par[par]=(pm[p].par[par]||0)+c;}}
  return pm;}

function renderBadKPIs(){
  const sh=shown();let bad=0,tot=0;const par={};
  sh.forEach(b=>{const a=badAgg(b);bad+=a.badN;tot+=agg(b).n;
    for(const p in a.parC)par[p]=(par[p]||0)+a.parC[p];});
  const negRate=tot?bad/tot*100:0;
  // top concrete complaint (exclude Other/General)
  const concrete=Object.entries(par).filter(([p])=>p!=='Other'&&p!=='General Feedback').sort((a,b)=>b[1]-a[1]);
  const top=concrete[0];
  // worst bank by neg rate
  let worst=null,wr=-1;sh.forEach(b=>{const t=agg(b).n;const r=t?badAgg(b).badN/t*100:0;if(r>wr){wr=r;worst=b;}});
  // fastest rising parent (share, halves, active combined)
  const per={};sh.forEach(b=>{const pp=badPeriods(b);for(const p in pp){if(!per[p])per[p]={bad:0,par:{}};per[p].bad+=pp[p].bad;for(const c in pp[p].par)per[p].par[c]=(per[p].par[c]||0)+pp[p].par[c];}});
  const pers=Object.keys(per).sort();let rise=null,rv=0;
  if(pers.length>=2){const h=Math.floor(pers.length/2);
    const cats=new Set();pers.forEach(p=>Object.keys(per[p].par).forEach(c=>cats.add(c)));
    const shr=(arr,c)=>{let b=0,t=0;arr.forEach(p=>{t+=per[p].bad;b+=(per[p].par[c]||0);});return t?b/t*100:0;};
    cats.forEach(c=>{if(c==='Other')return;const d=shr(pers.slice(h),c)-shr(pers.slice(0,h),c);if(d>rv){rv=d;rise=c;}});}
  const k=[['Total bad reviews',bad.toLocaleString(),''],
    ['Overall negative rate',negRate.toFixed(1)+'%',''],
    ['Top complaint',top?top[0]:'—',top?top[1].toLocaleString()+' reviews':''],
    ['Worst bank (neg rate)',worst?`${worst} · ${wr.toFixed(1)}%`:'—',''],
    ['Fastest rising',rise||'—',rise?'+'+rv.toFixed(1)+' pts share':'']];
  document.getElementById('badKpis').innerHTML=k.map(([l,v,d])=>
    `<div class="kpi"><div class="l">${l}</div><div class="v" style="font-size:${v.length>16?'18px':'24px'}">${v}</div><div class="d">${d}</div></div>`).join('');
}
let negBar,negLine,mixChart,trendChart,sevChart;
function renderNegRate(){
  const sh=shown();
  negBar&&negBar.destroy();
  negBar=new Chart(negRateBar,{type:'bar',data:{labels:sh,datasets:[{label:'Negative rate',
    data:sh.map(b=>{const t=agg(b).n;return t?badAgg(b).badN/t*100:0;}),backgroundColor:sh.map(b=>COLORS[b])}]},
    options:Object.assign(baseOpts({y:{beginAtZero:true,ticks:{callback:v=>v+'%'}}}),{plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>c.parsed.y.toFixed(1)+'%'}}}})});
  // over time: neg rate per period per bank
  const periods=allPeriods();
  const ds=sh.map(b=>{const bp=badPeriods(b),tot=Object.fromEntries(agg(b).series.map(s=>[s.p,s.n]));
    return{label:b,borderColor:COLORS[b],backgroundColor:COLORS[b],tension:.3,spanGaps:true,pointRadius:0,borderWidth:2,
      data:periods.map(p=>{const t=tot[p];return t?((bp[p]?bp[p].bad:0)/t*100):null;})};});
  negLine&&negLine.destroy();
  negLine=new Chart(negRateLine,{type:'line',data:{labels:periods,datasets:ds},options:Object.assign(baseOpts({y:{beginAtZero:true,ticks:{callback:v=>v+'%'}}}),{plugins:{legend:{position:'bottom',labels:{boxWidth:10,font:{size:10}},onHover:LH.onHover,onLeave:LH.onLeave},tooltip:{callbacks:{label:c=>c.dataset.label+': '+(c.parsed.y==null?'—':c.parsed.y.toFixed(1)+'%')}}}})});
}
function renderMix(){
  const sh=shown(),lvl=state.mixLevel,share=state.mixValue==='share';
  const keys=lvl==='parent'?BAD.parents:BAD.subs_order;
  const colf=lvl==='parent'?(k=>BAD.parent_colors[k]):(k=>SUBCOLOR[k]);
  const A={};sh.forEach(b=>A[b]=badAgg(b));
  const ds=keys.map(k=>({label:k,backgroundColor:colf(k),
    data:sh.map(b=>{const src=lvl==='parent'?A[b].parC:A[b].subC;const val=src[k]||0;
      return share?(A[b].badN?val/A[b].badN*100:0):val;})}));
  mixChart&&mixChart.destroy();
  mixChart=new Chart(document.getElementById('mixChart'),{type:'bar',data:{labels:sh,datasets:ds},
    options:Object.assign(baseOpts({x:{stacked:true,beginAtZero:true,max:share?100:undefined,ticks:share?{callback:v=>v+'%'}:{}},y:{stacked:true}},'y'),
    {plugins:{legend:{position:'bottom',labels:{boxWidth:9,font:{size:9}},onHover:LH.onHover,onLeave:LH.onLeave},
      tooltip:{callbacks:{label:c=>`${c.dataset.label}: ${share?c.parsed.x.toFixed(1)+'%':c.parsed.x.toLocaleString()}`}}}})});
}
function renderTrend(){
  const sel=document.getElementById('trendBank').value;
  const sh=sel?[sel]:BANKS,periods=allPeriods();
  const per={};sh.forEach(b=>{const pp=badPeriods(b);for(const p in pp)for(const c in pp[p].par){if(!per[c])per[c]={};per[c][p]=(per[c][p]||0)+pp[p].par[c];}});
  const cats=BAD.parents.filter(c=>per[c]);
  const ds=cats.map(c=>({label:c,borderColor:BAD.parent_colors[c],backgroundColor:BAD.parent_colors[c],tension:.3,pointRadius:0,borderWidth:2,spanGaps:true,
    data:periods.map(p=>per[c][p]||0)}));
  trendChart&&trendChart.destroy();
  trendChart=new Chart(document.getElementById('trendChart'),{type:'line',data:{labels:periods,datasets:ds},options:baseOpts({y:{beginAtZero:true}})});
}
function renderSev(){
  const sh=shown(),A={};sh.forEach(b=>A[b]=badAgg(b));
  const ds=BAD.sev_order.map(s=>({label:s,backgroundColor:BAD.sev_colors[s],
    data:sh.map(b=>{const t=A[b].badN||1;return(A[b].sevC[s]||0)/t*100;})}));
  sevChart&&sevChart.destroy();
  sevChart=new Chart(document.getElementById('sevChart'),{type:'bar',data:{labels:sh,datasets:ds},
    options:Object.assign(baseOpts({x:{stacked:true,max:100,ticks:{callback:v=>v+'%'}},y:{stacked:true}},'y'),
    {plugins:{legend:{position:'bottom',labels:{boxWidth:10,font:{size:10}},onHover:LH.onHover,onLeave:LH.onLeave},tooltip:{callbacks:{label:c=>`${c.dataset.label}: ${c.parsed.x.toFixed(1)}%`}}}})});
}
function renderCooc(){
  const sel=document.getElementById('coocBank').value;
  const banks=sel?[sel]:BANKS;
  const subs=BAD.concrete_subs,N=subs.length,M=Array.from({length:N},()=>new Array(N).fill(0));
  banks.forEach(b=>{const c=BAD.cooc[b]||{};for(const key in c){const[i,j]=key.split(',').map(Number);M[i][j]+=c[key];if(i!==j)M[j][i]+=c[key];}});
  const diag=subs.map((s,i)=>[i,M[i][i]]).sort((a,b)=>b[1]-a[1]).slice(0,12).map(x=>x[0]);
  let maxOff=1;diag.forEach(i=>diag.forEach(j=>{if(i!==j&&M[i][j]>maxOff)maxOff=M[i][j];}));
  const sh=s=>s.replace('/ ','/ ').split(' ').map(w=>w).join(' ');
  let html='<table class="heat"><tr><th></th>'+diag.map(j=>`<th class="colh"><div>${subs[j]}</div></th>`).join('')+'</tr>';
  diag.forEach(i=>{html+=`<tr><th class="rowh">${subs[i]}</th>`;
    diag.forEach(j=>{const v=M[i][j];if(i===j){html+=`<td class="diag">${v.toLocaleString()}</td>`;}
      else{const a=v/maxOff;html+=`<td style="background:rgba(180,83,9,${(a*0.85).toFixed(3)});color:${a>0.5?'#fff':'#3c372e'}">${v?v.toLocaleString():''}</td>`;}});
    html+='</tr>';});
  html+='</table>';
  document.getElementById('coocWrap').innerHTML=html;
}
function renderTab2(){renderBadKPIs();renderNegRate();renderMix();renderTrend();renderSev();renderCooc();}

/* ====================== TAB 3 — examples ====================== */
const EX=DATA.examples||[];
let exState={sort:'recent'};
function escapeHtml(s){return(s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function fillExSub(){const cat=exCat.value,cur=exSub.value;
  const subs=BAD.subs_order.filter(s=>!cat||BAD.sub_parent[s]===cat);
  exSub.innerHTML='<option value="">All subcategories</option>'+subs.map(s=>`<option ${s===cur?'selected':''}>${s}</option>`).join('');}
function renderExamples(){
  const from=exFrom.value,to=exTo.value,bank=exBank.value,star=exStar.value,
    cat=exCat.value,sub=exSub.value,any=exAny.value,q=exSearch.value.trim().toLowerCase();
  let rows=EX.filter(r=>(!from||r.d>=from)&&(!to||r.d<=to)&&(!bank||r.b===bank)&&(!star||r.s==+star)
    &&(!cat||r.c===cat)&&(!sub||r.sc===sub)&&(!any||(r.m&&r.m.includes(any))||r.sc===any)
    &&(!q||r.t.toLowerCase().includes(q))).slice();
  if(exState.sort==='thumbs')rows.sort((a,b)=>(b.th-a.th)||(a.d<b.d?1:-1));
  else rows.sort((a,b)=>a.d<b.d?1:a.d>b.d?-1:0);
  const tb=document.querySelector('#exTable tbody');
  tb.innerHTML=rows.slice(0,400).map(r=>{
    const pcol=BAD.parent_colors[r.c]||'#9ca3af';
    const chips=((r.m&&r.m.length?r.m:[r.sc])).map(s=>`<span class="chip">${s}</span>`).join('');
    return `<tr><td style="white-space:nowrap">${r.d}</td>
      <td class="bankname"><span class="dot" style="background:${COLORS[r.b]||'#999'}"></span>${r.b}</td>
      <td class="num"><span class="stars">${'★'.repeat(r.s)}${'☆'.repeat(5-r.s)}</span></td>
      <td><span class="catpill" style="background:${pcol}">${r.c}</span></td>
      <td>${r.sc}</td><td>${chips}</td>
      <td class="ex-text">${escapeHtml(r.t)}</td><td class="num">${r.th||0}</td></tr>`;}).join('');
  document.getElementById('exCount').textContent=`${rows.length.toLocaleString()} reviews match (showing up to 400 of ${EX.length.toLocaleString()} sampled).`;
}

/* ---------- orchestration ---------- */
function renderActive(){state._cut=monthsBack(state.win);
  state.tab==='1'?renderTab1():state.tab==='2'?renderTab2():renderExamples();}

function init(){
  document.getElementById('genstamp').textContent='Generated '+DATA.generated_at;
  document.getElementById('subtitle').textContent=`Google Play Store · Indonesia · ${BANKS.length} apps`;
  document.getElementById('bankToggles').innerHTML=BANKS.map(b=>
    `<label style="margin-right:10px;cursor:pointer;white-space:nowrap"><input type="checkbox" data-bank="${b}" checked>
      <span class="dot" style="background:${COLORS[b]}"></span>${b}</label>`).join('');
  document.querySelectorAll('#bankToggles input').forEach(cb=>cb.addEventListener('change',e=>{
    const b=e.target.dataset.bank;e.target.checked?state.active.add(b):state.active.delete(b);renderActive();}));
  verBank.innerHTML=BANKS.map(b=>`<option>${b}</option>`).join('');
  volBank.innerHTML=BANKS.map(b=>`<option>${b}</option>`).join('');
  verBank.addEventListener('change',renderVerChart);
  volBank.addEventListener('change',renderVolChart);
  const allOpt='<option value="">All banks</option>'+BANKS.map(b=>`<option>${b}</option>`).join('');
  trendBank.innerHTML=allOpt;coocBank.innerHTML=allOpt;
  trendBank.addEventListener('change',renderTrend);
  coocBank.addEventListener('change',renderCooc);
  document.querySelectorAll('#winSeg button').forEach(b=>b.addEventListener('click',e=>{
    document.querySelectorAll('#winSeg button').forEach(x=>x.classList.remove('active'));e.target.classList.add('active');
    state.win=+e.target.dataset.w;
    if(state.win===3)setGran('day');
    else if((state.win>=12||state.win===0)&&state.gran==='day')setGran('month');
    renderActive();}));
  document.querySelectorAll('#granSeg button').forEach(b=>b.addEventListener('click',e=>{
    document.querySelectorAll('#granSeg button').forEach(x=>x.classList.remove('active'));e.target.classList.add('active');state.gran=e.target.dataset.g;renderActive();}));
  document.querySelectorAll('#matrix th').forEach(th=>th.addEventListener('click',()=>{
    const k=th.dataset.k;state.matrixSort=state.matrixSort.k===k?{k,asc:!state.matrixSort.asc}:{k,asc:false};renderMatrix();}));
  // tab2 toggles
  document.querySelectorAll('#mixLevel button').forEach(b=>b.addEventListener('click',e=>{
    document.querySelectorAll('#mixLevel button').forEach(x=>x.classList.remove('active'));e.target.classList.add('active');state.mixLevel=e.target.dataset.l;renderMix();}));
  document.querySelectorAll('#mixValue button').forEach(b=>b.addEventListener('click',e=>{
    document.querySelectorAll('#mixValue button').forEach(x=>x.classList.remove('active'));e.target.classList.add('active');state.mixValue=e.target.dataset.v;renderMix();}));
  // examples tab filters
  exBank.innerHTML='<option value="">All banks</option>'+BANKS.map(b=>`<option>${b}</option>`).join('');
  exCat.innerHTML='<option value="">All categories</option>'+BAD.parents.map(p=>`<option>${p}</option>`).join('');
  exAny.innerHTML='<option value="">Any complaint…</option>'+BAD.subs_order.map(s=>`<option>${s}</option>`).join('');
  fillExSub();
  ['exFrom','exTo','exBank','exStar','exSub','exAny','exSearch'].forEach(id=>document.getElementById(id).addEventListener('input',renderExamples));
  exCat.addEventListener('change',()=>{fillExSub();renderExamples();});
  document.querySelectorAll('#exSort button').forEach(b=>b.addEventListener('click',e=>{
    document.querySelectorAll('#exSort button').forEach(x=>x.classList.remove('active'));e.target.classList.add('active');exState.sort=e.target.dataset.s;renderExamples();}));
  document.getElementById('exReset').addEventListener('click',()=>{
    ['exFrom','exTo','exBank','exStar','exCat','exAny','exSearch'].forEach(id=>document.getElementById(id).value='');
    fillExSub();exState.sort='recent';
    document.querySelectorAll('#exSort button').forEach((x,i)=>x.classList.toggle('active',i===0));renderExamples();});

  // tab switching
  document.querySelectorAll('.tabnav button').forEach(b=>b.addEventListener('click',e=>{
    document.querySelectorAll('.tabnav button').forEach(x=>x.classList.remove('active'));e.target.classList.add('active');
    state.tab=e.target.dataset.tab;
    document.getElementById('tab1').hidden=state.tab!=='1';
    document.getElementById('tab2').hidden=state.tab!=='2';
    document.getElementById('tab3').hidden=state.tab!=='3';
    document.getElementById('controls').hidden=state.tab==='3';
    renderActive();}));
  document.getElementById('foot').innerHTML=
    `Created by <b>Redi Sunarta</b> · Source: Google Play Store · ${Object.values(BM).reduce((s,m)=>s+m.total,0).toLocaleString()} reviews · ${BAD.total.toLocaleString()} classified 1–3★ · Regenerate: python build_dashboard.py`;
  renderActive();
}
init();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    build()
