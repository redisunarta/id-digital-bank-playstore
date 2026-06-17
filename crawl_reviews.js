const fs = require('fs');
const path = require('path');

const HERE = __dirname;
const RAW_DIR = path.join(HERE, '..', 'Data Raw');
const OUT_DIR = path.join(HERE, '..', 'data final');
const CRAWL_DATE = new Date();
const DATE_LABEL = formatDateLabel(CRAWL_DATE);

function formatDateLabel(d) {
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return `${d.getDate()}${months[d.getMonth()]}${String(d.getFullYear()).slice(-2)}`;
}

const BANKS = [
  { stem: 'Allo_Bank',          name: 'Allo Bank',          appId: 'com.alloapp.yump' },
  { stem: 'Bank_Jago',          name: 'Bank Jago',          appId: 'com.jago.digitalBanking' },
  { stem: 'Blu_by_BCA_Digital', name: 'Blu by BCA Digital', appId: 'com.bcadigital.blu' },
  { stem: 'Jenius',             name: 'Jenius',             appId: 'com.btpn.dc' },
  { stem: 'Neobank_BNC',        name: 'Neobank BNC',        appId: 'com.bnc.finance' },
  { stem: 'Sea_Bank',           name: 'Sea Bank',           appId: 'id.co.bankbkemobile.digitalbank' },
  { stem: 'Superbank',          name: 'Superbank',          appId: 'id.co.bankfama.android' },
  { stem: 'Krom_Bank',          name: 'Krom Bank',          appId: 'com.krom.android' },
];

const HEADER = ['reviewer_name','review_date','review_content','star_rating','review_link','reviewer_language','thumbs_up','app_version','review_id'];

