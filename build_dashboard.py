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
    "Allo_Bank":          ("Allo Bank",   "#f87171"),
    "Bank_Jago":          ("Bank Jago",   "#fbbf24"),
    "Blu_by_BCA_Digital": ("blu by BCA",  "#38bdf8"),
    "Jenius":             ("Jenius",      "#2dd4bf"),
    "Neobank_BNC":        ("Neobank BNC", "#a78bfa"),
    "Sea_Bank":           ("SeaBank",     "#4ade80"),
    "Superbank":          ("Superbank",   "#f472b6"),
    "Krom_Bank":          ("Krom Bank",   "#818cf8"),
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
    "Access & Account": "#60a5fa", "Transactions": "#22d3ee", "Funds & Security": "#f87171",
    "Loans & Limits": "#fbbf24", "App Performance": "#a78bfa", "Customer Service": "#f472b6",
    "General Feedback": "#a3e635", "Other": "#64748b",
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
SEV_COLORS = {"Financial harm": "#f87171", "Access blocker": "#fbbf24",
              "Experience": "#60a5fa", "Unknown": "#64748b"}
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
<title>ID Digital Banks · Play Store Intelligence</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
:root{
  --bg:#0a0e16; --bg2:#0d1220; --panel:#111827; --panel2:#151d2e;
  --line:rgba(148,163,184,.13); --line2:rgba(148,163,184,.22);
  --ink:#e7ebf3; --muted:#94a0b4; --dim:#5f6b80;
  --accent:#6366f1; --accent2:#818cf8; --good:#34d399; --bad:#f87171; --warn:#fbbf24;
  --r:14px; --r-sm:9px;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px -12px rgba(0,0,0,.5);
}
*{box-sizing:border-box}
html{scrollbar-color:#2b3548 var(--bg)}
body{margin:0;background:var(--bg);color:var(--ink);font-size:14px;line-height:1.5;
  font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;
  background-image:radial-gradient(1200px 500px at 70% -10%,rgba(99,102,241,.08),transparent 60%);}
a{color:var(--accent2)}
::selection{background:rgba(99,102,241,.35)}

/* ---------- header ---------- */
.topbar{position:sticky;top:0;z-index:50;background:rgba(10,14,22,.82);backdrop-filter:blur(14px);
  border-bottom:1px solid var(--line);}
.topbar-in{max-width:1360px;margin:0 auto;padding:0 24px;}
.brandrow{display:flex;align-items:center;gap:14px;padding:14px 0 10px;flex-wrap:wrap;}
.logo{width:34px;height:34px;border-radius:9px;flex:none;display:grid;place-items:center;
  background:linear-gradient(135deg,#6366f1,#22d3ee);font-weight:800;font-size:15px;color:#fff;}
.brand h1{margin:0;font-size:16px;font-weight:700;letter-spacing:-.01em;}
.brand .sub{font-size:12px;color:var(--muted);margin-top:1px;}
.stamp{margin-left:auto;font-size:11.5px;color:var(--dim);text-align:right;}
.tabs{display:flex;gap:2px;}
.tabs button{border:0;background:none;color:var(--muted);font:inherit;font-weight:600;font-size:13px;
  padding:9px 14px;cursor:pointer;border-bottom:2px solid transparent;border-radius:6px 6px 0 0;}
.tabs button:hover{color:var(--ink);background:rgba(148,163,184,.06);}
.tabs button.active{color:#fff;border-bottom-color:var(--accent);}

/* ---------- controls ---------- */
.controls{max-width:1360px;margin:0 auto;padding:14px 24px 0;display:flex;gap:18px;align-items:center;flex-wrap:wrap;}
.ctl{display:flex;align-items:center;gap:8px;}
.ctl>label{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.07em;color:var(--dim);}
.seg{display:inline-flex;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:2px;}
.seg button{border:0;background:none;color:var(--muted);font:inherit;font-size:12.5px;font-weight:600;
  padding:5px 11px;cursor:pointer;border-radius:6px;}
.seg button:hover{color:var(--ink)}
.seg button.active{background:var(--accent);color:#fff;}
.seg button:disabled{opacity:.35;cursor:not-allowed;}
.rangelabel{font-size:12px;color:var(--muted);background:var(--panel);border:1px solid var(--line);
  border-radius:8px;padding:6px 12px;white-space:nowrap;}
.chips{display:flex;gap:6px;flex-wrap:wrap;align-items:center;}
.chip{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--line);background:var(--panel);
  color:var(--ink);border-radius:99px;padding:5px 12px 5px 9px;font-size:12.5px;font-weight:600;cursor:pointer;
  user-select:none;transition:opacity .12s,border-color .12s;}
.chip .dot{width:9px;height:9px;border-radius:99px;flex:none;}
.chip.off{opacity:.38;}
.chip.locked{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent);}
.chip:hover{border-color:var(--line2)}
.chiphint{font-size:11px;color:var(--dim);margin-left:2px;}
.btn{border:1px solid var(--line);background:var(--panel);color:var(--ink);font:inherit;font-size:12.5px;
  font-weight:600;padding:6px 14px;border-radius:8px;cursor:pointer;}
.btn:hover{border-color:var(--accent);color:#fff;}
.btn.active{background:var(--accent);border-color:var(--accent);color:#fff;}

/* ---------- layout ---------- */
.wrap{max-width:1360px;margin:0 auto;padding:18px 24px 70px;}
.grid{display:grid;gap:16px;}
.g2{grid-template-columns:repeat(auto-fit,minmax(min(460px,100%),1fr));}
.card{background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--line);
  border-radius:var(--r);padding:18px 20px;box-shadow:var(--shadow);position:relative;margin-bottom:16px;}
.grid .card{margin-bottom:0;}
.card h2{margin:0;font-size:14px;font-weight:700;letter-spacing:-.01em;}
.card .hint{color:var(--dim);font-size:12px;margin:2px 0 0;}
.cardhead{display:flex;align-items:flex-start;gap:12px;margin-bottom:14px;flex-wrap:wrap;}
.cardhead .sp{margin-left:auto;display:flex;gap:8px;align-items:center;flex-wrap:wrap;}
select{font:inherit;font-size:12.5px;font-weight:500;padding:6px 28px 6px 10px;border:1px solid var(--line);
  border-radius:8px;background:var(--panel) url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="10" height="6" viewBox="0 0 10 6"><path d="M1 1l4 4 4-4" stroke="%2394a0b4" stroke-width="1.5" fill="none" stroke-linecap="round"/></svg>') no-repeat right 10px center;
  color:var(--ink);appearance:none;cursor:pointer;}
select:hover{border-color:var(--line2)}
input[type=search],input[type=date]{font:inherit;font-size:13px;padding:7px 12px;border:1px solid var(--line);
  border-radius:8px;background:var(--panel);color:var(--ink);color-scheme:dark;}
input[type=search]:focus,input[type=date]:focus,select:focus{outline:none;border-color:var(--accent);}
.dl{border:0;background:none;color:var(--dim);cursor:pointer;font-size:14px;padding:2px 6px;border-radius:6px;}
.dl:hover{color:var(--ink);background:rgba(148,163,184,.1);}
.chartbox{position:relative;height:300px;}
.chartbox.tall{height:400px;} .chartbox.sm{height:240px;}

/* ---------- insights ---------- */
.insights{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(280px,100%),1fr));gap:12px;margin-bottom:16px;}
.insight{border:1px solid var(--line);border-radius:12px;padding:13px 15px;background:var(--panel);
  border-left:3px solid var(--accent);box-shadow:var(--shadow);}
.insight .tag{font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--dim);}
.insight .head{font-size:13.5px;font-weight:700;margin:4px 0 2px;}
.insight .det{font-size:12px;color:var(--muted);}
.insight.up{border-left-color:var(--good);} .insight.down{border-left-color:var(--bad);}
.insight.warn{border-left-color:var(--warn);}

/* ---------- KPIs ---------- */
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(200px,100%),1fr));gap:12px;margin-bottom:16px;}
.kpi{background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--line);
  border-radius:12px;padding:14px 16px;box-shadow:var(--shadow);}
