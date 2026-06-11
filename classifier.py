"""
Deterministic classifier for Indonesian digital bank reviews (v2).
Follows the full taxonomy & rules in AGENTS.md — 17 subcategories,
compound gates, soft fallback.
"""

import csv
import os
import re
from collections import defaultdict

# ── Taxonomy (§3) ─────────────────────────────────────────────────────────
SUBCATEGORIES = [
    ("Access & Account", "Login & Auth", "Access blocker"),
    ("Access & Account", "OTP / Verification", "Access blocker"),
    ("Access & Account", "Registration & KYC", "Access blocker"),
    ("Access & Account", "Account Blocked/Frozen", "Financial harm"),
    ("Transactions", "Transfer & Payment", "Access blocker"),
    ("Transactions", "Failed / Pending Transaction", "Access blocker"),
    ("Transactions", "Withdraw & Top-up", "Access blocker"),
    ("Transactions", "Card", "Access blocker"),
    ("Funds & Security", "Money Missing / Balance", "Financial harm"),
    ("Funds & Security", "Fraud & Scam", "Financial harm"),
    ("Funds & Security", "Fees & Charges", "Financial harm"),
    ("Funds & Security", "Data & Privacy", "Financial harm"),
    ("Loans & Limits", "Loan / Paylater Application", "Access blocker"),
    ("Loans & Limits", "Credit Limit", "Access blocker"),
    ("App Performance", "Crash / Bug / Slow", "Experience"),
    ("App Performance", "Update Issues", "Experience"),
    ("App Performance", "Connectivity / Server", "Experience"),
    ("App Performance", "Usability / UX", "Experience"),
    ("Customer Service", "Support Response & Resolution", "Experience"),
]

