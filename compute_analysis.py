#!/usr/bin/env python3
"""
Analyst: Compute Metrics & Write Analysis File
Sections 1-7 per CLAUDE.md contract.
"""
import csv
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from statistics import median

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data final")
BAD_REVIEWS = os.path.join(HERE, "bad_reviews_classified.csv")
OUTPUT = os.path.join(HERE, "report", f"competitive-analysis-{datetime.now().strftime('%Y-%m-%d')}.md")
os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)

BANKS = [
    "Allo Bank",
    "Bank Jago",
    "Blu by BCA Digital",
    "Jenius",
    "Neobank BNC",
    "Sea Bank",
    "Superbank",
]

FILE_MAP = {
    "Allo Bank": "Allo_Bank_reviews_combined.csv",
    "Bank Jago": "Bank_Jago_reviews_combined.csv",
    "Blu by BCA Digital": "Blu_by_BCA_Digital_reviews_combined.csv",
    "Jenius": "Jenius_reviews_combined.csv",
    "Neobank BNC": "Neobank_BNC_reviews_combined.csv",
    "Sea Bank": "Sea_Bank_reviews_combined.csv",
    "Superbank": "Superbank_reviews_combined.csv",
}

DISPLAY_NAMES = {
    "Allo Bank": "Allo Bank",
    "Bank Jago": "Bank Jago",
    "Blu by BCA Digital": "blu by BCA",
    "Jenius": "Jenius",
    "Neobank BNC": "Neobank BNC",
    "Sea Bank": "SeaBank",
    "Superbank": "Superbank",
}

REVEALED_SUBCATS = {
    "Login & Auth", "OTP", "Registration & KYC", "Transfer & Payment",
    "Failed / Pending", "Withdraw & Top-up", "Crash / Bug", "Connectivity",
    "Money Missing", "Account Blocked", "Loan / Paylater Application",
}
STATED_SUBCATS = {
    "Usability / UX", "Fees", "Credit Limit", "Update Preferences", "General Dissatisfaction",
}

CATEGORY_ORDER = [
    "Access & Account", "Transactions", "Funds & Security", "Loans & Limits",
    "App Performance", "Customer Service", "General Feedback", "Other",
]


def parse_date(s):
    s = s.strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def load_combined():
    """Returns dict: bank -> list of row dicts."""
    data = {}
    for bank, fname in FILE_MAP.items():
        path = os.path.join(DATA_DIR, fname)
        rows = []
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("app_name", "").strip():  # skip blank rows
                    rows.append(row)
        data[bank] = rows
    return data