.kpi .l{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.07em;color:var(--dim);}
.kpi .v{font-size:26px;font-weight:800;letter-spacing:-.02em;margin-top:6px;line-height:1.1;}
.kpi .v .unit{font-size:14px;font-weight:600;color:var(--muted);margin-left:2px;}
.kpi .d{font-size:12px;margin-top:5px;color:var(--muted);}
.pos{color:var(--good);} .neg{color:var(--bad);}

/* ---------- table ---------- */
.tblwrap{overflow-x:auto;margin:0 -6px;}
table{border-collapse:collapse;width:100%;font-size:13px;}
th{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--dim);
  text-align:left;padding:8px 10px;border-bottom:1px solid var(--line2);cursor:pointer;white-space:nowrap;user-select:none;}
th:hover{color:var(--muted)} th.num{text-align:right;} td.num{text-align:right;font-variant-numeric:tabular-nums;}
th .arrow{font-size:9px;color:var(--accent2);}
td{padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:middle;}
tbody tr{cursor:pointer;transition:background .1s,opacity .15s;}
tbody tr:hover{background:rgba(148,163,184,.05);}
tbody tr.dim{opacity:.3;}
tbody tr.focus{background:rgba(99,102,241,.09);}
.bname{display:flex;align-items:center;gap:9px;font-weight:600;white-space:nowrap;}
.bname .dot{width:9px;height:9px;border-radius:99px;flex:none;}
.mixbar{display:flex;height:9px;border-radius:5px;overflow:hidden;min-width:120px;background:var(--bg2);}
.mixbar i{display:block;height:100%;}
.delta-pill{font-size:11.5px;font-weight:700;padding:2px 8px;border-radius:99px;white-space:nowrap;}
.delta-pill.pos{background:rgba(52,211,153,.13);} .delta-pill.neg{background:rgba(248,113,113,.13);}
.delta-pill.zero{background:rgba(148,163,184,.12);color:var(--muted);}

/* ---------- compare ---------- */
.cmpgrid{display:grid;grid-template-columns:1fr 1fr;gap:16px;}
@media(max-width:760px){.cmpgrid{grid-template-columns:1fr;}}
.cmpcol{border:1px solid var(--line);border-radius:12px;padding:16px;background:var(--bg2);}
.cmpcol .bighead{display:flex;align-items:center;gap:10px;margin-bottom:12px;}
.cmpcol .bighead .dot{width:12px;height:12px;border-radius:99px;}
.cmpcol .bighead b{font-size:16px;}
.cmpstat{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--line);font-size:13px;}
.cmpstat span:first-child{color:var(--muted);} .cmpstat b{font-variant-numeric:tabular-nums;}
.cmpsub{margin-top:12px;}
.cmpsub .row{display:flex;align-items:center;gap:10px;margin:6px 0;font-size:12.5px;}
.cmpsub .row .nm{flex:0 0 175px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.cmpsub .row .bar{flex:1;height:8px;border-radius:5px;background:var(--bg);overflow:hidden;}
.cmpsub .row .bar i{display:block;height:100%;border-radius:5px;}
.cmpsub .row .pc{flex:0 0 44px;text-align:right;font-variant-numeric:tabular-nums;font-weight:600;}

/* ---------- heat tables ---------- */
.heatwrap{overflow-x:auto;}
.heat{border-collapse:separate;border-spacing:2px;font-size:11.5px;}
.heat th{border:0;padding:5px 7px;cursor:default;}
.heat td{border:0;border-radius:5px;text-align:center;padding:6px 8px;font-variant-numeric:tabular-nums;
  font-weight:600;min-width:46px;color:#dbe3f0;}
.heat .rowlab{text-align:right;color:var(--muted);font-weight:500;background:none;white-space:nowrap;max-width:190px;overflow:hidden;text-overflow:ellipsis;}
.heat thead th{color:var(--dim);font-size:10.5px;max-width:80px;overflow:hidden;text-overflow:ellipsis;}
.legendbar{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--dim);margin-top:10px;}
.legendbar .grad{width:140px;height:8px;border-radius:4px;}

/* ---------- examples ---------- */
.exfilters{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:6px;}
.excount{font-size:12px;color:var(--dim);margin:10px 2px;}
.excards{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(390px,100%),1fr));gap:12px;}
.excard{border:1px solid var(--line);border-radius:12px;background:var(--panel);padding:14px 16px;
  display:flex;flex-direction:column;gap:8px;box-shadow:var(--shadow);}
