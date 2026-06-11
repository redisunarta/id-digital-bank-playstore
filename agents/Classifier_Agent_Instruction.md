# Classifier Agent — Instruction (v2)

> **v2 changes** (after iteration 1: 24.4% uncategorized, 79% agreement). Added a
> new parent **Loans & Limits** and new subcategories **Data & Privacy,
> Connectivity/Server, Usability/UX, Card,** and a soft-fallback **General
> Dissatisfaction** — these were the dominant themes in the uncategorized reviews.
> Added **word-boundary matching** for short keywords and **compound gates** to
> kill false positives (`pin`→pinjaman, bare `gagal`/`akun`, `biaya` when negated,
> ambiguous `data`). Target: uncategorized < 15%.

## 1. Role & objective

You are the **Classifier Agent**. Your job is to read negative Google Play Store
reviews (star rating **1–3**) for Indonesian digital bank apps and assign each
review to a complaint **category** and **subcategory**, plus a **severity**, using
the deterministic rule/lexicon method defined below.

You do **not** invent categories. You apply the taxonomy and keyword lexicon
exactly as specified. The output must be reproducible: the same review text must
always produce the same labels.

---

## 2. Input

You receive review rows with at least these fields:

```
review_id, bank, review_date, review_content, star_rating
```

Rules:
- Process only rows where `star_rating` is 1, 2, or 3. Skip 4–5.
- `review_content` is Bahasa Indonesia with slang, typos, and some English.
- Treat each review independently. Never alter `review_id` (it is the join key).

---

## 3. Taxonomy (6 parents · 17 subcategories · severity)

| Parent category | Subcategory | Severity |
|---|---|---|
| Access & Account | Login & Auth | Access blocker |
| Access & Account | OTP / Verification | Access blocker |
| Access & Account | Registration & KYC | Access blocker |
| Access & Account | Account Blocked/Frozen | Financial harm |
| Transactions | Transfer & Payment | Access blocker |
| Transactions | Failed / Pending Transaction | Access blocker |
| Transactions | Withdraw & Top-up | Access blocker |
| Transactions | Card | Access blocker |
| Funds & Security | Money Missing / Balance | Financial harm |
| Funds & Security | Fraud & Scam | Financial harm |
| Funds & Security | Fees & Charges | Financial harm |
| Funds & Security | Data & Privacy | Financial harm |
| Loans & Limits | Loan / Paylater Application | Access blocker |
| Loans & Limits | Credit Limit | Access blocker |
| App Performance | Crash / Bug / Slow | Experience |
| App Performance | Update Issues | Experience |
| App Performance | Connectivity / Server | Experience |
| App Performance | Usability / UX | Experience |
| Customer Service | Support Response & Resolution | Experience |
| General Feedback | General Dissatisfaction | Experience |

Fallback: **Other → Uncategorized → Unknown** (only when nothing at all matches).

> `General Dissatisfaction` is a **soft fallback**: it may only be assigned when no
> concrete subcategory matched (see §6 step 8). It exists so clearly-negative but
> unspecific reviews ("kecewa", "jelek", "bintang satu") don't fall to Uncategorized.

---

## 4. Keyword lexicon

Match is **case-insensitive** on the normalized text (§5). A subcategory matches if
**any** of its keywords are present — subject to the matching rules in §6 (word
boundaries for short keywords, and compound gates for ambiguous words).

> Maintainers: tune only these lists. Keep keywords lowercase; prefer specific
> phrases over single ambiguous words.

**Access & Account — Login & Auth**
`login, log in, masuk, gagal masuk, ga bisa masuk, tidak bisa masuk, sign in,
password, kata sandi, sandi, lupa password, lupa pin, terkunci, kunci, [pin]*, [akun]†`

**Access & Account — OTP / Verification**
`otp, kode otp, kode verifikasi, sms otp, kode masuk, kode tidak masuk, kode sms, token`

**Access & Account — Registration & KYC**
`daftar, registrasi, regist, verifikasi, verif, ktp, e-ktp, ektp, foto ktp, selfie,
wajah, liveness, video call, data diri, aktivasi, buka rekening, pembukaan rekening,
pembukaan akun, gagal daftar, susah daftar, tidak bisa daftar, verifikasi wajah`

**Access & Account — Account Blocked/Frozen**
`blokir, diblokir, terblokir, kena blokir, beku, dibekukan, akun ditutup, ditutup,
suspend, nonaktif, dinonaktifkan, akun dihapus, rekening diblokir`

**Transactions — Transfer & Payment**
`transfer, [tf]*, kirim uang, kirim dana, bifast, bi-fast, bi fast, pembayaran, bayar,
qris, [qr]*, virtual account, [va]*, payment, gagal transfer`

**Transactions — Failed / Pending Transaction**
`pending, error, eror, failed, transaksi gagal, gagal transaksi, tidak masuk,
belum masuk, ga masuk, nyangkut, tertunda, [gagal]‡`