function csvEscape(v) {
  if (v == null) return '';
  const s = String(v);
  if (s.includes(',') || s.includes('"') || s.includes('\n') || s.includes('\r')) {
    return '"' + s.replace(/"/g, '""') + '"';
  }
  return s;
}

function reviewsToCsv(reviews) {
  const lines = [HEADER.join(',')];
  for (const r of reviews) {
    const row = [
      csvEscape(r.userName),
      r.date || '',
      csvEscape(r.text || ''),
      r.score,
      r.url || '',
      r.userImage ? '' : '',
      r.thumbsUp || 0,
      r.version || '',
      r.id || '',
    ];
    lines.push(row.join(','));
  }
  return lines.join('\n');
}

async function getCutoffDate(stem) {
  const p = path.join(OUT_DIR, `${stem}_reviews_combined.csv`);
  if (!fs.existsSync(p)) return null;
  const data = fs.readFileSync(p, 'utf-8').trim();
  const lines = data.split('\n');
  if (lines.length < 2) return null;
  const hdr = lines[0].split(',');
  const dateIdx = hdr.indexOf('review_date');
  if (dateIdx === -1) return null;
  let maxDate = null;
  for (let i = 1; i < lines.length; i++) {
    const cols = parseCsvLine(lines[i]);
    const d = cols[dateIdx];
    if (d) {
      const dt = new Date(d);
      if (!isNaN(dt) && (maxDate === null || dt > maxDate)) maxDate = dt;
    }
  }
  return maxDate;
}

function parseCsvLine(line) {
  const result = [];
  let cur = '';
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (inQuotes) {
      if (c === '"') {
        if (i + 1 < line.length && line[i + 1] === '"') {
          cur += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        cur += c;
      }
    } else {
      if (c === '"') {
        inQuotes = true;
      } else if (c === ',') {
        result.push(cur);
        cur = '';
      } else {
        cur += c;
      }
    }
  }
  result.push(cur);
  return result;
}

async function fetchPage(gplay, appId, sort, filterScoreWith, paginationToken) {
  const opts = {
    appId,
    sort,
    num: 150,
    lang: 'id',
    country: 'id',
    paginate: true,
  };
  if (filterScoreWith !== undefined && filterScoreWith !== null) {
    opts.filterScoreWith = filterScoreWith;
  }
  if (paginationToken) opts.nextPaginationToken = paginationToken;
  return await gplay.reviews(opts);
}

async function crawlIncremental(gplay, appId, cutoffDate, bankLabel) {
  const seen = new Set();
  const allReviews = [];
  const passStats = {};
  const SORT = gplay.sort;

  // Pass A: per-star
  for (const score of [1, 2, 3, 4, 5]) {
    let token = null;
    let passCount = 0;
    while (true) {
      const result = await fetchPage(gplay, appId, SORT.NEWEST, score, token);
      let hasOld = false;
      for (const review of result.data) {
        const d = new Date(review.date);
        if (d <= cutoffDate) { hasOld = true; break; }
        if (!seen.has(review.id)) {
          seen.add(review.id);
          allReviews.push(review);
          passCount++;
        }
      }
      token = result.nextPaginationToken;
      if (!token || hasOld) break;
    }
    passStats[`star_${score}`] = passCount;
  }

  // Pass B: multi-sort
  for (const sort of [SORT.NEWEST, SORT.RATING, SORT.HELPFULNESS]) {
    let token = null;
    let passCount = 0;
    while (true) {
      const result = await fetchPage(gplay, appId, sort, null, token);
      let hasOld = false;
      for (const review of result.data) {
        const d = new Date(review.date);
        if (d <= cutoffDate) { hasOld = true; break; }
        if (!seen.has(review.id)) {
          seen.add(review.id);
          allReviews.push(review);
          passCount++;
        }
      }
      token = result.nextPaginationToken;
      if (!token || hasOld) break;
    }
    const sortName = Object.keys(SORT).find(k => SORT[k] === sort);
    passStats[`sort_${sortName}`] = passCount;
  }

  const newOnly = allReviews.filter(r => new Date(r.date) > cutoffDate);
  return { reviews: newOnly, passStats };
}

async function crawlFull(gplay, appId, bankLabel) {
  const seen = new Set();
  const allReviews = [];
  const passStats = {};
  const SORT = gplay.sort;

  // Pass A: per-star, num 10000 each
  for (const score of [1, 2, 3, 4, 5]) {
    let count = 0;
    try {
      const result = await gplay.reviews({
        appId,
        sort: SORT.NEWEST,
        num: 10000,
        filterScoreWith: score,
        lang: 'id',
        country: 'id',
      });
      for (const review of result.data) {
        if (!seen.has(review.id)) {
          seen.add(review.id);
          allReviews.push(review);
          count++;
        }
      }
    } catch (e) {
      console.error(`  [${bankLabel}] Pass A star=${score} error:`, e.message);
    }
    passStats[`star_${score}`] = count;
  }

  // Pass B: multi-sort, num 25000 each
  for (const sort of [SORT.NEWEST, SORT.RATING, SORT.HELPFULNESS]) {
    let count = 0;
    const sortName = Object.keys(SORT).find(k => SORT[k] === sort);
    try {
      const result = await gplay.reviews({
        appId,
        sort,
        num: 25000,
        lang: 'id',
        country: 'id',
      });
      for (const review of result.data) {
        if (!seen.has(review.id)) {
          seen.add(review.id);
          allReviews.push(review);
          count++;
        }
      }
    } catch (e) {
      console.error(`  [${bankLabel}] Pass B sort=${sortName} error:`, e.message);
    }
    passStats[`sort_${sortName}`] = count;
  }

  return { reviews: allReviews, passStats };
}

async function main() {
  const gplay = (await import('google-play-scraper')).default;

  fs.mkdirSync(RAW_DIR, { recursive: true });
  fs.mkdirSync(OUT_DIR, { recursive: true });

  const report = {};

  for (const bank of BANKS) {
    console.log(`\n=== ${bank.name} (${bank.stem}) ===`);
    console.log(`  App ID: ${bank.appId}`);

    const cutoff = await getCutoffDate(bank.stem);
    const isNew = cutoff === null;

    console.log(`  Cutoff: ${cutoff ? cutoff.toISOString() : 'NONE (full crawl)'}`);

    let result;
    if (isNew) {
      result = await crawlFull(gplay, bank.appId, bank.name);
    } else {
      result = await crawlIncremental(gplay, bank.appId, cutoff, bank.name);
    }

    const { reviews, passStats } = result;

    // Report pass stats
    console.log(`  Pass A (per-star):`);
    for (const s of [1,2,3,4,5]) {
      console.log(`    star ${s}: ${passStats[`star_${s}`] || 0} reviews`);
    }
    console.log(`  Pass B (multi-sort):`);
    for (const sn of ['NEWEST','RATING','HELPFULNESS']) {
      const v = passStats[`sort_${sn}`];
      if (v !== undefined) console.log(`    sort ${sn}: ${v} reviews`);
    }

    console.log(`  Total new unique reviews after filter: ${reviews.length}`);

    // Save raw batch
    const rawFile = `${bank.stem}_reviews_${DATE_LABEL}.csv`;
    const rawPath = path.join(RAW_DIR, rawFile);
    fs.writeFileSync(rawPath, reviewsToCsv(reviews), 'utf-8');
    console.log(`  Saved: Data Raw/${rawFile} (${reviews.length} rows)`);

    // Count combined file before
    const combinedPath = path.join(OUT_DIR, `${bank.stem}_reviews_combined.csv`);
    let beforeCount = 0;
    if (fs.existsSync(combinedPath)) {
      const data = fs.readFileSync(combinedPath, 'utf-8').trim();
      beforeCount = data ? data.split('\n').length - 1 : 0;
    }

    report[bank.stem] = {
      bank: bank.name,
      isNew,
      passStats,
      rawFetched: reviews.length,
      beforeCount,
    };
  }

  // Print summary report
  console.log('\n\n========================================');
  console.log('CRAWL REPORT');
  console.log('========================================');
  let totalFetched = 0;
  for (const [stem, r] of Object.entries(report)) {
    console.log(`\n${r.bank}:`);
    console.log(`  Type: ${r.isNew ? 'FULL (new bank)' : 'INCREMENTAL'}`);
    if (!r.isNew) console.log(`  Combined file before: ${r.beforeCount} reviews`);
    console.log(`  Raw batch saved: ${r.rawFetched} reviews`);
    totalFetched += r.rawFetched;
  }
  console.log(`\nTotal new reviews across all banks: ${totalFetched}`);
  console.log('\n========================================');
  console.log('Run: python3 merge_data.py  (from project root)');
}

main().catch(e => {
  console.error('Fatal error:', e);
  process.exit(1);
});