# ── Keyword lexicon (§4) ──────────────────────────────────────────────────
KEYWORDS = {
    "Login & Auth": [
        "login", "log in", "masuk", "gagal masuk", "ga bisa masuk",
        "tidak bisa masuk", "sign in", "password", "kata sandi", "sandi",
        "lupa password", "lupa pin", "terkunci", "kunci",
    ],
    "OTP / Verification": [
        "otp", "kode otp", "kode verifikasi", "sms otp", "kode masuk",
        "kode tidak masuk", "kode sms", "token",
    ],
    "Registration & KYC": [
        "daftar", "registrasi", "regist", "verifikasi", "verif", "ktp",
        "e-ktp", "ektp", "foto ktp", "selfie", "wajah", "liveness",
        "video call", "data diri", "aktivasi", "buka rekening",
        "pembukaan rekening", "pembukaan akun", "gagal daftar",
        "susah daftar", "tidak bisa daftar", "verifikasi wajah",
    ],
    "Account Blocked/Frozen": [
        "blokir", "diblokir", "terblokir", "kena blokir", "beku",
        "dibekukan", "akun ditutup", "ditutup", "suspend", "nonaktif",
        "dinonaktifkan", "akun dihapus", "rekening diblokir",
    ],
    "Transfer & Payment": [
        "transfer", "kirim uang", "kirim dana", "bifast", "bi-fast",
        "bi fast", "pembayaran", "bayar", "qris", "virtual account",
        "payment", "gagal transfer",
    ],
    "Failed / Pending Transaction": [
        "pending", "error", "eror", "failed", "transaksi gagal",
        "gagal transaksi", "tidak masuk", "belum masuk", "ga masuk",
        "nyangkut", "tertunda",
    ],
    "Withdraw & Top-up": [
        "tarik tunai", "tarik", "atm", "top up", "topup", "isi saldo",
        "withdraw", "cairkan", "pencairan", "setor", "setor tunai",
    ],
    "Card": [
        "kartu debit", "kartu atm", "kartu fisik", "debit card",
        "kartu gpn", "kartu",
    ],
    "Money Missing / Balance": [
        "saldo", "dana hilang", "uang hilang", "raib",
        "saldo berkurang", "berkurang", "terpotong", "kepotong",
        "mengendap", "ngendap", "ketahan", "tertahan", "hangus",
        "dana tidak kembali", "uang tidak kembali", "refund",
        "belum dikembalikan", "potong saldo",
    ],
    "Fraud & Scam": [
        "penipuan", "tipu", "nipu", "menipu", "scam", "hack",
        "diretas", "retas", "bobol", "kebobolan", "dibobol", "fraud",
        "modus", "phishing", "penipu", "ilegal", "tidak aman", "dirampok",
    ],
    "Fees & Charges": [
        "biaya admin", "potongan biaya", "fee", "biaya bulanan",
        "biaya transfer", "charge", "tarif", "potong biaya",
    ],
    "Data & Privacy": [
        "data pribadi", "salah gunakan data", "salahgunakan data",
        "gunakan data tanpa", "sebar data", "data disebar",
        "bocor data", "data bocor", "hapus data", "jual data",
        "privasi", "kontak disebar", "teror", "diteror",
        "debt collector", "dc lapangan", "penagihan", "tagih ke kontak",
    ],
    "Loan / Paylater Application": [
        "pinjaman", "pinjam", "pinjol", "mengajukan pinjaman",
        "pengajuan pinjaman", "ajukan pinjaman", "pengajuan ditolak",
        "pinjaman ditolak", "pengajuan tolak", "kredit", "cicilan",
        "cicil", "paylater", "pay later", "jatuh tempo", "tenor",
        "angsuran", "kta",
    ],
    "Credit Limit": [
        "limit", "limit pinjaman", "limit paylater", "limit kartu",
        "naik limit", "tambah limit", "kenaikan limit", "limit kecil",
        "limit rendah", "limit turun",
    ],
    "Crash / Bug / Slow": [
        "force close", "keluar sendiri", "crash", "ngecrash", "bug",
        "ngebug", "error aplikasi", "ngelag", "lag", "lemot",
        "lambat", "loading", "loading lama", "muter", "macet", "hang",
        "not responding", "freeze", "berat", "blank", "layar putih",
        "white screen", "sering error", "ga bisa dibuka",
        "tidak bisa dibuka", "gabisa buka aplikasi",
        "aplikasi tidak bisa dibuka",
    ],
    "Update Issues": [
        "update", "versi baru", "setelah update", "abis update",
        "pembaruan", "upgrade", "versi lama", "paksa update",
        "harus update", "gagal update",
    ],
    "Connectivity / Server": [
        "jaringan", "koneksi", "internet", "sinyal", "server",
        "server down", "gangguan", "maintenance", "sistem error",
        "sistem sedang", "tidak terhubung", "sambungan", "kuota data",
        "data seluler",
    ],
    "Usability / UX": [
        "ribet", "susah dipakai", "susah digunakan", "membingungkan",
        "bingung", "tidak user friendly", "ga user friendly", "rumit",
        "mempersulit", "dipersulit", "kurang praktis", "tidak praktis",
        "ngerepotin", "ngrepotin", "repot",
    ],
    "Support Response & Resolution": [
        "cs", "customer service", "call center", "callcenter",
        "layanan", "layanan pelanggan", "respon", "tidak direspon",
        "gak dibales", "ga dibales", "susah dihubungi", "dihubungi",
        "email", "komplain", "keluhan", "admin lambat", "hotline",
        "chat cs", "lambat respon", "tidak ada solusi", "tidak membantu",
    ],
    "General Dissatisfaction": [
        "kecewa", "mengecewakan", "jelek", "buruk", "parah", "payah",
        "aneh", "sampah", "zonk", "php", "kapok", "tidak puas",
        "jangan download", "jangan pakai", "jangan gunakan",
        "tidak recommended", "gak rekomen", "bintang satu",
    ],
}

# ── Gate helpers ──────────────────────────────────────────────────────────

# Short tokens that require word boundary match (§6 step 2)
WORD_BOUNDARY_TOKENS = {"pin", "tf", "va", "qr", "atm", "wd", "cs", "akun"}

# Compound gate for `akun` (§6 step 2 — †)
AKUN_COMPANION = {"masuk", "login", "buka", "terkunci", "blokir", "lupa", "sandi", "password"}

# Compound gate for bare `gagal` (§6 step 2 — ‡)
GAGAL_TRANSACTION_WORDS = {"transfer", "transaksi", "bayar", "kirim", "top up", "topup", "tarik", "qris"}

# Negation gate for fees (§6 step 2 — §)
FEE_NEGATIONS = ["tanpa biaya", "bebas biaya", "gratis", "no admin"]

