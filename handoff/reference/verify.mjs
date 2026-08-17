/* Regression suite for the StatMap reference implementation — drives the real page in a browser
   and asserts the fixes from USER_EXPERIENCE_REVIEW.md stay fixed.

   This is a development tool, NOT a runtime dependency: the game itself is still
   vanilla JS/SVG with nothing to install, per ACTION_PLAN.md §3. Playwright is only
   needed to run this file.

     python3 pipeline/build_site.py --url https://example.com
     node pipeline/devserver.mjs 8901 &
     node reference/verify.mjs

   Exits non-zero if any check fails. */
import { chromium, devices } from 'playwright';
// Point at the dev server (handoff/pipeline/devserver.mjs), which serves the built
// site AND /api/daily from the same selection module the deployed Worker uses.
//   node handoff/pipeline/devserver.mjs 8901
const BASE = process.env.BASE || 'http://localhost:8903/';
const log = (...a) => console.log(...a);
const browser = await chromium.launch();
let fails = 0;
const check = (name, ok, detail = '') => { log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`); if (!ok) fails++; };

// ================= 1. PRACTICE MODE GONE =================
log('\n=== 1. PRACTICE MODE REMOVED ===');
const c1 = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const d1 = await c1.newPage();
const errs = [];
d1.on('pageerror', e => errs.push(e.message));
/* Console errors count, but only the game's own. Once an analytics provider is
   installed the page loads a script from a vendor CDN, and any environment that
   cannot reach it — a sandbox, an offline laptop, an ad blocker — produced a
   "Failed to load resource" error that failed this suite for a reason that has
   nothing to do with the game. Judged by origin: anything served from somewhere
   other than the page's own host is somebody else's outage. */
d1.on('console', m => {
  if (m.type() !== 'error') return;
  const from = (m.location() && m.location().url) || '';
  const ownOrigin = new URL(BASE).origin;
  if (from && !from.startsWith(ownOrigin)) return;
  errs.push(m.text());
});
await d1.goto(BASE); await d1.waitForSelector('#startBtn');
check('no Practice button on start screen', await d1.locator('#practiceBtn').count() === 0);
check('no practice symbols in JS', await d1.evaluate(() => typeof startPractice === 'undefined'));
check('no page errors', errs.length === 0, errs[0] || '');

// ================= 2. iPHONE =================
log('\n=== 2. iPHONE (390x664) ===');
const c2 = await browser.newContext({ ...devices['iPhone 13'] });
const p = await c2.newPage();
const perrs = [];
p.on('pageerror', e => perrs.push(e.message));
await p.goto(BASE); await p.waitForSelector('#startBtn');
await p.click('#startBtn'); await p.waitForSelector('#chartSvg');
const vh = p.viewportSize().height;
const g1 = await p.evaluate(() => {
  const r = s => { const e = document.querySelector(s); const b = e.getBoundingClientRect(); return { t: Math.round(b.top), b: Math.round(b.bottom), l: Math.round(b.left), rr: Math.round(b.right) }; };
  return { chart: r('.chart-frame'), submit: r('#submitBtn'), topRight: r('#topRight'), controls: r('.controls') };
});
check('submit button visible without scrolling', g1.submit.b <= vh, `bottom ${g1.submit.b} vs viewport ${vh}`);
const ov = !(g1.topRight.rr < g1.controls.l || g1.controls.rr < g1.topRight.l || g1.topRight.b < g1.controls.t || g1.controls.b < g1.topRight.t);
check('controls no longer overlap the round counter', !ov);
check('chart starts higher up the page', g1.chart.t < 296, `chart top ${g1.chart.t} (was 296)`);
await p.screenshot({ path: 'v-phone-question.png' });

const cb = await p.locator('.chart-frame').boundingBox();
await p.touchscreen.tap(cb.x + cb.width * 0.55, cb.y + cb.height * 0.45);
await p.waitForTimeout(150);
await p.click('#submitBtn');
await p.waitForSelector('.reveal');
await p.waitForTimeout(700);
const g2 = await p.evaluate(() => {
  const r = s => { const e = document.querySelector(s); const b = e.getBoundingClientRect(); return { t: Math.round(b.top), b: Math.round(b.bottom) }; };
  return { reveal: r('.reveal'), pts: r('.pts'), fact: r('.fact'), submit: r('#submitBtn'), heat: !!document.querySelector('.heat') };
});
check('score is on-screen after submit', g2.pts.t >= 0 && g2.pts.b <= vh, `pts at ${g2.pts.t}-${g2.pts.b}, viewport ${vh}`);
check('next button still on-screen after submit', g2.submit.b <= vh + 1, `bottom ${g2.submit.b}`);
check('heat bands drawn on the chart', g2.heat);
check('no phone JS errors', perrs.length === 0, perrs[0] || '');
await p.screenshot({ path: 'v-phone-reveal.png' });

// ================= 3. STREAK CLOCK =================
log('\n=== 3. STREAK CLOCK (ET everywhere) ===');
const sim = await p.evaluate(() => {
  localStorage.clear();
  const out = [];
  // 9pm ET Mon Aug 10 == 2026-08-11T01:00Z. Puzzle date is 2026-08-10 in both cases now.
  let s = registerCompletion([50, 50, 50, 50, 50], '2026-08-10');
  out.push(`Mon 9pm ET (puzzle 2026-08-10): lastPlayed=${s.lastPlayed} streak=${s.currentStreak} days=${s.daysPlayed}`);
  s = registerCompletion([60, 60, 60, 60, 60], '2026-08-11');
  out.push(`Tue 10am ET (puzzle 2026-08-11): lastPlayed=${s.lastPlayed} streak=${s.currentStreak} days=${s.daysPlayed}`);
  s = registerCompletion([70, 70, 70, 70, 70], '2026-08-12');
  out.push(`Wed 10am ET (puzzle 2026-08-12): lastPlayed=${s.lastPlayed} streak=${s.currentStreak} days=${s.daysPlayed}`);
  const dup = registerCompletion([99, 99, 99, 99, 99], '2026-08-12');
  out.push(`replay of Wed:                   streak=${dup.currentStreak} days=${dup.daysPlayed} (must be unchanged)`);
  return { out, final: JSON.parse(localStorage.getItem('statmap_stats_v1')) };
});
sim.out.forEach(l => log('    ' + l));
check('evening play no longer eats the next day', sim.final.currentStreak === 3 && sim.final.daysPlayed === 3, `streak ${sim.final.currentStreak}, days ${sim.final.daysPlayed}`);

const stale = await p.evaluate(() => {
  localStorage.setItem('statmap_stats_v1', JSON.stringify({ lastPlayed: '2026-01-15', currentStreak: 7, bestStreak: 12, daysPlayed: 20, totalPoints: 6000, bestRound: 410, tiers: {} }));
  const s = loadStats();
  return { stored: s.currentStreak, live: liveStreak(s, TODAY), yesterdayCase: liveStreak({ lastPlayed: prevDateString(TODAY), currentStreak: 4 }, TODAY) };
});
check('lapsed streak reads 0, not the stored value', stale.live === 0, `stored ${stale.stored} -> shown ${stale.live}`);
check('yesterday still counts as live', stale.yesterdayCase === 4);

// v1 migration
const mig = await p.evaluate(() => {
  localStorage.clear();
  localStorage.setItem('guesstimate_stats_v1', JSON.stringify({ lastPlayed: '2026-08-06', currentStreak: 5, bestStreak: 9, daysPlayed: 12, totalPoints: 4000, bestRound: 420, tiers: { Ballpark: 30 } }));
  const s = loadStats();
  return { streak: s.currentStreak, best: s.bestStreak, pts: s.totalPoints, tiers: Object.keys(s.tiers).length };
});
check('v1 migration keeps streaks, drops old-scale scores', mig.streak === 5 && mig.best === 9 && mig.pts === 0 && mig.tiers === 0, JSON.stringify(mig));
await c2.close();

// ================= 4. CHALLENGE ESCAPE =================
log('\n=== 4. CHALLENGE LINK NO LONGER A ONE-WAY DOOR ===');
const c4 = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
const d4 = await c4.newPage();
/* A challenge date is only honoured if it is on or after BAG_EPOCH, and a challenge
   FOR TODAY is deliberately not challenge mode at all — it is today's puzzle, so it
   counts toward the streak and there is nothing to escape to (statmap.html, the
   MODE assignment in init()).

   Both together mean this whole section is unexercisable on launch day: there is no
   earlier puzzle to link to. Rather than retarget it at today and let five
   assertions pass trivially — which is how a suite ends up reporting safety it
   never checked — it announces the skip and moves on. It starts running tomorrow. */
await d4.goto(BASE);
await d4.waitForSelector('#startBtn');
const { epoch, today } = await d4.evaluate(() => ({ epoch: BAG_EPOCH, today: TODAY }));
const past = new Date(Date.parse(today + 'T00:00:00Z') - 3 * 86400000).toISOString().slice(0, 10);

if (past < epoch) {
  log(`  SKIP  challenge-escape section — epoch is ${epoch}, so no puzzle before`
    + ` ${today} exists yet. A same-day challenge is daily mode by design, so there`
    + ` is nothing here to exercise until tomorrow.`);
} else {
  const yest = past;
  await d4.goto(`${BASE}?challenge=1&from=Drew&score=380&d=${yest}`);
  await d4.waitForSelector('#startBtn');
  check('"Play today\'s instead" offered before committing', await d4.locator('#todayBtn').count() === 1);
  await d4.click('#todayBtn'); await d4.waitForSelector('#startBtn');
  const after = await d4.evaluate(async () => {
    const served = await (await fetch('/api/daily')).json();
    return { mode: MODE, rounds: ROUNDS.map(q => q.id), today: served.questions.map(q => q.id), url: location.search, banner: !!document.querySelector('.challenge-banner') };
  });
  check('escape from start screen reaches today', JSON.stringify(after.rounds) === JSON.stringify(after.today), `${after.rounds[0]} vs ${after.today[0]}`);
  check('MODE back to daily', after.mode === 'daily');
  check('challenge params cleared from the URL', after.url === '', `url search = "${after.url}"`);
  check('banner removed', !after.banner);
  check('topline no longer says CHALLENGE', !(await d4.locator('#topLeft').innerText()).includes('CHALLENGE'));

  // and via the results screen
  await d4.goto(`${BASE}?challenge=1&from=Drew&score=380&d=${yest}`);
  await d4.waitForSelector('#startBtn'); await d4.click('#startBtn');
  for (let i = 0; i < 5; i++) {
    await d4.waitForSelector('#chartSvg');
    const bb = await d4.locator('#chartSvg').boundingBox();
    await d4.mouse.click(bb.x + bb.width * 0.5, bb.y + bb.height * 0.5);
    await d4.click('#submitBtn'); await d4.waitForSelector('.reveal'); await d4.click('#submitBtn');
  }
  await d4.waitForSelector('.share-card');
  // Case-insensitive on purpose: this asserts the streak is untouched, not how the
  // sentence is punctuated. It broke once because a copy edit capitalised the word
  // after a full stop, which is not a behaviour change and should not read as one.
  check('challenge round did not touch the streak',
    /doesn't affect/i.test(await d4.locator('.streak-line').innerText()));
  await d4.click('#backBtn'); await d4.waitForSelector('#startBtn');
  const after2 = await d4.evaluate(async () => {
    const served = await (await fetch('/api/daily')).json();
    return { mode: MODE, rounds: ROUNDS.map(q => q.id), today: served.questions.map(q => q.id), url: location.search };
  });
  check('escape from results screen reaches today', JSON.stringify(after2.rounds) === JSON.stringify(after2.today) && after2.mode === 'daily' && after2.url === '');
}

// Was `check('no "Play again" button on a daily result', true)` — a literal true,
// which cannot fail and therefore checked nothing. Play again was removed with
// practice mode because on a daily round it re-served the same five questions with
// every answer already revealed. This asserts the button is actually absent.
await d4.goto(BASE);
await d4.waitForSelector('#startBtn'); await d4.click('#startBtn');
for (let i = 0; i < 5; i++) {
  await d4.waitForSelector('#chartSvg');
  const bb = await d4.locator('#chartSvg').boundingBox();
  await d4.mouse.click(bb.x + bb.width * 0.5, bb.y + bb.height * 0.5);
  await d4.click('#submitBtn'); await d4.waitForSelector('.reveal'); await d4.click('#submitBtn');
}
await d4.waitForSelector('.share-card');
check('no "Play again" button on a daily result',
  await d4.locator('button', { hasText: /play again/i }).count() === 0);

// ================= 5. SCORING =================
log('\n=== 5. SCORING / HEAT TIERS ===');
const sc = await d4.evaluate(() => {
  const f = d => scoreGuess2D(0, 0, d / Math.SQRT2, d / Math.SQRT2, 1, 1).points;
  return {
    exact: f(0), max: f(Math.SQRT2),
    curve: [0, 0.05, 0.1, 0.2, 0.3, 0.45, 0.7, 1.0].map(d => [d, f(d)]),
    tiers: TIERS.map(t => [t.label, t.min, t.emoji]),
    rings: TIERS.filter(t => t.min > 0).map(t => [t.label, +distForScore(t.min).toFixed(3)]),
  };
});
check('exact hit scores 100', sc.exact === 100);
check('maximum miss scores 0 (was 2 — the floor is real now)', sc.max === 0);
check('six reachable tiers', sc.tiers.length === 6);
log('    curve  d -> pts: ' + sc.curve.map(([d, p]) => `${d}->${p}`).join('  '));
log('    ring radii     : ' + sc.rings.map(([l, d]) => `${l} ${d}`).join('  '));

// full daily run to see a realistic strip
await d4.goto(BASE); await d4.waitForSelector('#startBtn'); await d4.click('#startBtn');
for (let i = 0; i < 5; i++) {
  await d4.waitForSelector('#chartSvg');
  const bb = await d4.locator('#chartSvg').boundingBox();
  await d4.mouse.click(bb.x + bb.width * 0.5, bb.y + bb.height * 0.5);
  await d4.click('#submitBtn'); await d4.waitForSelector('.reveal'); await d4.click('#submitBtn');
}
await d4.waitForSelector('.share-card');
log('    centre-clicker result: ' + (await d4.locator('.share-card').innerText()).replace(/\n/g, ' | '));
await d4.screenshot({ path: 'v-desktop-results.png', fullPage: true });
await d4.click('#statsBtn'); await d4.waitForTimeout(250);
await d4.screenshot({ path: 'v-stats.png' });
await c4.close();

log(`\n${fails === 0 ? 'ALL CHECKS PASSED' : fails + ' CHECK(S) FAILED'}`);
await browser.close();
process.exit(fails ? 1 : 0);