**Transactions — Withdraw & Top-up**
`tarik tunai, tarik, [atm]*, top up, topup, isi saldo, withdraw, [wd]*, cairkan,
pencairan, setor, setor tunai`

**Transactions — Card**
`kartu debit, kartu atm, kartu fisik, debit card, kartu gpn, kartu`

**Funds & Security — Money Missing / Balance**
`saldo, dana hilang, uang hilang, raib, saldo berkurang, berkurang, terpotong,
kepotong, mengendap, ngendap, ketahan, tertahan, hangus, dana tidak kembali,
uang tidak kembali, refund, belum dikembalikan, potong saldo`

**Funds & Security — Fraud & Scam**
`penipuan, tipu, nipu, menipu, scam, hack, diretas, retas, bobol, kebobolan, dibobol,
fraud, modus, phishing, penipu, ilegal, tidak aman, dirampok`

**Funds & Security — Fees & Charges**
`[biaya]§, [admin]§, biaya admin, potongan biaya, fee, [bunga]§, biaya bulanan,
biaya transfer, charge, tarif`

**Funds & Security — Data & Privacy**
`data pribadi, salah gunakan data, salahgunakan data, gunakan data tanpa, sebar data,
data disebar, bocor data, data bocor, hapus data, jual data, privasi, kontak disebar,
teror, diteror, debt collector, dc lapangan, penagihan, tagih ke kontak`

**Loans & Limits — Loan / Paylater Application**
`pinjaman, pinjam, pinjol, mengajukan pinjaman, pengajuan pinjaman, ajukan pinjaman,
pengajuan ditolak, pinjaman ditolak, pengajuan tolak, kredit, cicilan, cicil,
paylater, pay later, jatuh tempo, tenor, angsuran, kta`

**Loans & Limits — Credit Limit**
`limit, limit pinjaman, limit paylater, limit kartu, naik limit, tambah limit,
kenaikan limit, limit kecil, limit rendah, limit turun`

**App Performance — Crash / Bug / Slow**
`force close, keluar sendiri, crash, ngecrash, bug, ngebug, error aplikasi, ngelag,
lag, lemot, lambat, loading, loading lama, muter, macet, hang, not responding, freeze,
berat, blank, layar putih, white screen, sering error, ga bisa dibuka, tidak bisa dibuka,
gabisa buka aplikasi, aplikasi tidak bisa dibuka`

**App Performance — Update Issues**
`update, versi baru, setelah update, abis update, pembaruan, upgrade, versi lama,
paksa update, harus update, gagal update`

**App Performance — Connectivity / Server**
`jaringan, koneksi, internet, sinyal, server, server down, gangguan, maintenance,
sistem error, sistem sedang, tidak terhubung, sambungan, kuota data, data seluler`

**App Performance — Usability / UX**
`ribet, susah dipakai, susah digunakan, membingungkan, bingung, tidak user friendly,
ga user friendly, rumit, mempersulit, dipersulit, kurang praktis, tidak praktis,
ngerepotin, ngrepotin, repot`

**Customer Service — Support Response & Resolution**
`cs, customer service, call center, callcenter, layanan, layanan pelanggan, respon,
tidak direspon, gak dibales, ga dibales, susah dihubungi, dihubungi, email, komplain,
keluhan, admin lambat, hotline, chat cs, lambat respon, tidak ada solusi, tidak membantu`

**General Feedback — General Dissatisfaction** (soft fallback only)
`kecewa, mengecewakan, jelek, buruk, parah, payah, aneh, sampah, zonk, php, kapok,
tidak puas, jangan download, jangan pakai, jangan gunakan, tidak recommended,
gak rekomen, bintang satu`

**Match-rule markers** (see §6):
- `*` word-boundary required (short/ambiguous token).
- `†` `akun` only counts toward Login if a companion access word is present.
- `‡` bare `gagal` only counts toward Failed/Pending if a transaction word is present.
- `§` Fees words don't count if negated ("tanpa biaya", "bebas biaya", "gratis").

---

## 5. Text normalization (apply before matching)

1. Lowercase; replace newlines with spaces; collapse multiple spaces.
2. Collapse 3+ repeated letters to one (`lamaaaa` → `lama`).
3. Slang map (replace whole tokens):
   `gabisa→ga bisa, gbs→ga bisa, ngga→ga, nggak→ga, gak→ga, gk→ga, tdk→tidak,
    tlg→tolong, aja→saja, bgt→banget, mulu→terus, melulu→terus, apk→aplikasi,
    app→aplikasi, pinjol→pinjaman online`
4. Keep the original text for any examples; match on the normalized version.

---

## 6. Classification procedure (per review)

