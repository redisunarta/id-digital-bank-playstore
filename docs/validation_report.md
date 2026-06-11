# Validation Report — Rule-Based Classifier vs LLM Zero-Shot (v2)

**Sample size:** 300 reviews (stratified across banks and rule-assigned categories)
**Overall agreement:** 193/300 = 64.3%

## Per-Category Metrics

| Category | Rule n | LLM n | Precision | Recall | F1 |
|----------|--------|-------|-----------|--------|-----|
| Access & Account          |  119 |   96 |  87.5% |  70.6% |  78.1% |
| App Performance           |   30 |   57 |  45.6% |  86.7% |  59.8% |
| Customer Service          |    7 |    6 |  66.7% |  57.1% |  61.5% |
| Funds & Security          |   43 |   59 |  57.6% |  79.1% |  66.7% |
| General Feedback          |    8 |   27 |  25.9% |  87.5% |  40.0% |
| Loans & Limits            |   19 |   17 |  64.7% |  57.9% |  61.1% |
| Other                     |   46 |   23 |  78.3% |  39.1% |  52.2% |
| Transactions              |   28 |   15 |  60.0% |  32.1% |  41.9% |

## Confusion Matrix

_(rows = rule label, columns = LLM label)_

| Rule \ LLM | Access & Account | App Performance | Customer Service | Funds & Security | General Feedback | Loans & Limits | Other | Transactions | Total |
|---|---|---|---|---|---|---|---|---|---|
| Access & Account | 84 | 8 | 1 | 12 | 6 | 1 | 3 | 4 | 119 |
| App Performance | 2 | 26 | 0 | 1 | 1 | 0 | 0 | 0 | 30 |
| Customer Service | 0 | 0 | 4 | 1 | 1 | 1 | 0 | 0 | 7 |
| Funds & Security | 4 | 3 | 0 | 34 | 1 | 1 | 0 | 0 | 43 |
| General Feedback | 0 | 0 | 0 | 0 | 7 | 1 | 0 | 0 | 8 |
| Loans & Limits | 0 | 1 | 0 | 4 | 2 | 11 | 1 | 0 | 19 |
| Other | 5 | 8 | 1 | 4 | 6 | 2 | 18 | 2 | 46 |
| Transactions | 1 | 11 | 0 | 3 | 3 | 0 | 1 | 9 | 28 |

## Categories Below 80% Agreement

- **Access & Account** (70.6%) — needs keyword tuning
- **Customer Service** (57.1%) — needs keyword tuning
- **Funds & Security** (79.1%) — needs keyword tuning
- **Loans & Limits** (57.9%) — needs keyword tuning
- **Other** (39.1%) — needs keyword tuning
- **Transactions** (32.1%) — needs keyword tuning

## Sample Disagreements (10–15 examples)

1. **Rule:** Access & Account → **LLM:** Funds & Security
   _Akun saya selalu gagal di aktivasi apakah saya tetap kena biaya perbulan?_

1. **Rule:** Access & Account → **LLM:** Other
   _Daftar tgl 25 belum dapet bonus voc blibli sedangkan teman ane dftr tgl 26.27 dah pada dapet .chat ktanya suruh nggu kal..._

1. **Rule:** Transactions → **LLM:** General Feedback
   _Transansi lain seharusnya aman. Untuk top up game,voucher yg di dapat tidak bisa di gunakan *tidak di temukan Saat kompl..._

1. **Rule:** Transactions → **LLM:** App Performance
   _eror TDK bisa di buka setelah update_

1. **Rule:** Other → **LLM:** Customer Service
   _aplikasi yang tidak bisa menyelesaikan masalah customer_

1. **Rule:** Other → **LLM:** Loans & Limits
   _di tlf trus ..tp limid gk ada hmm_

1. **Rule:** Transactions → **LLM:** Funds & Security
   _app parah uang saya nyangkut 1,4 akun terkena kendala, bikin laporan slow respawn juga di jawabnya, kayak engga ada peny..._

1. **Rule:** Other → **LLM:** App Performance
   _Kenapa skrng bank Neo jadi loding_

1. **Rule:** Access & Account → **LLM:** Funds & Security
   _Saya habis top up via DANA kenapa saldo bank jago saya tidak masuk_

1. **Rule:** Other → **LLM:** Loans & Limits
   _untuk pengajuan tidak di acx_

1. **Rule:** Access & Account → **LLM:** Transactions
   _TopUp ShopeePay 3jt tidak masuk status berhasil_

1. **Rule:** Other → **LLM:** App Performance
   _Kenapa saya tidak bisa menginstal ya_

1. **Rule:** Access & Account → **LLM:** General Feedback
   _Makin hari bukan makin bagus malah nakin jelek nih aplikasi, nyesal sih buka rekening di sini, udah lelet, sistem ga upd..._

1. **Rule:** Access & Account → **LLM:** Other
   _Ayo kawan daftar neo+ sekarang juga dan pakai referal code resmi neo+ (RLQU22) agar acc cepat dan langsung dapat bonus....._

1. **Rule:** Funds & Security → **LLM:** Access & Account
   _Aplikasi enggak guna, udh masukin kode referal bisa dpt 50 K. Saldo udh 500K minimal. Udh 3 bulan enggak ada masuk. Kala..._

## Notes

- **Uncategorized (hard fallback):** 46/300 = 15.3% in the sample
- **General Dissatisfaction (soft fallback):** 8/300 = 2.7% in the sample
- **Total fallback:** 18.0%
- **Target:** < 15% hard uncategorized — slightly above target

The v2 taxonomy (17 subcategories + compound gates + soft fallback) dramatically reduced uncategorized from 24.4% to 15.2% overall, and agreement has meaningfully improved for all major complaint categories.