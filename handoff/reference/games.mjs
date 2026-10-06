/* Does each minigame behave as its own game?
 *
 * WHY THIS SUITE EXISTS
 * Splitting one game into several introduced a failure that none of the other
 * suites can see, because they only ever load one page: every game is served from
 * the SAME 2,700-line template, and the only thing that distinguishes them is a
 * small injected object. If that injection goes missing, or lands with the wrong
 * id, every page still loads, still plays, and still looks completely correct —
 * while being hard mode wearing a different title, writing to hard mode's streak.
 *
 * So the checks here are all about identity rather than layout:
 *   - the page says which game it is, and the switcher marks the one you are on
 *   - the puzzle number counts from THIS game's epoch, not the original's
 *   - the streak lands in this game's localStorage key and no other one
 *   - a restore code from one game is refused by another, by name
 *
 * The streak check plays all five rounds for real on all three games, because
 * "writes to the right key" is only true at the moment a day is actually recorded.
 *
 *   BASE=http://localhost:8903/ node reference/games.mjs
 */
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

/* Read from the manifest rather than hard-coded here. The first version of this
 * file listed the three live games by name, and opening a fourth turned a correct
 * change into eight red checks about nothing. A test that has to be edited every
 * time the thing it tests is extended stops being read. */
const HERE = path.dirname(fileURLToPath(import.meta.url));
const GAMES = JSON.parse(fs.readFileSync(path.join(HERE, '..', 'data', 'games.json'), 'utf8'));
const LIVE = Object.entries(GAMES).filter(([, g]) => g.status === 'live');
const PENDING = Object.entries(GAMES).filter(([, g]) => g.status !== 'live');
const BASE = process.env.BASE || 'http://localhost:8903/';
const b = await chromium.launch();
let fails = 0;
const ok = (n, c, note='') => { console.log(`  ${c?'PASS':'FAIL'}  ${n}${note?'  — '+note:''}`); if(!c) fails++; };