.exhead{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12px;color:var(--muted);}
.exbank{display:inline-flex;align-items:center;gap:6px;font-weight:700;color:var(--ink);font-size:12.5px;}
.exbank .dot{width:8px;height:8px;border-radius:99px;}
.exstars{color:var(--warn);letter-spacing:1.5px;font-size:12px;}
.exdate{margin-left:auto;color:var(--dim);white-space:nowrap;}
.extext{font-size:13px;line-height:1.55;color:#cdd5e1;}
.exfoot{display:flex;gap:5px;flex-wrap:wrap;align-items:center;}
.expill{font-size:10.5px;font-weight:700;border-radius:99px;padding:2px 9px;color:#fff;white-space:nowrap;}
.exchip{font-size:10.5px;font-weight:600;border-radius:99px;padding:2px 9px;background:rgba(148,163,184,.12);
  color:var(--muted);white-space:nowrap;}
.exthumbs{margin-left:auto;font-size:11px;color:var(--dim);}
.loadmore{display:block;margin:18px auto 0;}

.foot{max-width:1360px;margin:0 auto;padding:0 24px;color:var(--dim);font-size:11.5px;}
.empty{color:var(--dim);font-size:13px;padding:30px 0;text-align:center;}
@media(max-width:700px){
  .wrap,.topbar-in,.controls,.foot{padding-left:14px;padding-right:14px;}
  .chartbox{height:250px;} .stamp{display:none;}
}
</style>
</head>
<body>

<div class="topbar">
  <div class="topbar-in">
    <div class="brandrow">
      <div class="logo">ID</div>
      <div class="brand">
        <h1>Digital Bank Intelligence</h1>
        <div class="sub">Google Play reviews · Indonesia · 8 digital banks</div>
      </div>
      <div class="stamp" id="stamp"></div>
    </div>
    <div class="tabs" id="tabs">
      <button data-tab="1" class="active">Overview</button>
      <button data-tab="2">Complaints</button>
      <button data-tab="3">Browse reviews</button>
    </div>
  </div>
</div>

<div class="controls" id="globalControls">
  <div class="ctl"><label>Window</label>
    <span class="seg" id="winSeg">
      <button data-w="1">1m</button><button data-w="3" class="active">3m</button>
      <button data-w="6">6m</button><button data-w="12">12m</button><button data-w="0">All</button>
    </span></div>
  <div class="ctl"><label>Granularity</label>
    <span class="seg" id="granSeg">
      <button data-g="day">Daily</button><button data-g="month" class="active">Monthly</button>
      <button data-g="quarter">Quarterly</button>
    </span></div>
  <span class="rangelabel" id="rangeLabel"></span>
  <div class="ctl" style="flex:1;min-width:280px">
    <label>Banks</label>
    <span class="chips" id="bankChips"></span>
    <span class="chiphint">click = toggle · dbl-click = solo · row-click locks focus</span>
  </div>
  <button class="btn" id="cmpBtn">⇄ Compare</button>
</div>

<div class="wrap">

  <!-- ============ TAB 1 : OVERVIEW ============ -->
  <div id="tab1" class="tabpanel">
    <div class="insights" id="insights"></div>
    <div class="kpis" id="kpis"></div>

    <div class="card" id="cmpCard" hidden>
      <div class="cardhead">
        <div><h2>Head-to-head</h2><div class="hint">Two banks, same window.</div></div>
        <div class="sp">
          <select id="cmpA"></select><span style="color:var(--dim);font-size:12px">vs</span><select id="cmpB"></select>
        </div>
      </div>
      <div class="cmpgrid" id="cmpGrid"></div>
    </div>

    <div class="card">
      <div class="cardhead">
        <div><h2>Benchmark</h2><div class="hint">Per bank over the selected window · click a header to sort · click a row to focus that bank everywhere.</div></div>
      </div>
      <div class="tblwrap"><table id="matrix"><thead><tr>
        <th data-k="bank">Bank</th><th data-k="avg" class="num">Avg ★</th>
        <th data-k="total" class="num">Reviews</th><th data-k="pos" class="num">4–5★</th>
        <th data-k="neg" class="num">1–2★</th><th data-k="delta" class="num">Δ window</th>
        <th>Star mix</th><th>Trend</th>
      </tr></thead><tbody></tbody></table></div>
    </div>

    <div class="grid g2">
      <div class="card">
        <div class="cardhead"><div><h2>Average rating over time</h2>
          <div class="hint">Weighted per period. Hover a bank chip to isolate.</div></div>
          <div class="sp"><button class="dl" data-dl="ratingLine" title="Download PNG">⤓</button></div></div>
        <div class="chartbox"><canvas id="ratingLine"></canvas></div>
      </div>
      <div class="card">
        <div class="cardhead"><div><h2>Review volume</h2>
          <div class="hint">Stacked reviews per period, all selected banks.</div></div>
          <div class="sp"><button class="dl" data-dl="volumeBar" title="Download PNG">⤓</button></div></div>
        <div class="chartbox"><canvas id="volumeBar"></canvas></div>
      </div>
    </div>

    <div class="grid g2" style="margin-top:16px">
      <div class="card">
        <div class="cardhead"><div><h2>Star distribution</h2>
          <div class="hint">Share of each rating within the window.</div></div>
          <div class="sp"><button class="dl" data-dl="starDist" title="Download PNG">⤓</button></div></div>
        <div class="chartbox"><canvas id="starDist"></canvas></div>
      </div>
      <div class="card">
        <div class="cardhead"><div><h2>Rating by app version</h2>
          <div class="hint">Spot bad releases — top versions by volume, all-time.</div></div>
          <div class="sp"><select id="verBank"></select><button class="dl" data-dl="verChart" title="Download PNG">⤓</button></div></div>
        <div class="chartbox"><canvas id="verChart"></canvas></div>
      </div>
    </div>
  </div>

  <!-- ============ TAB 2 : COMPLAINTS ============ -->
  <div id="tab2" class="tabpanel" hidden>
    <div class="kpis" id="badKpis"></div>

    <div class="grid g2">
      <div class="card">
        <div class="cardhead"><div><h2>Negative review rate</h2>
          <div class="hint">1–3★ share of each bank's reviews in the window.</div></div>
          <div class="sp"><button class="dl" data-dl="negRateBar" title="Download PNG">⤓</button></div></div>
        <div class="chartbox"><canvas id="negRateBar"></canvas></div>
      </div>
      <div class="card">
        <div class="cardhead"><div><h2>Negative rate over time</h2>
          <div class="hint">1–3★ share per period.</div></div>
          <div class="sp"><button class="dl" data-dl="negRateLine" title="Download PNG">⤓</button></div></div>
        <div class="chartbox"><canvas id="negRateLine"></canvas></div>
      </div>
    </div>

    <div class="card" style="margin-top:16px">
      <div class="cardhead">
        <div><h2>Complaint mix</h2><div class="hint">What 1–3★ reviewers complain about, per bank.</div></div>
        <div class="sp">
          <span class="seg" id="mixLevel"><button data-l="parent" class="active">Category</button><button data-l="sub">Subcategory heatmap</button></span>
        </div>
      </div>
      <div id="mixParentBox" class="chartbox tall"><canvas id="mixChart"></canvas></div>
      <div id="mixSubBox" class="heatwrap" hidden></div>
    </div>

    <div class="grid g2" style="margin-top:16px">
      <div class="card">
        <div class="cardhead"><div><h2>Complaint trend</h2>
          <div class="hint">Bad reviews per category per period.</div></div>
          <div class="sp"><select id="trendBank"></select><button class="dl" data-dl="trendChart" title="Download PNG">⤓</button></div></div>
        <div class="chartbox"><canvas id="trendChart"></canvas></div>
      </div>
      <div class="card">
        <div class="cardhead"><div><h2>Severity split</h2>
          <div class="hint">Financial harm &gt; access blockers &gt; experience.</div></div>
          <div class="sp"><button class="dl" data-dl="sevChart" title="Download PNG">⤓</button></div></div>
        <div class="chartbox"><canvas id="sevChart"></canvas></div>
      </div>
    </div>

    <div class="card" style="margin-top:16px">
      <div class="cardhead">
        <div><h2>Complaint co-occurrence</h2>
          <div class="hint">How often two complaint types appear in the same review (all-time). Diagonal = total mentions.</div></div>
        <div class="sp"><select id="coocBank"></select></div>
      </div>
      <div class="heatwrap" id="coocWrap"></div>
      <div class="legendbar"><span>fewer</span><span class="grad" id="coocGrad"></span><span>more</span></div>
    </div>
  </div>

  <!-- ============ TAB 3 : BROWSE ============ -->
  <div id="tab3" class="tabpanel" hidden>
    <div class="card">
      <div class="cardhead">
        <div><h2>Review browser</h2>
          <div class="hint">Sampled 1–3★ review text (up to ~50 most-recent + most-helpful per bank × subcategory).</div></div>
      </div>
      <div class="exfilters">
        <select id="exBank"></select>
        <span class="seg" id="exStarSeg">
          <button data-s="" class="active">All ★</button><button data-s="1">1★</button>
          <button data-s="2">2★</button><button data-s="3">3★</button>
        </span>
        <select id="exCat"></select>
        <select id="exSub"></select>
        <span class="seg" id="exSort"><button data-s="recent" class="active">Recent</button><button data-s="thumbs">Helpful</button></span>
        <input id="exFrom" type="date" title="From"><input id="exTo" type="date" title="To">
        <input id="exSearch" type="search" placeholder="Search review text…" style="flex:1;min-width:200px">
        <button class="btn" id="exReset">Reset</button>
      </div>
      <div class="excount" id="exCount"></div>
      <div class="excards" id="exCards"></div>
      <button class="btn loadmore" id="exMore" hidden>Load more</button>
    </div>
  </div>

  <div class="foot" id="foot"></div>
</div>

<script>
const DATA=/*__DATA__*/;
const BANKS=DATA.banks, META=DATA.bank_meta, BAD=DATA.bad, EX=DATA.examples||[];
const COL=b=>META[b].color;
const state={tab:'1',win:3,gran:'month',active:new Set(BANKS),focus:null,hover:null,cmp:false,
  mixLevel:'parent',exPage:1,exStar:'',exSort:'recent',_cut:'0000-00'};
const CH={}; // chart registry
const $=id=>document.getElementById(id);
const fmt=n=>n.toLocaleString('en-US');
const pct=(x,d=1)=>(x*100).toFixed(d)+'%';
const signed=x=>(x>=0?'+':'')+x.toFixed(2);
const esc=s=>(s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function toRGBA(c,a){if(c.startsWith('#')){const v=parseInt(c.slice(1),16);
  return `rgba(${v>>16&255},${v>>8&255},${v&255},${a})`;}return c;}

/* ---------- chart defaults ---------- */
Chart.defaults.color='#8b95a8';
Chart.defaults.borderColor='rgba(148,163,184,.08)';
Chart.defaults.font.family="'Inter',-apple-system,sans-serif";
Chart.defaults.font.size=11.5;
Chart.defaults.plugins.tooltip.backgroundColor='#1a2233';
Chart.defaults.plugins.tooltip.borderColor='rgba(148,163,184,.25)';
Chart.defaults.plugins.tooltip.borderWidth=1;
Chart.defaults.plugins.tooltip.padding=10;
Chart.defaults.plugins.tooltip.titleFont={weight:'700'};
Chart.defaults.plugins.tooltip.cornerRadius=8;
Chart.defaults.plugins.legend.labels.boxWidth=10;
Chart.defaults.plugins.legend.labels.boxHeight=10;
Chart.defaults.plugins.legend.labels.usePointStyle=true;
Chart.defaults.plugins.legend.labels.pointStyle='circle';
Chart.defaults.animation.duration=250;

/* ---------- time helpers ---------- */
function latestMonth(){let l='0000-00';BANKS.forEach(b=>(DATA.monthly[b]||[]).forEach(m=>{if(m.m>l)l=m.m;}));return l;}
function monthsBack(n){if(!n)return'0000-00';let[y,mo]=latestMonth().split('-').map(Number);
  mo-=n;while(mo<1){mo+=12;y--;}return `${String(y).padStart(4,'0')}-${String(mo).padStart(2,'0')}`;}
function inWin(m){return m>state._cut||(!state.win);}
function periodKey(m){if(state.gran!=='quarter')return m;
  const[y,mo]=m.split('-').map(Number);return `${y}-Q${Math.floor((mo-1)/3)+1}`;}
function srcRows(b){return state.gran==='day'
  ?((DATA.daily&&DATA.daily[b])||[]).map(r=>({m:r.d,n:r.n,avg:r.avg,stars:r.stars}))
  :(DATA.monthly[b]||[]);}
function shown(){return BANKS.filter(b=>state.active.has(b));}
function fmtMonth(m){const[y,mo]=m.split('-');const N=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return N[+mo-1]+' '+y;}
function shiftMonth(m,k){let[y,mo]=m.split('-').map(Number);mo+=k;
  while(mo<1){mo+=12;y--;}while(mo>12){mo-=12;y++;}
  return `${String(y).padStart(4,'0')}-${String(mo).padStart(2,'0')}`;}
function rangeText(){const last=latestMonth();
  if(!state.win){let f='9999-99';BANKS.forEach(b=>{const r=DATA.monthly[b];if(r&&r.length&&r[0].m<f)f=r[0].m;});
    return fmtMonth(f)+' – '+fmtMonth(last);}
  const from=shiftMonth(last,-(state.win-1));
  return state.win===1?fmtMonth(last):fmtMonth(from)+' – '+fmtMonth(last);}

/* ---------- aggregation ---------- */
function agg(b,cutLo,cutHi){ // cutLo exclusive lower bound month-key; cutHi optional exclusive upper
  cutLo=cutLo===undefined?state._cut:cutLo;
  let n=0,sw=0,stars=[0,0,0,0,0];const per={};
  srcRows(b).forEach(r=>{if(r.m<=cutLo&&cutLo!=='0000-00')return;if(cutHi&&r.m>cutHi)return;
    n+=r.n;sw+=r.avg*r.n;for(let i=0;i<5;i++)stars[i]+=r.stars[i];
    const p=periodKey(r.m);(per[p]=per[p]||{n:0,sw:0}).n+=r.n;per[p].sw+=r.avg*r.n;});
  const series=Object.keys(per).sort().map(p=>({p,n:per[p].n,avg:per[p].sw/per[p].n}));
  return{n,avg:n?sw/n:null,stars,series};}
function deltaOf(a){const s=a.series;if(s.length<2)return null;const h=Math.floor(s.length/2);
  const w=x=>{let n=0,sw=0;x.forEach(r=>{n+=r.n;sw+=r.avg*r.n;});return n?sw/n:null;};
  const A=w(s.slice(0,h)),B=w(s.slice(h));return A==null||B==null?null:B-A;}
function badSrc(b){return state.gran==='day'?((BAD.daily&&BAD.daily[b])||{}):(BAD.monthly[b]||{});}
function badAgg(b){const out={};let total=0;
  Object.entries(badSrc(b)).forEach(([m,subs])=>{if(!inWin(m))return;
    Object.entries(subs).forEach(([s,n])=>{out[s]=(out[s]||0)+n;total+=n;});});
  return{subs:out,total};}
function badPeriods(b){const pm={};
  Object.entries(badSrc(b)).forEach(([m,subs])=>{if(!inWin(m))return;const p=periodKey(m);
    pm[p]=pm[p]||{};Object.entries(subs).forEach(([s,n])=>{pm[p][s]=(pm[p][s]||0)+n;});});
  return pm;}
function allPeriods(){const s=new Set();shown().forEach(b=>srcRows(b).forEach(r=>{if(inWin(r.m))s.add(periodKey(r.m));}));
  return[...s].sort();}

/* ---------- focus painting ---------- */
function focusBank(){return state.hover||state.focus;}
function paintFocus(){
  const f=focusBank();
  ['ratingLine','volumeBar','negRateLine'].forEach(id=>{const ch=CH[id];if(!ch)return;
    ch.data.datasets.forEach(ds=>{const on=!f||ds.label===f;
      const c=ds._baseColor;if(!c)return;
      if(ds.type==='line'||ch.config.type==='line'){
        ds.borderColor=on?c:toRGBA(c,.10);ds.backgroundColor=on?c:toRGBA(c,.10);
        ds.borderWidth=on&&f?2.6:2;}
      else{ds.backgroundColor=on?toRGBA(c,.85):toRGBA(c,.12);}});
    ch.update('none');});
  document.querySelectorAll('#matrix tbody tr').forEach(tr=>{
    tr.classList.toggle('dim',!!f&&tr.dataset.bank!==f);
    tr.classList.toggle('focus',!!state.focus&&tr.dataset.bank===state.focus);});
  document.querySelectorAll('#bankChips .chip').forEach(ch=>{
    ch.classList.toggle('locked',ch.dataset.b===state.focus);});
}

/* ---------- chips ---------- */
function renderChips(){
  $('bankChips').innerHTML=BANKS.map(b=>`<span class="chip${state.active.has(b)?'':' off'}" data-b="${b}">
    <span class="dot" style="background:${COL(b)}"></span>${b}</span>`).join('');
  document.querySelectorAll('#bankChips .chip').forEach(el=>{
    const b=el.dataset.b;
    el.onclick=()=>{if(state.active.has(b)&&state.active.size>1)state.active.delete(b);
      else state.active.add(b);
      if(state.focus&&!state.active.has(state.focus))state.focus=null;
      renderChips();renderActive();};
    el.ondblclick=e=>{e.preventDefault();state.active=new Set([b]);state.focus=null;renderChips();renderActive();};
    el.onmouseenter=()=>{if(state.active.has(b)){state.hover=b;paintFocus();}};
    el.onmouseleave=()=>{state.hover=null;paintFocus();};});
}

/* ---------- charts util ---------- */
function mkChart(id,cfg){if(CH[id])CH[id].destroy();CH[id]=new Chart($(id),cfg);return CH[id];}
function gridOpts(extra){return Object.assign({responsive:true,maintainAspectRatio:false,
  interaction:{mode:'nearest',intersect:false},
  plugins:{legend:{display:false}},
  scales:{x:{grid:{display:false}},y:{grid:{color:'rgba(148,163,184,.07)'},border:{display:false}}}},extra||{});}

/* =========================================================
   TAB 1
========================================================= */
function computeInsights(){
  const out=[];const minN=state.win===1?30:80;
  // rating movers
  let best=null,worst=null;
  shown().forEach(b=>{const a=agg(b);if(a.n<minN)return;const d=deltaOf(a);if(d==null)return;
    if(!best||d>best.d)best={b,d,a};if(!worst||d<worst.d)worst={b,d,a};});
  if(best&&best.d>0.05)out.push({cls:'up',tag:'Biggest improver',
    head:`${best.b} ${signed(best.d)}★`,
    det:`Rating trending up within the window (now avg ${best.a.avg.toFixed(2)}★ on ${fmt(best.a.n)} reviews).`});
  if(worst&&worst.d<-0.05)out.push({cls:'down',tag:'Biggest decliner',
    head:`${worst.b} ${signed(worst.d)}★`,
    det:`Rating trending down within the window (now avg ${worst.a.avg.toFixed(2)}★ on ${fmt(worst.a.n)} reviews).`});
  // rising complaint (market-wide, first vs second half of window periods)
  const perSub={},periods=new Set();
  shown().forEach(b=>{Object.entries(badPeriods(b)).forEach(([p,subs])=>{periods.add(p);
    Object.entries(subs).forEach(([s,n])=>{if(s==='Uncategorized'||s==='General Dissatisfaction')return;
      (perSub[s]=perSub[s]||{})[p]=(perSub[s][p]||0)+n;});});});
  const ps=[...periods].sort();
  if(ps.length>=2){const h=Math.floor(ps.length/2),A=ps.slice(0,h),B=ps.slice(h);
    let top=null;
    Object.entries(perSub).forEach(([s,pm])=>{
      const a=A.reduce((t,p)=>t+(pm[p]||0),0),b=B.reduce((t,p)=>t+(pm[p]||0),0);
      if(a+b<40||a===0)return;const g=(b-a)/a;
      if(!top||g>top.g)top={s,g,a,b};});
    if(top&&top.g>0.25)out.push({cls:'warn',tag:'Rising complaint',
      head:`${top.s} +${Math.round(top.g*100)}%`,
      det:`Market-wide: ${fmt(top.a)} → ${fmt(top.b)} complaints between the first and second half of the window.`});}
  // worst release
  let bad=null;
  shown().forEach(b=>(DATA.versions[b]||[]).forEach(v=>{if(v.n<50)return;
    if(!bad||v.avg<bad.avg)bad={b,...v};}));
  if(bad&&bad.avg<3.2)out.push({cls:'down',tag:'Worst release',
    head:`${bad.b} v${bad.v} · ${bad.avg.toFixed(2)}★`,
    det:`Lowest-rated app version with meaningful volume (${fmt(bad.n)} reviews, all-time).`});
  return out.slice(0,4);}

function renderInsights(){
  const ins=computeInsights();
  $('insights').innerHTML=ins.length?ins.map(i=>`<div class="insight ${i.cls}">
    <div class="tag">${i.tag}</div><div class="head">${esc(i.head)}</div>
    <div class="det">${esc(i.det)}</div></div>`).join('')
    :'';
  $('insights').style.display=ins.length?'':'none';}

function renderKPIs(){
  const bs=shown();let n=0,sw=0,neg=0;const prevLo=monthsBack(state.win*2),prevHi=state._cut;
  let pn=0,psw=0,pneg=0;
  bs.forEach(b=>{const a=agg(b);n+=a.n;if(a.avg!=null)sw+=a.avg*a.n;neg+=a.stars[0]+a.stars[1];
    if(state.win){const p=agg(b,prevLo,prevHi);pn+=p.n;if(p.avg!=null)psw+=p.avg*p.n;pneg+=p.stars[0]+p.stars[1];}});
  const avg=n?sw/n:0,pavg=pn?psw/pn:null;
  const negR=n?neg/n:0,pnegR=pn?pneg/pn:null;
  let lead=null,lag=null;
  bs.forEach(b=>{const a=agg(b);if(a.n<50||a.avg==null)return;
    if(!lead||a.avg>lead.avg)lead={b,...a};if(!lag||a.avg<lag.avg)lag={b,...a};});
  const dHtml=(cur,prev,inv,fm)=>{if(prev==null||!state.win)return'<span style="color:var(--dim)">—</span>';
    const d=cur-prev,good=inv?d<0:d>0;
    return `<span class="${Math.abs(d)<1e-9?'':good?'pos':'neg'}">${d>=0?'▲':'▼'} ${fm(Math.abs(d))}</span> vs prior ${state.win}m`;};
  $('kpis').innerHTML=`
    <div class="kpi"><div class="l">Reviews in window</div><div class="v">${fmt(n)}</div>
      <div class="d">${dHtml(n,pn,false,x=>fmt(Math.round(x)))}</div></div>
    <div class="kpi"><div class="l">Market avg rating</div><div class="v">${avg.toFixed(2)}<span class="unit">★</span></div>
      <div class="d">${dHtml(avg,pavg,false,x=>x.toFixed(2)+'★')}</div></div>
    <div class="kpi"><div class="l">Negative share (1–2★)</div><div class="v">${pct(negR)}</div>
      <div class="d">${dHtml(negR,pnegR,true,x=>(x*100).toFixed(1)+'pp')}</div></div>
    <div class="kpi"><div class="l">Leader / laggard</div>
      <div class="v" style="font-size:17px;line-height:1.35">${lead?`<span class="pos">${esc(lead.b)} ${lead.avg.toFixed(2)}★</span>`:'—'}<br>
      ${lag?`<span class="neg">${esc(lag.b)} ${lag.avg.toFixed(2)}★</span>`:''}</div>
      <div class="d">min 50 reviews in window</div></div>`;}

let sortK='avg',sortDir=-1;
function renderMatrix(){
  const rows=shown().map(b=>{const a=agg(b);
    return{bank:b,avg:a.avg||0,total:a.n,
      pos:a.n?(a.stars[3]+a.stars[4])/a.n:0,neg:a.n?(a.stars[0]+a.stars[1])/a.n:0,
      delta:deltaOf(a),stars:a.stars,series:a.series};});
  rows.sort((x,y)=>{const a=x[sortK],b=y[sortK];
    return(typeof a==='string'?a.localeCompare(b):(a==null?-1:b==null?1:a-b))*sortDir;});
  const starCols=['#ef4444','#f97316','#facc15','#a3e635','#34d399'];
  $('matrix').querySelector('tbody').innerHTML=rows.map(r=>{
    const mix=r.total?r.stars.map((c,i)=>`<i style="width:${c/r.total*100}%;background:${starCols[i]}" title="${i+1}★ ${pct(c/r.total)}"></i>`).join(''):'';
    const dp=r.delta==null?'<span class="delta-pill zero">–</span>'
      :`<span class="delta-pill ${r.delta>=0.005?'pos':r.delta<=-0.005?'neg':'zero'}">${r.delta>=0.005?'▲':r.delta<=-0.005?'▼':'·'} ${signed(r.delta)}</span>`;
    return `<tr data-bank="${r.bank}">
      <td><span class="bname"><span class="dot" style="background:${COL(r.bank)}"></span>${r.bank}</span></td>
      <td class="num" style="font-weight:700">${r.avg?r.avg.toFixed(2):'—'}</td>
      <td class="num">${fmt(r.total)}</td>
      <td class="num pos">${pct(r.pos)}</td><td class="num neg">${pct(r.neg)}</td>
      <td class="num">${dp}</td>
      <td><span class="mixbar">${mix}</span></td>
      <td><canvas class="spark" width="110" height="30" data-b="${r.bank}"></canvas></td></tr>`;}).join('');
  document.querySelectorAll('#matrix tbody tr').forEach(tr=>{
    tr.onclick=()=>{state.focus=state.focus===tr.dataset.bank?null:tr.dataset.bank;paintFocus();};});
  rows.forEach(r=>{const cv=document.querySelector(`.spark[data-b="${CSS.escape(r.bank)}"]`);
    if(cv)drawSpark(cv,r.series.map(s=>s.avg),COL(r.bank));});
  document.querySelectorAll('#matrix th[data-k]').forEach(th=>{
    th.onclick=()=>{const k=th.dataset.k;if(sortK===k)sortDir*=-1;else{sortK=k;sortDir=k==='bank'?1:-1;}renderMatrix();paintFocus();};
    const base=th.textContent.replace(/[▲▼]\s*$/,'').trim();
    th.innerHTML=base+(sortK===th.dataset.k?` <span class="arrow">${sortDir<0?'▼':'▲'}</span>`:'');});}

function drawSpark(cv,vals,col){const ctx=cv.getContext('2d'),w=cv.width,h=cv.height;
  ctx.clearRect(0,0,w,h);const v=vals.filter(x=>x!=null);if(v.length<2)return;
  const mn=Math.min(...v),mx=Math.max(...v),sp=(mx-mn)||1;
  ctx.beginPath();ctx.strokeStyle=col;ctx.lineWidth=1.8;ctx.lineJoin='round';
  vals.forEach((x,i)=>{if(x==null)return;const px=i/(vals.length-1)*(w-4)+2,py=h-3-((x-mn)/sp)*(h-8);
    i===0?ctx.moveTo(px,py):ctx.lineTo(px,py);});
  ctx.stroke();}

function renderRatingLine(){
  const periods=allPeriods();
  mkChart('ratingLine',{type:'line',data:{labels:periods,
    datasets:shown().map(b=>{const m=Object.fromEntries(agg(b).series.map(s=>[s.p,s.avg]));
      return{label:b,data:periods.map(p=>m[p]??null),_baseColor:COL(b),
        borderColor:COL(b),backgroundColor:COL(b),borderWidth:2,pointRadius:0,
        pointHoverRadius:4,tension:.3,spanGaps:true};})},
    options:gridOpts({scales:{x:{grid:{display:false},ticks:{maxTicksLimit:10}},
      y:{min:1,max:5,grid:{color:'rgba(148,163,184,.07)'},border:{display:false}}},
      plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>` ${c.dataset.label}: ${c.parsed.y?.toFixed(2)}★`}}}})});}