# Data disambiguation (§6 step 2)
DATA_PRIVACY_PATTERNS = [
    "data pribadi", "salah gunakan data", "salahgunakan data",
    "gunakan data tanpa", "sebar data", "data disebar",
    "bocor data", "data bocor", "hapus data", "jual data", "privasi",
    "kontak disebar", "teror", "diteror",
    "debt collector", "dc lapangan", "penagihan", "tagih ke kontak",
]
DATA_DIRI = ["data diri"]
DATA_CONNECTIVITY = ["kuota data", "paket data", "data seluler"]

# ── Slang map (§5 step 3) ─────────────────────────────────────────────────
SLANG_MAP = {
    "gabisa": "ga bisa",
    "gbs": "ga bisa",
    "ngga": "ga",
    "nggak": "ga",
    "gak": "ga",
    "gk": "ga",
    "tdk": "tidak",
    "tlg": "tolong",
    "dr": "dari",
    "dgn": "dengan",
    "aja": "saja",
    "bgt": "banget",
    "mulu": "terus",
    "melulu": "terus",
    "apk": "aplikasi",
    "app": "aplikasi",
    "pinjol": "pinjaman online",
}

# ── Tiebreak order (§6 Step C) ──────────────────────────────────────────
TIEBREAK_ORDER = [
    "Money Missing / Balance", "Fraud & Scam", "Data & Privacy",
    "Account Blocked/Frozen", "Fees & Charges", "Login & Auth",
    "OTP / Verification", "Registration & KYC",
    "Loan / Paylater Application", "Credit Limit",
    "Transfer & Payment", "Failed / Pending Transaction",
    "Withdraw & Top-up", "Card", "Crash / Bug / Slow",
    "Connectivity / Server", "Update Issues", "Usability / UX",
    "Support Response & Resolution",
]
TIEBREAK_IDX = {s: i for i, s in enumerate(TIEBREAK_ORDER)}

SEVERITY_RANK = {"Financial harm": 0, "Access blocker": 1, "Experience": 2}


def normalize(text: str) -> str:
    t = text.lower()
    t = t.replace("\n", " ")
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"(.)\1{2,}", r"\1", t)
    tokens = t.split()
    mapped = [SLANG_MAP.get(tok, tok) for tok in tokens]
    return " ".join(mapped)


def sub_word_boundary(norm_text: str, kw: str) -> bool:
    return kw in norm_text.split()


def sub_substring(norm_text: str, kw: str) -> bool:
    return kw in norm_text


def has_fee_negation(norm_text: str) -> bool:
    for phrase in FEE_NEGATIONS:
        if phrase in norm_text:
            return True
    return False


def classify(norm_text: str):
    """
    §6 classification.
    Returns (category, subcategory, severity, matched_list, confidence).
    """
    tokens_set = set(norm_text.split())
    matched = []

    for parent, sub, sev in SUBCATEGORIES:
        keywords = KEYWORDS.get(sub, [])
        hits = 0

        for kw in keywords:
            # Word boundary for short/ambiguous tokens
            if kw in WORD_BOUNDARY_TOKENS or kw in ("biaya", "admin", "bunga"):
                if not sub_word_boundary(norm_text, kw):
                    continue
            elif kw in ("pin", "tf", "va", "qr", "atm", "wd", "cs", "akun"):
                if not sub_word_boundary(norm_text, kw):
                    continue
            else:
                if not sub_substring(norm_text, kw):
                    continue

            # Compound gate: akun requires companion access word
            if kw == "akun" and sub == "Login & Auth":
                if not tokens_set & AKUN_COMPANION:
                    continue

            # Compound gate: gagal requires transaction word
            if kw == "gagal" and sub == "Failed / Pending Transaction":
                if not (tokens_set & GAGAL_TRANSACTION_WORDS):
                    continue
                # Also skip if preceded by login/masuk/daftar (already handled)
                for prefix in ["gagal login", "gagal masuk", "gagal daftar", "gagal verifikasi"]:
                    if prefix in norm_text:
                        break
                else:
                    # Check if bare gagal with a transaction word
                    has_gagal = "gagal" in norm_text.split()
                    has_txn_word = bool(tokens_set & GAGAL_TRANSACTION_WORDS)
                    if has_gagal and not has_txn_word:
                        continue

            # Negation gate for fees
            if sub == "Fees & Charges" and kw in ("biaya", "admin", "bunga"):
                if has_fee_negation(norm_text):
                    continue

            hits += 1

        # Handle ambiguous data subcategory
        if sub == "Data & Privacy":
            data_hits = 0
            for dkw in DATA_PRIVACY_PATTERNS:
                if dkw in norm_text:
                    data_hits += 1
            if data_hits == 0:
                hits = 0

        if hits > 0:
            matched.append((sub, parent, sev, hits))

    # Check for matched concrete subcategories
    concrete = [m for m in matched if m[0] != "General Dissatisfaction"]

    if not concrete:
        # Soft fallback: check General Dissatisfaction
        gd_keywords = KEYWORDS.get("General Dissatisfaction", [])
        gd_hits = 0
        for kw in gd_keywords:
            if kw in norm_text:
                gd_hits += 1
        if gd_hits > 0:
            return ("General Feedback", "General Dissatisfaction", "Experience", [], "low")

        # Hard fallback
        return ("Other", "Uncategorized", "Unknown", [], "low")

    # Sort by hit count desc, cap at top 3
    concrete.sort(key=lambda x: -x[3])
    concrete = concrete[:3]

    # Step A: severity priority
    best_sev = min(SEVERITY_RANK.get(m[2], 99) for m in concrete)
    candidates = [m for m in concrete if SEVERITY_RANK.get(m[2], 99) == best_sev]

    # Step B: hit count
    max_hits = max(m[3] for m in candidates)
    candidates = [m for m in candidates if m[3] == max_hits]

    # Step C: tiebreak
    candidates.sort(key=lambda m: TIEBREAK_IDX.get(m[0], 99))
    primary = candidates[0]

    sub, parent, sev, hits = primary

    if hits >= 2:
        conf = "high"
    else:
        conf = "medium"

    sub_list = [m[0] for m in concrete]

    return (parent, sub, sev, sub_list, conf)