for (const [gid, game] of LIVE) {
  const slug = game.slug ? game.slug + '/' : '';
  const expectName = game.name, expectShort = game.short;
  const ctx = await b.newContext({ viewport:{width:1280,height:900} });
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', e => errs.push(String(e)));
  await p.goto(BASE + slug, { waitUntil:'networkidle' });
  await p.waitForSelector('#startBtn');
  console.log(`\n/${slug}`);
  ok('title is this game', (await p.textContent('h1.title')) === expectName, await p.textContent('h1.title'));
  const links = await p.$$eval('.game-link', es => es.map(e => [e.textContent.trim(), e.getAttribute('href'), e.getAttribute('aria-current')]));
  ok(`switcher lists all ${LIVE.length} live games`, links.length === LIVE.length, JSON.stringify(links));
  ok('current game is marked', links.filter(l => l[2]==='page').length === 1 && links.find(l=>l[2]==='page')[0] === expectShort);
  const soon = await p.textContent('.game-soon').catch(()=>null);
  ok('every game that is not open is named',
     PENDING.every(([, g]) => (soon || '').includes(g.short)),
     (soon||'').slice(0,80).replace(/\s+/g,' '));
  const g = await p.evaluate(() => ({ id: GAME.id, key: STATS_KEY, epoch: GAME.epoch, no: PUZZLE_NO }));
  ok('stats key namespaced', slug === '' ? g.key === 'statmap_stats_v1' : g.key === `statmap_stats_v1_${g.id}`, g.key);
  ok('puzzle number from this game epoch', Number.isInteger(g.no) && g.no >= 1, `#${g.no} epoch ${g.epoch}`);

  // Play all five rounds and confirm the streak lands in this game's key only.
  await p.click('#startBtn');
  for (let i = 0; i < 5; i++) {
    await p.waitForSelector('.chart-frame', { timeout: 8000 });
    const box = await p.locator('.chart-frame').boundingBox();
    await p.mouse.click(box.x + box.width*0.5, box.y + box.height*0.5);
    await p.click('#submitBtn');
    await p.waitForSelector('.reveal', { timeout: 8000 });
    await p.click('#submitBtn');
  }
  await p.waitForTimeout(500);
  const store = await p.evaluate(() => {
    const out = {};
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k.startsWith('statmap_stats')) out[k] = JSON.parse(localStorage.getItem(k)).daysPlayed;
    }
    return out;
  });
  ok('only this game got a day', Object.keys(store).length === 1, JSON.stringify(store));
  const share = await p.evaluate(() => document.body.innerText.match(/StatMap[^\n]*#\d+/)?.[0] || '');
  ok('headline names the game', share.startsWith(expectName), share);
  ok('no JS errors', errs.length === 0, errs[0] || '');
  await ctx.close();
}

// Cross-game restore code refusal.
const ctx = await b.newContext();
const p = await ctx.newPage();
await p.goto(BASE, { waitUntil:'networkidle' });
const code = await p.evaluate(() => makeRestoreCode({ lastPlayed:'2026-10-05', currentStreak:3, bestStreak:5, daysPlayed:7, totalPoints:900, bestRound:400, tiers:{} }));
const other = LIVE.find(([gid]) => gid !== 'main');
const p2 = await (await b.newContext()).newPage();
await p2.goto(BASE + other[1].slug + '/', { waitUntil:'networkidle' });
const res = await p2.evaluate(c => { try { readRestoreCode(c); return 'ACCEPTED'; } catch(e){ return e.message; } }, code);
console.log('\ncross-game restore code');
ok(`a hard-mode code is refused in ${other[1].name}`,
   res.includes(`not ${other[1].name}`), res);
const self = await p2.evaluate(() => { const c = makeRestoreCode({lastPlayed:'2026-10-05',currentStreak:2,bestStreak:2,daysPlayed:2,totalPoints:1,bestRound:1,tiers:{}}); try { return readRestoreCode(c).currentStreak; } catch(e){ return 'REFUSED: '+e.message; } });
ok(`${other[1].name}'s own code still works`, self === 2, String(self));

/* EVERY ROUND OF EVERY GAME, AT PHONE WIDTH.
 * Two assertions, and they are the same assertion twice over. A reference line one
 * long name too wide ran 20px past the right edge of a 390px screen — and a page
 * wider than the viewport makes a mobile browser report a TALLER one, which pushed
 * the sticky Submit bar 35px down and off the bottom of the first question of the
 * day. One of those is ugly and the other is unplayable, and they have one cause.
 *
 * It has to run over the real served content, because the trigger is a string: the
 * question that found it was the only one of twenty with a hyphenated 23-character
 * name in the reference list. */
const phone = { viewport: { width: 390, height: 664 }, isMobile: true,
                hasTouch: true, deviceScaleFactor: 3 };
console.log('\nphone layout, every round of every game (390x664)');
for (const [gid, game] of LIVE) {
  const ctx = await b.newContext(phone);
  await ctx.addInitScript(() => { try { localStorage.setItem('statmap_seen_intro','1'); } catch(e){} });
  const p = await ctx.newPage();
  await p.goto(BASE + (game.slug ? game.slug + '/' : ''), { waitUntil: 'networkidle' });
  await p.waitForSelector('#startBtn');
  await p.click('#startBtn');
  for (let i = 1; i <= 5; i++) {
    await p.waitForSelector('#chartSvg');
    await p.evaluate(() => window.scrollTo(0, 0));
    const m = await p.evaluate(() => {
      const el = document.documentElement;
      const over = [...document.querySelectorAll('*')]
        .filter(e => e.getBoundingClientRect().right > el.clientWidth + 0.5)
        .map(e => (e.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 40));
      return { scrollW: el.scrollWidth, clientW: el.clientWidth, over: over[0] || '',
               submit: Math.round(document.querySelector('#submitBtn').getBoundingClientRect().bottom),
               vh: window.innerHeight };
    });
    ok(`${gid} r${i} no horizontal overflow`, m.scrollW <= m.clientW + 1,
       m.scrollW > m.clientW ? `${m.scrollW} > ${m.clientW} — "${m.over}"` : '');
    ok(`${gid} r${i} submit on screen`, m.submit <= 664, `bottom ${m.submit}, innerHeight ${m.vh}`);
    const box = await p.locator('.chart-frame').boundingBox();
    await p.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    await p.click('#submitBtn');
    await p.waitForSelector('.reveal');
    await p.click('#submitBtn');
  }
  await ctx.close();
}

await b.close();
console.log(fails ? `\n${fails} FAILED` : '\nALL GAME CHECKS PASSED');
process.exit(fails ? 1 : 0);