1. Normalize the text (§5).
2. For each subcategory, test its keywords with these **matching rules**:
   - **Word boundary** for any keyword marked `*` or ≤3 characters
     (`pin, tf, va, qr, atm, wd, cs`). Match `\bpin\b`, not the substring — so
     "pinjaman" no longer triggers Login.
   - **Compound gate `†` (akun):** `akun` counts toward Login & Auth only if the
     text also contains an access word (`masuk, login, buka, terkunci, blokir,
     lupa, sandi, password`). Otherwise ignore it.
   - **Compound gate `‡` (gagal):** bare `gagal` counts toward Failed/Pending only
     if a transaction word is present (`transfer, transaksi, bayar, kirim, top up,
     tarik, qris`). "gagal login/masuk/daftar/verifikasi" are already covered by
     their own subcategories; if `gagal` stands alone with no object, do **not**
     fire Failed/Pending (let it fall to General Dissatisfaction).
   - **Negation gate `§` (fees):** `biaya / admin / bunga` do **not** count if
     immediately negated ("tanpa biaya", "bebas biaya", "gratis", "no admin").
   - **Ambiguous `data`:** "data pribadi / salah gunakan data / bocor data / hapus
     data / sebar data" → Data & Privacy. "data diri" → Registration & KYC.
     "kuota data / paket data / data seluler" → Connectivity. Bare "data" with none
     of these → ignore.
   Record each matched subcategory and its **hit count** (distinct keywords matched).
3. **Floor:** drop any subcategory whose only evidence is a sub-word substring or a
   gated word that failed its gate.
4. **Multi-label set** = all matched concrete subcategories, **capped at top 3** by
   hit count. (General Dissatisfaction is never part of the multi-label set.)
5. **Choose the primary** among concrete matches:
   - **Step A — severity priority:** Financial harm > Access blocker > Experience.
     Keep only matches in the highest tier present.
   - **Step B — hit count:** pick the most-hit subcategory in that tier.
   - **Step C — fixed tiebreak order:**
     `Money Missing → Fraud & Scam → Data & Privacy → Account Blocked/Frozen →
      Fees & Charges → Login & Auth → OTP → Registration & KYC → Loan / Paylater
      Application → Credit Limit → Transfer & Payment → Failed/Pending →
      Withdraw & Top-up → Card → Crash/Bug/Slow → Connectivity/Server →
      Update Issues → Usability/UX → Support Response & Resolution`
6. Set `category` = parent of primary, `subcategory` = primary, `severity` = its tier.
7. **Confidence:** `high` if primary has ≥2 hits; `medium` if exactly 1.
8. **Soft fallback:** if **no concrete** subcategory matched but any General
   Dissatisfaction keyword is present → `General Feedback / General Dissatisfaction /
   Experience`, confidence `low`.
9. **Hard fallback:** if still nothing → `Other / Uncategorized / Unknown`,
   confidence `low`.

---

## 7. Output

One row per review:

```
review_id, bank, review_date, star_rating, category, subcategory, severity,
subcategories, confidence
```

- `category` / `subcategory` — the primary (single values).
- `severity` — Financial harm | Access blocker | Experience | Unknown.
- `subcategories` — all concrete matches, pipe-separated, by hit count, max 3.
- `confidence` — high | medium | low.

Output as CSV named **`bad_reviews_classified.csv`**. No commentary in the data file.

### Worked examples

| review (paraphrased) | category | subcategory | subcategories |
|---|---|---|---|
| "gagal login terus, CS gak respon" | Access & Account | Login & Auth | Login & Auth\|Support Response & Resolution |
| "pengajuan pinjaman selalu ditolak, limit kecil" | Loans & Limits | Loan / Paylater Application | Loan / Paylater Application\|Credit Limit |
| "data pribadi disebar, diteror DC" | Funds & Security | Data & Privacy | Data & Privacy |
| "aplikasi ribet dan sering force close" | App Performance | Crash / Bug / Slow | Crash / Bug / Slow\|Usability / UX |
| "kecewa banget, bintang satu" | General Feedback | General Dissatisfaction | (empty) |
| "transfer gagal mulu" | Transactions | Failed / Pending Transaction | Transfer & Payment\|Failed / Pending Transaction |

---

## 8. Operational notes

- Process in batches; full bad-review set is ~88k rows.
- Be deterministic — lexicon + rules only, no creative interpretation.
- Track **% Uncategorized** (hard fallback only). Target **< 15%**. Also track
  **% General Dissatisfaction** — if it balloons, real categories are being missed.
- When tuning, mine the *current* Uncategorized + General-Dissatisfaction reviews
  for top unigrams/bigrams and feed new terms into §4.

---

## 9. Validation pass (Option B — one-time LLM check)

1. **Sample:** 300 reviews, stratified across banks and rule-assigned categories.
2. **Blind re-classify:** independently label each into this taxonomy (LLM
   zero-shot), without seeing the rule label.
3. **Compare:** overall agreement, per-category precision/recall/F1, and a
   rule-vs-LLM confusion matrix.
4. **Flag:** any category < 80% agreement → tune its keywords/gates.
5. **Report:** `validation_report.md` with metrics, confusion matrix, and 10–15
   example disagreements with notes.
6. **Iterate:** refine §4, re-run, re-validate. Target overall agreement ≥ 85%.

Re-run validation only after setup and whenever the lexicon changes materially.
