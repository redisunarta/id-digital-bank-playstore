const fs = require('fs');
const path = require('path');

const HERE = __dirname;
const RAW_DIR = path.join(HERE, '..', 'Data Raw');
const OUT_DIR = path.join(HERE, '..', 'data final');
const CRAWL_DATE = new Date();
const DATE_LABEL = `${CRAWL_DATE.getDate()}${['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][CRAWL_DATE.getMonth()]}${String(CRAWL_DATE.getFullYear()).slice(-2)}`;

const HEADER = ['reviewer_name','review_date','review_content','star_rating','review_link','reviewer_language','thumbs_up','app_version','review_id'];

function csvEscape(v) {
  if (v == null) return '';
  const s = String(v);
  if (s.includes(',') || s.includes('"') || s.includes('\n') || s.includes('\r'))
    return '"' + s.replace(/"/g, '""') + '"';
  return s;
}

function reviewsToCsv(reviews) {
  const lines = [HEADER.join(',')];
  for (const r of reviews) {
    lines.push([csvEscape(r.userName), r.date||'', csvEscape(r.text||''), r.score, r.url||'', '',
      r.thumbsUp||0, r.version||'', r.id||''].join(','));
  }
  return lines.join('\n');
}

async function main() {
  const gplay = (await import('google-play-scraper')).default;
  const appId = 'com.krom.android';
  const seen = new Set();
  const allReviews = [];
  const SORT = gplay.sort;

  console.log('=== Krom Bank full crawl ===');

  // Pass A per-star
  for (const score of [1, 2, 3, 4, 5]) {
    console.log(`  Pass A star=${score}...`);
    let count = 0;
    try {
      const result = await gplay.reviews({ appId, sort: SORT.NEWEST, num: 10000, filterScoreWith: score, lang: 'id', country: 'id' });
      for (const r of result.data) {
        if (!seen.has(r.id)) { seen.add(r.id); allReviews.push(r); count++; }
      }
    } catch(e) { console.error(`  error star=${score}:`, e.message); }
    console.log(`    -> ${count} new`);
  }

  // Pass B multi-sort
  for (const sort of [SORT.NEWEST, SORT.RATING, SORT.HELPFULNESS]) {
    const sn = Object.keys(SORT).find(k => SORT[k] === sort);
    console.log(`  Pass B sort=${sn}...`);
    let count = 0;
    try {
      const result = await gplay.reviews({ appId, sort, num: 25000, lang: 'id', country: 'id' });
      for (const r of result.data) {
        if (!seen.has(r.id)) { seen.add(r.id); allReviews.push(r); count++; }
      }
    } catch(e) { console.error(`  error sort=${sn}:`, e.message); }
    console.log(`    -> ${count} new`);
  }

  console.log(`\nTotal unique: ${allReviews.length}`);

  // Save raw batch
  const rawFile = `Krom_Bank_reviews_${DATE_LABEL}.csv`;
  fs.writeFileSync(path.join(RAW_DIR, rawFile), reviewsToCsv(allReviews), 'utf-8');
  console.log(`Saved: Data Raw/${rawFile}`);
}

main().catch(e => { console.error(e); process.exit(1); });