def derive_bank(filename: str) -> str:
    base = os.path.basename(filename)
    base = re.sub(r"_reviews.*", "", base)
    return base.replace("_", " ")


def main():
    base_dir = "/Users/redisunarta/Documents/Digital Bank Review/data final"
    input_files = [
        "Allo_Bank_reviews_combined.csv",
        "Bank_Jago_reviews_combined.csv",
        "Blu_by_BCA_Digital_reviews_combined.csv",
        "Jenius_reviews_combined.csv",
        "Neobank_BNC_reviews_combined.csv",
        "Sea_Bank_reviews_combined.csv",
        "Superbank_reviews_combined.csv",
    ]

    out_path = "/Users/redisunarta/Documents/Digital Bank Review/bad_reviews_classified.csv"
    total_rows = 0
    bad_rows = 0

    with open(out_path, "w", newline="") as out:
        writer = csv.writer(out)
        writer.writerow([
            "review_id", "bank", "review_date", "star_rating", "review_content",
            "category", "subcategory", "severity",
            "subcategories", "confidence",
        ])

        for fname in input_files:
            fpath = os.path.join(base_dir, fname)
            fsize = os.path.getsize(fpath)
            print(f"Processing {fname} ({fsize:,} bytes)...")

            default_bank = derive_bank(fname)

            with open(fpath, "rb") as raw:
                content = raw.read().replace(b"\x00", b"")

            decoded = content.decode("utf-8", errors="replace")
            lines = decoded.splitlines()

            reader = csv.DictReader(lines)
            file_bad = 0
            file_total = 0

            for row in reader:
                file_total += 1
                try:
                    star = int(row.get("star_rating", "0").strip())
                except (ValueError, KeyError):
                    continue
                if star > 3:
                    continue

                file_bad += 1
                bank = row.get("app_name", "").strip() or default_bank
                review_id = row.get("review_id", "").strip()
                review_date = row.get("review_date", "").strip()
                content_text = row.get("review_content", "").strip()

                norm = normalize(content_text)
                category, subcategory, severity, sub_list, confidence = classify(norm)

                sub_str = "|".join(sub_list) if sub_list else ""

                writer.writerow([
                    review_id, bank, review_date, star, content_text,
                    category, subcategory, severity,
                    sub_str, confidence,
                ])

            total_rows += file_total
            bad_rows += file_bad
            print(f"  {fname}: {file_total} total, {file_bad} bad reviews")

    print(f"\nDone. {total_rows} total rows, {bad_rows} bad reviews classified.")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