function renderVolume(){
  const periods=allPeriods();
  mkChart('volumeBar',{type:'bar',data:{labels:periods,
    datasets:shown().map(b=>{const m=Object.fromEntries(agg(b).series.map(s=>[s.p,s.n]));
      return{label:b,data:periods.map(p=>m[p]||0),_baseColor:COL(b),
        backgroundColor:toRGBA(COL(b),.85),borderRadius:2,stack:'v'};})},
    options:gridOpts({scales:{x:{stacked:true,grid:{display:false},ticks:{maxTicksLimit:10}},
      y:{stacked:true,grid:{color:'rgba(148,163,184,.07)'},border:{display:false}}}})});}

function renderStarDist(){
  const bs=shown(),starCols=['#ef4444','#f97316','#facc15','#a3e635','#34d399'];
  const aggs=bs.map(b=>agg(b));
  mkChart('starDist',{type:'bar',data:{labels:bs,
    datasets:[0,1,2,3,4].map(i=>({label:(i+1)+'★',
      data:aggs.map(a=>a.n?a.stars[i]/a.n*100:0),
      backgroundColor:starCols[i],stack:'s',borderRadius:2}))},
    options:gridOpts({indexAxis:'y',
      scales:{x:{stacked:true,max:100,grid:{color:'rgba(148,163,184,.07)'},border:{display:false},
        ticks:{callback:v=>v+'%'}},y:{stacked:true,grid:{display:false}}},
      plugins:{legend:{display:true,position:'bottom'},
        tooltip:{callbacks:{label:c=>` ${c.dataset.label}: ${c.parsed.x.toFixed(1)}%`}}}})});}

