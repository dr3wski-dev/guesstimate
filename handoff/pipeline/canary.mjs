/* Is statmap.app actually working right now?
 *
 * WHY THIS EXISTS
 * Everything else in this repo checks the game at the moment somebody changes it.
 * Nothing checked it at 3am on a Tuesday when nobody had touched it for a week. The
 * failures that matter most are the quiet ones: an expired route, an edge serving a
 * stale day, a deploy that reported success and released nothing. None of those
 * announce themselves, and the first report would otherwise come from a player who
 * has already decided the game is broken.
 *
 * WHAT IT ASSERTS, AND WHY EACH ONE
 *   1. The page loads at all.                 The site being down is the loud case.
 *   2. The API answers with five questions.   Four or six means selection is broken.
 *   3. Every question is well-formed.         A missing axis renders an empty chart.
 *   4. The date served is today in ET.        Catches a frozen edge cache.
 *   5. x-build matches this checkout.         Catches the silent one: a deploy that
 *                                             succeeded, released nothing, and left
 *                                             the previous pool in place. Everything
 *                                             above passes while it serves last
 *                                             month's questions.
 *
 * Check 5 only means something when run against main, since that is the pool that is
 * supposed to be live. Run from a branch it will report a mismatch that is not a
 * fault, so it downgrades to a warning unless CANARY_STRICT is set.
 *
 *   node pipeline/canary.mjs                        # against production
 *   API=http://localhost:8903 node pipeline/canary.mjs
 */
import { fingerprint } from './build_fingerprint.mjs';

const BASE = (process.env.API || 'https://statmap.app').replace(/\/$/, '');
const STRICT = process.env.CANARY_STRICT === '1';

let failures = 0, warnings = 0;
const check = (name, ok, detail = '') => {
  if (!ok) failures++;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  — ${detail}` : ''}`);
};
const warn = (name, ok, detail = '') => {
  if (!ok) warnings++;
  console.log(`${ok ? 'PASS' : 'WARN'}  ${name}${detail ? `  — ${detail}` : ''}`);
};

// One retry on a network blip. A canary that pages on a single dropped packet gets
// muted, and a muted canary is worse than none — it is a monitoring system everyone
// has learned to ignore.
async function get(path) {
  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      return await fetch(BASE + path, { cache: 'no-store' });
    } catch (err) {
      if (attempt === 2) throw err;
      await new Promise(r => setTimeout(r, 5000));
    }
  }
}

console.log(`=== CANARY  ${BASE}  ${new Date().toISOString()} ===\n`);

// 1. The page
let page;
try {
  page = await get('/');
  check('the site responds', page.ok, `HTTP ${page.status}`);
  const html = await page.text();
  check('the page is the game', /id="app"/.test(html) && /STATMAP/i.test(html),
    `${html.length} bytes`);
} catch (err) {
  check('the site responds', false, err.message);
}

// 2-5. The API
try {
  const res = await get('/api/daily');
  check('the API responds', res.ok, `HTTP ${res.status}`);

  const build = res.headers.get('x-build');
  const data = await res.json();

  check('five questions', Array.isArray(data.questions) && data.questions.length === 5,
    `got ${data.questions?.length}`);

  const bad = (data.questions || []).filter(q =>
    !q.xLabel || !q.yLabel || !q.targetPlayer
    || !Array.isArray(q.xDomain) || q.xDomain.length !== 2
    || !Array.isArray(q.yDomain) || q.yDomain.length !== 2
    || typeof q.targetX !== 'number' || typeof q.targetY !== 'number'
    || !Array.isArray(q.referencePlayers) || q.referencePlayers.length < 2);
  check('every question is well-formed', bad.length === 0,
    bad.length ? bad.map(q => q.id).join(', ') : `${data.questions?.length} checked`);

  // The Worker decides the date in America/New_York. If the edge freezes, this is
  // the first thing that goes wrong and the last thing anyone notices.
  const et = new Date().toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
  check('serving today in ET', data.date === et, `API says ${data.date}, ET is ${et}`);

  check('puzzle number is present', Number.isInteger(data.puzzleNumber),
    `#${data.puzzleNumber}`);

  const want = fingerprint();
  const matches = build === want;
  (STRICT ? check : warn)('live pool matches this checkout', matches,
    matches ? build : `live ${build ?? '(header missing)'}, checkout ${want}`);
} catch (err) {
  check('the API responds', false, err.message);
}

console.log();
if (failures) {
  console.error(`${failures} CHECK(S) FAILED — statmap.app is not healthy`);
  process.exit(1);
}
if (warnings) console.log(`${warnings} warning(s), no failures`);
console.log('statmap.app is healthy');