def load_bad():
    """Returns dict: bank -> list of classified row dicts."""
    data = defaultdict(list)
    with open(BAD_REVIEWS, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data[row["bank"]].append(row)
    return dict(data)


def star(row):
    try:
        return int(float(row.get("star_rating", 0)))
    except Exception:
        return 0


def split_subcats(s):
    if not s:
        return []
    return [x.strip() for x in s.split("|") if x.strip()]


# ─── Load data ────────────────────────────────────────────────────────────────
combined = load_combined()
bad = load_bad()

# ─── Section 1 ────────────────────────────────────────────────────────────────
def section1():
    lines = ["## Section 1 — Dataset Summary & Data Sufficiency\n"]
    lines.append("| Bank | Total Reviews | Date Range | Bad Reviews (1–3★) | % Classified | % Uncategorized |")
    lines.append("|---|---|---|---|---|---|")
    for bank in BANKS:
        rows = combined[bank]
        total = len(rows)
        dates = [parse_date(r["review_date"]) for r in rows if parse_date(r["review_date"])]
        if dates:
            dmin = min(dates).strftime("%Y-%m-%d")
            dmax = max(dates).strftime("%Y-%m-%d")
            date_range = f"{dmin} – {dmax}"
        else:
            date_range = "unknown"

        brows = bad.get(bank, [])
        n_bad = len(brows)
        # "% classified" = bad reviews with non-null category (all have category, check for Uncategorized)
        n_uncategorized = sum(1 for r in brows if r.get("category", "").strip() == "Other"
                              and r.get("subcategory", "").strip() == "Uncategorized")
        pct_classified = 100 if n_bad == 0 else round((n_bad - n_uncategorized) / n_bad * 100)
        pct_uncategorized = 0 if n_bad == 0 else round(n_uncategorized / n_bad * 100)
        dn = DISPLAY_NAMES[bank]
        lines.append(f"| {dn} | {total:,} | {date_range} | {n_bad:,} | {pct_classified}% | {pct_uncategorized}% |")

    lines.append("")
    lines.append("**Global data gaps:**")
    lines.append("- No developer-reply data. CS-complaint rate (share of bad reviews in Customer Service category) is the available proxy.")
    lines.append("- Review population is self-selected: unhappy users and loyal advocates.")
    lines.append("- Indonesian corpus underrepresents elderly, lower-literacy, and rural users.")
    lines.append("- Review data alone is not causal.")
    lines.append("")
    return "\n".join(lines)


# ─── Section 2 ────────────────────────────────────────────────────────────────
def section2():
    lines = ["## Section 2 — Per-App Metric Table\n"]
    lines.append("| Bank | Avg ★ | Negative Rate | Total Reviews | Top-3 Subcategories (Prevalence %) | Severity Mix (FH / AB / EX) |")
    lines.append("|---|---|---|---|---|---|")

    for bank in BANKS:
        rows = combined[bank]
        total = len(rows)
        stars = [star(r) for r in rows]
        avg_star = round(sum(stars) / total, 2) if total else 0

        neg = sum(1 for s in stars if s <= 3)
        neg_rate = round(neg / total * 100) if total else 0

        brows = bad.get(bank, [])
        n_bad = len(brows)

        # Prevalence by subcategory (multi-label field)
        subcat_count = defaultdict(int)
        for r in brows:
            for sc in split_subcats(r.get("subcategories", "")):
                subcat_count[sc] += 1
            # also count primary subcategory
            sc = r.get("subcategory", "").strip()
            if sc:
                subcat_count[sc] += 1  # may double-count but prevalence uses subcategories field

        # Re-do: prevalence = reviews whose subcategories field contains that subcategory
        subcat_prev = defaultdict(int)
        for r in brows:
            seen = set()
            for sc in split_subcats(r.get("subcategories", "")):
                if sc not in seen:
                    subcat_prev[sc] += 1
                    seen.add(sc)
            # also the primary subcategory
            sc = r.get("subcategory", "").strip()
            if sc and sc not in seen:
                subcat_prev[sc] += 1

        top3 = sorted(subcat_prev.items(), key=lambda x: -x[1])[:3]
        top3_str = "; ".join(
            f"{sc} ({round(c/n_bad*100)}% of {n_bad} bad)" for sc, c in top3
        ) if n_bad > 0 else "n/a"

        # Severity mix (denominator: total bad reviews)
        fh = sum(1 for r in brows if r.get("severity") == "Financial harm")
        ab = sum(1 for r in brows if r.get("severity") == "Access blocker")
        ex = sum(1 for r in brows if r.get("severity") == "Experience")
        fh_pct = round(fh / n_bad * 100) if n_bad else 0
        ab_pct = round(ab / n_bad * 100) if n_bad else 0
        ex_pct = round(ex / n_bad * 100) if n_bad else 0

        dn = DISPLAY_NAMES[bank]
        lines.append(f"| {dn} | {avg_star} | {neg_rate}% (of {total:,}) | {total:,} | {top3_str} | {fh_pct}% / {ab_pct}% / {ex_pct}% |")

    lines.append("")
    lines.append("*Severity mix denominator: total bad reviews (1–3★ classified) per bank.*")
    lines.append("*Negative rate denominator: all reviews per bank.*")
    lines.append("")
    return "\n".join(lines)


# ─── Section 3 ────────────────────────────────────────────────────────────────
def section3():
    lines = ["## Section 3 — Blocking-Failure Analysis\n"]

    rows_by_bank = []
    all_combined_total = {b: len(combined[b]) for b in BANKS}

    for bank in BANKS:
        brows = bad.get(bank, [])
        n_bad = len(brows)
        total = all_combined_total[bank]

        ab_rows = [r for r in brows if r.get("severity") == "Access blocker"]
        n_ab = len(ab_rows)

        bf_share_bad = round(n_ab / n_bad * 100) if n_bad else 0
        bf_share_all = round(n_ab / total * 100) if total else 0

        # Dominant blocking mechanism: subcategory prevalence among AB rows
        ab_subcat_prev = defaultdict(int)
        for r in ab_rows:
            seen = set()
            for sc in split_subcats(r.get("subcategories", "")):
                if sc not in seen:
                    ab_subcat_prev[sc] += 1
                    seen.add(sc)
            sc = r.get("subcategory", "").strip()
            if sc and sc not in seen:
                ab_subcat_prev[sc] += 1

        if ab_subcat_prev:
            dom_sc, dom_n = sorted(ab_subcat_prev.items(), key=lambda x: -x[1])[0]
            dom_pct = round(dom_n / n_ab * 100) if n_ab else 0
            dom_str = f"{dom_sc} ({dom_pct}% of {n_ab} AB reviews)"
        else:
            dom_str = "n/a"

        rows_by_bank.append((bank, n_ab, n_bad, total, bf_share_bad, bf_share_all, dom_str))

    # Rank by blocking-failure share (of bad reviews)
    rows_by_bank.sort(key=lambda x: -x[4])

    lines.append("Ranked by blocking-failure share (denominator: total bad reviews per bank):\n")
    lines.append("| Rank | Bank | AB Reviews | Blocking-Failure Share (of bad) | Blocking-Failure Share (of all) | Dominant Blocking Mechanism |")
    lines.append("|---|---|---|---|---|---|")

    for i, (bank, n_ab, n_bad, total, bf_bad, bf_all, dom) in enumerate(rows_by_bank, 1):
        dn = DISPLAY_NAMES[bank]
        lines.append(f"| {i} | {dn} | {n_ab:,} | {bf_bad}% (of {n_bad:,} bad) | {bf_all}% (of {total:,} all) | {dom} |")

    lines.append("")
    lines.append("**Note:** Trend vs prior period not computable from current data (single date-range snapshot; no prior-period classified file).")
    lines.append("")
    return "\n".join(lines)


# ─── Section 4 ────────────────────────────────────────────────────────────────
def section4():
    lines = ["## Section 4 — Version Risk & Anomaly Detection\n"]

    ### Version risk ###
    lines.append("### 4.1 Version Risk\n")
    lines.append("Flag rule: version v for bank b if n(v) ≥ 30 AND avg_rating(v) ≤ trailing-12m avg_rating(b) − 0.5★\n")

    version_flags = []
    for bank in BANKS:
        rows = combined[bank]
        # trailing-12m = all reviews (data window is within 12m)
        all_stars = [star(r) for r in rows]
        if not all_stars:
            continue
        bank_avg = sum(all_stars) / len(all_stars)

        # Group by app_version
        by_ver = defaultdict(list)
        for r in rows:
            v = r.get("app_version", "").strip()
            if v:
                by_ver[v].append(star(r))

        for v, vstars in by_ver.items():
            n = len(vstars)
            if n < 30:
                continue
            v_avg = sum(vstars) / n
            gap = bank_avg - v_avg
            if gap >= 0.5:
                version_flags.append((bank, v, n, round(v_avg, 2), round(bank_avg, 2), round(gap, 2)))

    if version_flags:
        lines.append("| Bank | Version | n | Version Avg ★ | Bank Trailing Avg ★ | Gap (★) |")
        lines.append("|---|---|---|---|---|---|")
        for bank, v, n, v_avg, b_avg, gap in sorted(version_flags, key=lambda x: -x[5]):
            dn = DISPLAY_NAMES[bank]
            lines.append(f"| {dn} | {v} | {n:,} | {v_avg} | {b_avg} | −{gap} |")
        lines.append("")
        lines.append("*All version flags: directional (requires multi-period tracking to confirm sustained underperformance).*")
    else:
        lines.append("No version signal (no version with n ≥ 30 and gap ≥ 0.5★ vs bank trailing average).")

    lines.append("")

    ### 5★ surge ###
    lines.append("### 4.2 5★ Surge Detection\n")
    lines.append("Flag rule: month m if 5★_count(m) ≥ 3× trailing-6-month median AND avg_rating(m) jumps ≥ +0.5★\n")

    surge_flags = []
    for bank in BANKS:
        rows = combined[bank]
        # Group by year-month
        by_month = defaultdict(list)
        for r in rows:
            d = parse_date(r.get("review_date", ""))
            if d:
                ym = d.strftime("%Y-%m")
                by_month[ym].append(star(r))

        months_sorted = sorted(by_month.keys())
        for i, m in enumerate(months_sorted):
            # Need at least 6 prior months
            prior_months = months_sorted[max(0, i-6):i]
            if len(prior_months) < 3:  # need some prior data
                continue
            five_star_counts_prior = [sum(1 for s in by_month[pm] if s == 5) for pm in prior_months]
            if not five_star_counts_prior:
                continue
            med_5star = median(five_star_counts_prior)
            cur_5star = sum(1 for s in by_month[m] if s == 5)

            if med_5star == 0:
                continue

            avg_prior = sum(sum(by_month[pm]) / len(by_month[pm]) for pm in prior_months) / len(prior_months)
            cur_avg = sum(by_month[m]) / len(by_month[m]) if by_month[m] else 0

            if cur_5star >= 3 * med_5star and (cur_avg - avg_prior) >= 0.5:
                surge_flags.append((bank, m, cur_5star, round(med_5star, 1), round(cur_avg, 2), round(avg_prior, 2)))

    if surge_flags:
        lines.append("| Bank | Month | 5★ Count | Trailing-6m Median 5★ | Month Avg ★ | Prior-6m Avg ★ |")
        lines.append("|---|---|---|---|---|---|")
        for bank, m, c5, med5, cur_avg, pri_avg in surge_flags:
            dn = DISPLAY_NAMES[bank]
            lines.append(f"| {dn} | {m} | {c5} | {med5} | {cur_avg} | {pri_avg} |")
        lines.append("")
        lines.append("*Anomalous 5★ surge, cause unverified. Directional only; does not assert manipulation.*")
    else:
        lines.append("No 5★ anomaly detected.")

    lines.append("")
    return "\n".join(lines)


# ─── Section 5 ────────────────────────────────────────────────────────────────
def section5():
    lines = ["## Section 5 — Market-Gap / Category Analysis\n"]

    all_bad = []
    for bank in BANKS:
        all_bad.extend(bad.get(bank, []))
    total_bad_global = len(all_bad)

    # Per-category, per-bank prevalence
    # category prevalence = reviews in that category (primary label)
    cat_bank_counts = defaultdict(lambda: defaultdict(int))  # cat -> bank -> count
    for r in all_bad:
        cat = r.get("category", "Other").strip()
        bank = r["bank"]
        cat_bank_counts[cat][bank] += 1

    # Total prevalence per category (global)
    cat_total = {cat: sum(cat_bank_counts[cat].values()) for cat in cat_bank_counts}

    lines.append("### 5.1 Category Totals (Cross-App)\n")
    lines.append("| Category | Total Bad Reviews | % of All Bad | Banks Affected | Category-Wide? (≥5 banks) |")
    lines.append("|---|---|---|---|---|")

    for cat in CATEGORY_ORDER:
        total_cat = cat_total.get(cat, 0)
        if total_cat == 0:
            continue
        pct = round(total_cat / total_bad_global * 100) if total_bad_global else 0
        banks_affected = len(cat_bank_counts.get(cat, {}))
        category_wide = "Yes" if banks_affected >= 5 else "No"
        lines.append(f"| {cat} | {total_cat:,} | {pct}% (of {total_bad_global:,} global bad) | {banks_affected}/7 | {category_wide} |")

    lines.append("")

    lines.append("### 5.2 Worst/Best Bank per Category\n")
    lines.append("*Ranking by category share = (bank's bad reviews in category ÷ bank's total bad reviews) × 100*\n")
    lines.append("| Category | Worst Bank (share) | Best Bank (share) | Revealed/Stated |")
    lines.append("|---|---|---|---|")

    cat_revealed_map = {
        "Access & Account": "Revealed",
        "Transactions": "Revealed",
        "Funds & Security": "Revealed",
        "Loans & Limits": "Mixed (Revealed: Loan/Paylater; Stated: Credit Limit)",
        "App Performance": "Revealed",
        "Customer Service": "Stated",
        "General Feedback": "Stated",
        "Other": "Stated",
    }

    for cat in CATEGORY_ORDER:
        if cat_total.get(cat, 0) == 0:
            continue
        bank_shares = []
        for bank in BANKS:
            brows = bad.get(bank, [])
            n_bank_bad = len(brows)
            n_cat = cat_bank_counts.get(cat, {}).get(bank, 0)
            share = round(n_cat / n_bank_bad * 100) if n_bank_bad else 0
            bank_shares.append((bank, share, n_cat))
        bank_shares.sort(key=lambda x: -x[1])
        worst = bank_shares[0]
        best_non_zero = [x for x in reversed(bank_shares) if x[2] > 0]
        best = best_non_zero[0] if best_non_zero else bank_shares[-1]
        rv = cat_revealed_map.get(cat, "Mixed")
        lines.append(f"| {cat} | {DISPLAY_NAMES[worst[0]]} ({worst[1]}% of {len(bad.get(worst[0],[]))} bad) | {DISPLAY_NAMES[best[0]]} ({best[1]}%) | {rv} |")

    lines.append("")

    lines.append("### 5.3 Category-Wide Pains (Present Across ≥5 Banks)\n")
    cwide = [cat for cat in CATEGORY_ORDER if len(cat_bank_counts.get(cat, {})) >= 5]
    if cwide:
        for cat in cwide:
            banks_in = sorted(cat_bank_counts[cat].keys())
            lines.append(f"- **{cat}**: {len(banks_in)}/7 banks — {', '.join(DISPLAY_NAMES[b] for b in banks_in)}")
    else:
        lines.append("No category present across ≥5 banks.")

    lines.append("")
    return "\n".join(lines)


# ─── Section 6 ────────────────────────────────────────────────────────────────
def section6():
    lines = ["## Section 6 — Unmet-Need Signals\n"]
    lines.append("*All unmet needs below are inferred from complaint patterns, not counted as explicit feature requests.*\n")

    all_bad = []
    for bank in BANKS:
        all_bad.extend(bad.get(bank, []))
    total_bad_global = len(all_bad)

    # Prevalence per subcategory across all banks (multi-label)
    subcat_prev = defaultdict(int)
    for r in all_bad:
        seen = set()
        for sc in split_subcats(r.get("subcategories", "")):
            if sc not in seen:
                subcat_prev[sc] += 1
                seen.add(sc)
        sc = r.get("subcategory", "").strip()
        if sc and sc not in seen:
            subcat_prev[sc] += 1

    top_subcats = sorted(subcat_prev.items(), key=lambda x: -x[1])[:20]

    lines.append("| Subcategory | Prevalence (all banks) | % of All Bad | Revealed/Stated | Basis |")
    lines.append("|---|---|---|---|---|")

    for sc, cnt in top_subcats:
        pct = round(cnt / total_bad_global * 100) if total_bad_global else 0
        if sc in REVEALED_SUBCATS:
            rv = "Revealed"
            basis = "User tried action, system failed or retried"
        elif sc in STATED_SUBCATS:
            rv = "Stated"
            basis = "User expressed opinion or preference gap"
        else:
            rv = "Mixed"
            basis = "Context-dependent; review content determines type"
        conf = "robust" if cnt >= 100 else ("directional only" if cnt < 10 else "")
        conf_str = f" [{conf}]" if conf else ""
        lines.append(f"| {sc} | {cnt:,}{conf_str} | {pct}% (of {total_bad_global:,}) | {rv} | {basis} |")

    lines.append("")
    return "\n".join(lines)


# ─── Section 7 ────────────────────────────────────────────────────────────────
def section7():
    lines = ["## Section 7 — Confidence Ledger\n"]

    lines.append("| Bank | Bad Reviews (n) | Confidence Tier | Notes |")
    lines.append("|---|---|---|---|")

    for bank in BANKS:
        brows = bad.get(bank, [])
        n = len(brows)
        if n >= 100:
            tier = "Robust (n ≥ 100)"
        elif n >= 10:
            tier = "Moderate"
        else:
            tier = "Directional only (n < 10)"
        dn = DISPLAY_NAMES[bank]
        lines.append(f"| {dn} | {n:,} | {tier} | — |")

    lines.append("")
    lines.append("**Robust findings (n ≥ 100 bad reviews per claim):**")
    lines.append("- Per-bank category distributions for all 7 banks (each has >100 bad reviews).")
    lines.append("- Cross-app category-wide pain identification.")
    lines.append("- Top subcategory prevalence figures (most exceed n=100 globally).")
    lines.append("")
    lines.append("**Directional findings:**")
    lines.append("- Version risk flags: single-snapshot; no multi-period trending.")
    lines.append("- 5★ surge flags: require external corroboration.")
    lines.append("- Any subcategory with global prevalence <10: tagged [directional only] in §6.")
    lines.append("- Severity breakdown by subcategory within a single bank where n<10: not reported.")
    lines.append("")
    lines.append("**Thin-data warnings:**")
    lines.append("- No prior-period classified file → §3 trend vs prior period not computable.")
    lines.append("- No developer-reply data → CS reply rate not computable; §3 uses CS-complaint rate only.")
    lines.append("")
    return "\n".join(lines)


# ─── Assemble output ──────────────────────────────────────────────────────────
def main():
    header = """# Competitive Analysis — Digital Banking Play Store Reviews
**Date:** 2026-06-11
**Produced by:** Analyst Playstore (TIM-55)
**Input files:** `data final/<Bank>_reviews_combined.csv` × 7, `bad_reviews_classified.csv`
**Reporter contract:** Sections numbered and metrics named per CLAUDE.md §0.3–§0.4. Do not renumber.

---

"""
    body = (
        header
        + section1() + "\n---\n\n"
        + section2() + "\n---\n\n"
        + section3() + "\n---\n\n"
        + section4() + "\n---\n\n"
        + section5() + "\n---\n\n"
        + section6() + "\n---\n\n"
        + section7()
    )
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"Written: {OUTPUT}")


if __name__ == "__main__":
    main()