function renderVersions(){
  const b=$('verBank').value,vs=(DATA.versions[b]||[]).slice().sort((a,c)=>verCmp(a.v,c.v));
  mkChart('verChart',{type:'bar',data:{labels:vs.map(v=>v.v),
    datasets:[{label:'Avg ★',data:vs.map(v=>v.avg),
      backgroundColor:vs.map(v=>v.avg>=4?'rgba(52,211,153,.8)':v.avg>=3?'rgba(251,191,36,.8)':'rgba(248,113,113,.85)'),
      borderRadius:4}]},
    options:gridOpts({scales:{x:{grid:{display:false}},
      y:{min:1,max:5,grid:{color:'rgba(148,163,184,.07)'},border:{display:false}}},
      plugins:{legend:{display:false},tooltip:{callbacks:{
        label:c=>` ${c.parsed.y.toFixed(2)}★ · ${fmt(vs[c.dataIndex].n)} reviews`}}}})});}
function verCmp(a,b){const pa=a.split('.').map(n=>parseInt(n)||0),pb=b.split('.').map(n=>parseInt(n)||0);
  for(let i=0;i<Math.max(pa.length,pb.length);i++){if((pa[i]||0)!==(pb[i]||0))return(pa[i]||0)-(pb[i]||0);}return 0;}

/* ---------- compare ---------- */
function renderCompare(){
  if(!state.cmp){$('cmpCard').hidden=true;return;}
  $('cmpCard').hidden=false;
  const col=(b)=>{
    const a=agg(b),bd=badAgg(b);
    const negR=a.n?(a.stars[0]+a.stars[1]+a.stars[2])/a.n:0;
    const d=deltaOf(a);
    const subs=Object.entries(bd.subs).filter(([s])=>s!=='Uncategorized'&&s!=='General Dissatisfaction')
      .sort((x,y)=>y[1]-x[1]).slice(0,5);
    const mx=subs.length?subs[0][1]:1;
    const starCols=['#ef4444','#f97316','#facc15','#a3e635','#34d399'];
    const mix=a.n?a.stars.map((c,i)=>`<i style="width:${c/a.n*100}%;background:${starCols[i]}"></i>`).join(''):'';
    return `<div class="cmpcol">
      <div class="bighead"><span class="dot" style="background:${COL(b)}"></span><b>${esc(b)}</b>
        <span style="margin-left:auto;font-size:22px;font-weight:800">${a.avg?a.avg.toFixed(2):'—'}<span style="font-size:13px;color:var(--muted)">★</span></span></div>
      <span class="mixbar" style="display:flex;margin-bottom:10px">${mix}</span>
      <div class="cmpstat"><span>Reviews (window)</span><b>${fmt(a.n)}</b></div>
      <div class="cmpstat"><span>Negative share (1–3★)</span><b class="${negR>.4?'neg':''}">${pct(negR)}</b></div>
      <div class="cmpstat"><span>Δ within window</span><b class="${d>0?'pos':d<0?'neg':''}">${d==null?'—':signed(d)+'★'}</b></div>
      <div class="cmpstat"><span>Classified complaints</span><b>${fmt(bd.total)}</b></div>
      <div class="cmpsub"><div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--dim);margin-bottom:4px">Top complaints</div>
      ${subs.map(([s,n])=>`<div class="row"><span class="nm" title="${esc(s)}">${esc(s)}</span>
        <span class="bar"><i style="width:${n/mx*100}%;background:${BAD.parent_colors[BAD.sub_parent[s]]||'#64748b'}"></i></span>
        <span class="pc">${bd.total?pct(n/bd.total,0):'0%'}</span></div>`).join('')||'<div class="empty">No complaints in window</div>'}</div>
    </div>`;};
  $('cmpGrid').innerHTML=col($('cmpA').value)+col($('cmpB').value);}

function renderTab1(){renderInsights();renderKPIs();renderMatrix();renderRatingLine();
  renderVolume();renderStarDist();renderVersions();renderCompare();paintFocus();}

/* =========================================================
   TAB 2
========================================================= */
function renderBadKPIs(){
  const bs=shown();let tot=0;const subTot={};
  bs.forEach(b=>{const a=badAgg(b);tot+=a.total;
    Object.entries(a.subs).forEach(([s,n])=>{subTot[s]=(subTot[s]||0)+n;});});
  let allN=0,allNeg=0;
  bs.forEach(b=>{const a=agg(b);allN+=a.n;allNeg+=a.stars[0]+a.stars[1]+a.stars[2];});
  const top=Object.entries(subTot).filter(([s])=>s!=='Uncategorized'&&s!=='General Dissatisfaction')
    .sort((a,b)=>b[1]-a[1])[0];
  let worst=null;
  bs.forEach(b=>{const a=agg(b);if(a.n<50)return;const r=(a.stars[0]+a.stars[1]+a.stars[2])/a.n;
    if(!worst||r>worst.r)worst={b,r};});
  // severity: financial harm share
  let fin=0,concrete=0;
  Object.entries(subTot).forEach(([s,n])=>{if(s==='Uncategorized'||s==='General Dissatisfaction')return;
    concrete+=n;if(BAD.sub_sev[s]==='Financial harm')fin+=n;});
  $('badKpis').innerHTML=`
    <div class="kpi"><div class="l">Classified complaints</div><div class="v">${fmt(tot)}</div>
      <div class="d">in window · selected banks</div></div>
    <div class="kpi"><div class="l">Negative rate (1–3★)</div><div class="v">${allN?pct(allNeg/allN):'—'}</div>
      <div class="d">${worst?`worst: <span class="neg">${esc(worst.b)} ${pct(worst.r)}</span>`:''}</div></div>
    <div class="kpi"><div class="l">Top complaint</div><div class="v" style="font-size:17px;line-height:1.3">${top?esc(top[0]):'—'}</div>
      <div class="d">${top?fmt(top[1])+' mentions · '+pct(top[1]/(tot||1)):''}</div></div>
    <div class="kpi"><div class="l">Financial-harm share</div><div class="v">${concrete?pct(fin/concrete):'—'}</div>
      <div class="d">of concrete complaints (blocked funds, fraud, fees…)</div></div>`;}

function renderNegRateBar(){
  const rows=shown().map(b=>{const a=agg(b);
    return{b,r:a.n?(a.stars[0]+a.stars[1]+a.stars[2])/a.n:0,n:a.n};})
    .filter(x=>x.n>0).sort((x,y)=>y.r-x.r);
  mkChart('negRateBar',{type:'bar',data:{labels:rows.map(r=>r.b),
    datasets:[{data:rows.map(r=>r.r*100),_baseColor:'#f87171',
      backgroundColor:rows.map(r=>toRGBA(COL(r.b),.85)),borderRadius:4}]},
    options:gridOpts({indexAxis:'y',
      scales:{x:{grid:{color:'rgba(148,163,184,.07)'},border:{display:false},ticks:{callback:v=>v+'%'}},
        y:{grid:{display:false}}},
      plugins:{legend:{display:false},tooltip:{callbacks:{
        label:c=>` ${c.parsed.x.toFixed(1)}% of ${fmt(rows[c.dataIndex].n)} reviews`}}}})});}

function renderNegRateLine(){
  const periods=allPeriods();
  mkChart('negRateLine',{type:'line',data:{labels:periods,
    datasets:shown().map(b=>{const per={};
      srcRows(b).forEach(r=>{if(!inWin(r.m))return;const p=periodKey(r.m);
        (per[p]=per[p]||{n:0,neg:0}).n+=r.n;per[p].neg+=r.stars[0]+r.stars[1]+r.stars[2];});
      return{label:b,data:periods.map(p=>per[p]&&per[p].n?per[p].neg/per[p].n*100:null),
        _baseColor:COL(b),borderColor:COL(b),backgroundColor:COL(b),
        borderWidth:2,pointRadius:0,pointHoverRadius:4,tension:.3,spanGaps:true};})},
    options:gridOpts({scales:{x:{grid:{display:false},ticks:{maxTicksLimit:10}},
      y:{grid:{color:'rgba(148,163,184,.07)'},border:{display:false},ticks:{callback:v=>v+'%'}}},
      plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>` ${c.dataset.label}: ${c.parsed.y?.toFixed(1)}%`}}}})});}

function renderMix(){
  const parent=state.mixLevel==='parent';
  $('mixParentBox').hidden=!parent;$('mixSubBox').hidden=parent;
  if(parent){
    const bs=shown(),ags=bs.map(b=>badAgg(b));
    mkChart('mixChart',{type:'bar',data:{labels:bs,
      datasets:BAD.parents.map(p=>({label:p,
        data:ags.map(a=>{let n=0;Object.entries(a.subs).forEach(([s,c])=>{if(BAD.sub_parent[s]===p)n+=c;});
          return a.total?n/a.total*100:0;}),
        backgroundColor:BAD.parent_colors[p],stack:'m',borderRadius:2}))},
      options:gridOpts({indexAxis:'y',
        scales:{x:{stacked:true,max:100,grid:{color:'rgba(148,163,184,.07)'},border:{display:false},ticks:{callback:v=>v+'%'}},
          y:{stacked:true,grid:{display:false}}},
        plugins:{legend:{display:true,position:'bottom'},
          tooltip:{callbacks:{label:c=>` ${c.dataset.label}: ${c.parsed.x.toFixed(1)}%`}}}})});
  }else{
    const bs=shown(),ags={},subs=BAD.subs_order.filter(s=>s!=='Uncategorized'&&s!=='General Dissatisfaction');
    bs.forEach(b=>ags[b]=badAgg(b));
    let mx=0;const val={};
    subs.forEach(s=>{val[s]={};bs.forEach(b=>{const share=ags[b].total?(ags[b].subs[s]||0)/ags[b].total:0;
      val[s][b]=share;if(share>mx)mx=share;});});
    $('mixSubBox').innerHTML=`<table class="heat"><thead><tr><th></th>${bs.map(b=>`<th title="${esc(b)}">${esc(b)}</th>`).join('')}</tr></thead>
      <tbody>${subs.map(s=>`<tr><td class="rowlab" title="${esc(s)}">${esc(s)}</td>${bs.map(b=>{
        const v=val[s][b],a=mx?Math.pow(v/mx,.7):0;
        return `<td style="background:rgba(99,102,241,${(a*.75).toFixed(3)})" title="${esc(b)} · ${esc(s)}: ${pct(v)} (${fmt(ags[b].subs[s]||0)})">${v?(v*100).toFixed(1):'·'}</td>`;}).join('')}</tr>`).join('')}</tbody></table>
      <div class="legendbar"><span>share of bank's complaints, %</span></div>`;}}

function renderTrend(){
  const b=$('trendBank').value;
  const banks=b==='__all'?shown():[b];
  const pm={};
  banks.forEach(bk=>Object.entries(badPeriods(bk)).forEach(([p,subs])=>{
    pm[p]=pm[p]||{};Object.entries(subs).forEach(([s,n])=>{
      const par=BAD.sub_parent[s]||'Other';pm[p][par]=(pm[p][par]||0)+n;});}));
  const periods=Object.keys(pm).sort();
  mkChart('trendChart',{type:'bar',data:{labels:periods,
    datasets:BAD.parents.map(p=>({label:p,data:periods.map(k=>pm[k][p]||0),
      backgroundColor:BAD.parent_colors[p],stack:'t',borderRadius:2}))},
    options:gridOpts({scales:{x:{stacked:true,grid:{display:false},ticks:{maxTicksLimit:10}},
      y:{stacked:true,grid:{color:'rgba(148,163,184,.07)'},border:{display:false}}},
      plugins:{legend:{display:true,position:'bottom'}}})});}

function renderSev(){
  const bs=shown(),ags=bs.map(b=>badAgg(b));
  mkChart('sevChart',{type:'bar',data:{labels:bs,
    datasets:BAD.sev_order.map(sv=>({label:sv,
      data:ags.map(a=>{let n=0,tot=0;Object.entries(a.subs).forEach(([s,c])=>{
        if(s==='Uncategorized'||s==='General Dissatisfaction')return;tot+=c;
        if(BAD.sub_sev[s]===sv)n+=c;});return tot?n/tot*100:0;}),
      backgroundColor:BAD.sev_colors[sv],stack:'sv',borderRadius:2}))},
    options:gridOpts({indexAxis:'y',
      scales:{x:{stacked:true,max:100,grid:{color:'rgba(148,163,184,.07)'},border:{display:false},ticks:{callback:v=>v+'%'}},
        y:{stacked:true,grid:{display:false}}},
      plugins:{legend:{display:true,position:'bottom'},
        tooltip:{callbacks:{label:c=>` ${c.dataset.label}: ${c.parsed.x.toFixed(1)}%`}}}})});}

function renderCooc(){
  const b=$('coocBank').value,cc=BAD.cooc[b]||{};
  const subs=BAD.concrete_subs;
  const totals=subs.map((s,i)=>cc[`${i},${i}`]||0);
  const idx=totals.map((n,i)=>({n,i})).sort((a,c)=>c.n-a.n).slice(0,12).map(x=>x.i);
  let mx=0;idx.forEach(i=>idx.forEach(j=>{if(i===j)return;
    const v=cc[`${Math.min(i,j)},${Math.max(i,j)}`]||0;if(v>mx)mx=v;}));
  const cell=(i,j)=>{if(i===j){const v=cc[`${i},${i}`]||0;
      return `<td style="background:rgba(148,163,184,.14);color:var(--muted)" title="${esc(subs[i])}: ${fmt(v)} total">${v||'·'}</td>`;}
    const v=cc[`${Math.min(i,j)},${Math.max(i,j)}`]||0,a=mx?Math.pow(v/mx,.6):0;
    return `<td style="background:rgba(34,211,238,${(a*.65).toFixed(3)})" title="${esc(subs[i])} + ${esc(subs[j])}: ${fmt(v)}">${v||'·'}</td>`;};
  $('coocWrap').innerHTML=`<table class="heat"><thead><tr><th></th>${idx.map(i=>`<th title="${esc(subs[i])}">${esc(subs[i].split(' ')[0])}</th>`).join('')}</tr></thead>
    <tbody>${idx.map(i=>`<tr><td class="rowlab" title="${esc(subs[i])}">${esc(subs[i])}</td>${idx.map(j=>cell(i,j)).join('')}</tr>`).join('')}</tbody></table>`;
  $('coocGrad').style.background='linear-gradient(90deg,rgba(34,211,238,0),rgba(34,211,238,.65))';}

function renderTab2(){renderBadKPIs();renderNegRateBar();renderNegRateLine();renderMix();renderTrend();renderSev();renderCooc();paintFocus();}

/* =========================================================
   TAB 3 : browse
========================================================= */
const EX_PAGE=30;
function exFiltered(){
  const b=$('exBank').value,cat=$('exCat').value,sub=$('exSub').value,
    q=$('exSearch').value.trim().toLowerCase(),from=$('exFrom').value,to=$('exTo').value;
  let rows=EX.filter(r=>(!b||r.b===b)&&(!state.exStar||String(r.s)===state.exStar)
    &&(!cat||r.c===cat)&&(!sub||r.sc===sub)
    &&(!from||r.d>=from)&&(!to||r.d<=to)
    &&(!q||r.t.toLowerCase().includes(q)));
  rows=rows.slice().sort(state.exSort==='thumbs'?(a,c)=>c.th-a.th||(c.d<a.d?-1:1):(a,c)=>c.d<a.d?-1:1);
  return rows;}
function renderExamples(){
  const rows=exFiltered(),show=rows.slice(0,state.exPage*EX_PAGE);
  $('exCount').textContent=`${fmt(rows.length)} reviews match · showing ${fmt(show.length)}`;
  $('exCards').innerHTML=show.map(r=>{
    const pc=BAD.parent_colors[r.c]||'#64748b';
    return `<div class="excard">
      <div class="exhead">
        <span class="exbank"><span class="dot" style="background:${COL(r.b)||'#888'}"></span>${esc(r.b)}</span>
        <span class="exstars">${'★'.repeat(r.s)}${'☆'.repeat(Math.max(0,5-r.s))}</span>
        <span class="exdate">${r.d}</span>
      </div>
      <div class="extext">${esc(r.t)}</div>
      <div class="exfoot">
        <span class="expill" style="background:${toRGBA(pc,.9)}">${esc(r.sc)}</span>
        ${(r.m||[]).filter(s=>s!==r.sc).slice(0,3).map(s=>`<span class="exchip">${esc(s)}</span>`).join('')}
        ${r.th?`<span class="exthumbs">👍 ${fmt(r.th)}</span>`:''}
      </div></div>`;}).join('')||'<div class="empty">No reviews match these filters.</div>';
  $('exMore').hidden=show.length>=rows.length;}
function fillExSub(){const cat=$('exCat').value,cur=$('exSub').value;
  const subs=BAD.subs_order.filter(s=>!cat||BAD.sub_parent[s]===cat);
  $('exSub').innerHTML='<option value="">All subcategories</option>'+subs.map(s=>`<option${s===cur?' selected':''}>${esc(s)}</option>`).join('');}

/* =========================================================
   plumbing
========================================================= */
function downloadChart(id){const ch=CH[id];if(!ch)return;
  const a=document.createElement('a');a.download=id+'.png';
  // paint bg
  const cv=ch.canvas,tmp=document.createElement('canvas');tmp.width=cv.width;tmp.height=cv.height;
  const cx=tmp.getContext('2d');cx.fillStyle='#0d1220';cx.fillRect(0,0,tmp.width,tmp.height);cx.drawImage(cv,0,0);
  a.href=tmp.toDataURL('image/png');a.click();}

function guardGran(){
  const dayBtn=document.querySelector('#granSeg button[data-g="day"]');
  const dayOK=state.win&&state.win<=6;
  dayBtn.disabled=!dayOK;
  if(!dayOK&&state.gran==='day')setGran('month');}
function setGran(g){state.gran=g;
  document.querySelectorAll('#granSeg button').forEach(x=>x.classList.toggle('active',x.dataset.g===g));}

function renderActive(){
  state._cut=monthsBack(state.win);
  $('rangeLabel').textContent=rangeText();
  if(state.tab==='1')renderTab1();else if(state.tab==='2')renderTab2();else renderExamples();}

function init(){
  $('stamp').innerHTML=`Generated ${DATA.generated_at}<br>${fmt(Object.values(META).reduce((t,m)=>t+m.total,0))} reviews · ${fmt(BAD.total)} classified`;
  $('foot').textContent=`Source: Google Play Store reviews · ${BANKS.length} Indonesian digital banks · complaints classified into ${BAD.concrete_subs.length} subcategories · generated ${DATA.generated_at}`;
  renderChips();
  // window
  document.querySelectorAll('#winSeg button').forEach(bt=>bt.onclick=()=>{
    state.win=+bt.dataset.w;
    document.querySelectorAll('#winSeg button').forEach(x=>x.classList.toggle('active',x===bt));
    guardGran();renderActive();});
  document.querySelectorAll('#granSeg button').forEach(bt=>bt.onclick=()=>{
    if(bt.disabled)return;setGran(bt.dataset.g);renderActive();});
  guardGran();
  // tabs
  document.querySelectorAll('#tabs button').forEach(bt=>bt.onclick=()=>{
    state.tab=bt.dataset.tab;
    document.querySelectorAll('#tabs button').forEach(x=>x.classList.toggle('active',x===bt));
    ['1','2','3'].forEach(t=>$('tab'+t).hidden=t!==state.tab);
    renderActive();});
  // selects
  const bankOpts=BANKS.map(b=>`<option>${esc(b)}</option>`).join('');
  $('verBank').innerHTML=bankOpts;
  $('trendBank').innerHTML=`<option value="__all">All selected banks</option>`+bankOpts;
  $('coocBank').innerHTML=bankOpts;
  $('verBank').onchange=renderVersions;$('trendBank').onchange=renderTrend;$('coocBank').onchange=renderCooc;
  // compare
  $('cmpA').innerHTML=bankOpts;$('cmpB').innerHTML=bankOpts;
  if(BANKS.length>1)$('cmpB').selectedIndex=1;
  $('cmpA').onchange=renderCompare;$('cmpB').onchange=renderCompare;
  $('cmpBtn').onclick=()=>{state.cmp=!state.cmp;$('cmpBtn').classList.toggle('active',state.cmp);
    renderCompare();if(state.cmp&&$('cmpCard').scrollIntoView)$('cmpCard').scrollIntoView({behavior:'smooth',block:'nearest'});};
  // mix level
  document.querySelectorAll('#mixLevel button').forEach(bt=>bt.onclick=()=>{
    state.mixLevel=bt.dataset.l;
    document.querySelectorAll('#mixLevel button').forEach(x=>x.classList.toggle('active',x===bt));
    renderMix();});
  // downloads
  document.querySelectorAll('.dl[data-dl]').forEach(bt=>bt.onclick=()=>downloadChart(bt.dataset.dl));
  // examples
  $('exBank').innerHTML='<option value="">All banks</option>'+bankOpts;
  $('exCat').innerHTML='<option value="">All categories</option>'+BAD.parents.map(p=>`<option>${esc(p)}</option>`).join('');
  fillExSub();
  const exRe=()=>{state.exPage=1;renderExamples();};
  $('exBank').onchange=exRe;
  $('exCat').onchange=()=>{fillExSub();exRe();};
  $('exSub').onchange=exRe;$('exFrom').onchange=exRe;$('exTo').onchange=exRe;
  let deb;$('exSearch').oninput=()=>{clearTimeout(deb);deb=setTimeout(exRe,180);};
  document.querySelectorAll('#exStarSeg button').forEach(bt=>bt.onclick=()=>{
    state.exStar=bt.dataset.s;
    document.querySelectorAll('#exStarSeg button').forEach(x=>x.classList.toggle('active',x===bt));exRe();});
  document.querySelectorAll('#exSort button').forEach(bt=>bt.onclick=()=>{
    state.exSort=bt.dataset.s;
    document.querySelectorAll('#exSort button').forEach(x=>x.classList.toggle('active',x===bt));exRe();});
  $('exMore').onclick=()=>{state.exPage++;renderExamples();};
  $('exReset').onclick=()=>{$('exBank').value='';$('exCat').value='';fillExSub();$('exSub').value='';
    $('exFrom').value='';$('exTo').value='';$('exSearch').value='';state.exStar='';state.exSort='recent';state.exPage=1;
    document.querySelectorAll('#exStarSeg button').forEach(x=>x.classList.toggle('active',!x.dataset.s));
    document.querySelectorAll('#exSort button').forEach(x=>x.classList.toggle('active',x.dataset.s==='recent'));
    renderExamples();};
  renderActive();}
init();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    build()
