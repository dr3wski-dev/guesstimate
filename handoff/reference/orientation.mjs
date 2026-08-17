/* Orientation suite — does the game work with the phone turned sideways?
 *
 * WHY THIS EXISTS
 * Landscape was broken from the day the layout was written and no check noticed,
 * because every other suite runs at one portrait viewport. Turned sideways a phone
 * has roughly 390px of height, and the portrait layout stacked everything: the chart
 * alone came out 411px tall — taller than the screen — so a player had to scroll down
 * to reach the thing they were supposed to tap, while 300px of width sat empty beside
 * it. It looked fine to anyone testing in portrait, which is everyone.
 *
 * WHAT IT ASSERTS
 * The two things that decide whether the game is playable at all in a given
 * orientation: can you see the chart without scrolling, and can you reach the button.
 * Everything else is taste; these are function.
 *
 *   node pipeline/devserver.mjs 8903
 *   node reference/orientation.mjs
 */
import { chromium } from 'playwright';

const BASE = process.env.BASE || 'http://localhost:8903/';

// Inner viewport sizes, i.e. after Safari's own chrome. The SE is the floor worth
// supporting; the Pro Max is the ceiling. iPad is here to prove the phone-landscape
// rules do NOT apply to it — it has the height for the portrait layout and should
// keep it.
const VIEWS = [
  { name: 'iPhone SE landscape',      w: 667,  h: 320 },
  { name: 'iPhone 13 landscape',      w: 844,  h: 390 },
  { name: 'iPhone 15 Pro Max landsc', w: 932,  h: 430 },
  { name: 'iPhone 13 portrait',       w: 390,  h: 664 },
  { name: 'iPad portrait',            w: 820,  h: 1180 },
];

let failures = 0;
const check = (name, ok, detail = '') => {
  if (!ok) failures++;
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`);
};

const browser = await chromium.launch();
console.log('=== ORIENTATION ===');

for (const v of VIEWS) {
  const ctx = await browser.newContext({
    viewport: { width: v.w, height: v.h }, isMobile: true, hasTouch: true,
  });
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', e => errs.push(e.message));

  await p.goto(BASE);
  await p.waitForSelector('#startBtn');
  await p.click('#startBtn');
  await p.waitForSelector('#chartSvg');
  await p.waitForTimeout(500);

  console.log(`\n${v.name}  ${v.w}x${v.h}`);

  const g = await p.evaluate(() => {
    const c = document.getElementById('chartSvg').getBoundingClientRect();
    const b = document.getElementById('submitBtn').getBoundingClientRect();
    return {
      chartFits: c.bottom <= window.innerHeight + 1 && c.top >= 0,
      chartH: Math.round(c.height),
      btnOn: b.bottom <= window.innerHeight + 1 && b.top >= 0,
      hScroll: document.documentElement.scrollWidth > window.innerWidth + 1,
      screenH: window.innerHeight,
    };
  });
  // The whole interaction is tapping the chart. If it needs scrolling to reach, the
  // game does not work in this orientation.
  check('chart fully visible before guessing', g.chartFits,
    `chart ${g.chartH}px of ${g.screenH}px screen`);
  check('submit reachable without scrolling', g.btnOn);
  check('no horizontal scroll', !g.hScroll);

  // Guess, then confirm the control survives the state change.
  const bb = await p.locator('#chartSvg').boundingBox();
  await p.mouse.click(bb.x + bb.width * 0.4, bb.y + bb.height * 0.55);
  await p.waitForTimeout(120);
  const beforeRight = await p.evaluate(() => {
    const r = document.getElementById('submitBtn').getBoundingClientRect();
    return Math.round(window.innerWidth - r.right);
  });
  await p.click('#submitBtn');
  await p.waitForSelector('.reveal');
  await p.waitForTimeout(1600);

  const r = await p.evaluate(() => {
    const b = document.getElementById('submitBtn').getBoundingClientRect();
    return {
      right: Math.round(window.innerWidth - b.right),
      btnOn: b.bottom <= window.innerHeight + 1 && b.top >= 0,
      // The written fact was cut from the product (see SHOW_FACT in the game).
      // The citation stayed, because the numbers on screen need one.
      sourcePresent: !!document.querySelector('.fact-source'),
      factAbsent: !document.querySelector('.fact'),
    };
  });
  // A control that moves after you press it costs the player their aim every round.
  check('button does not move after submitting', Math.abs(r.right - beforeRight) <= 3,
    `${beforeRight}px -> ${r.right}px from right edge`);
  check('button still on screen after reveal', r.btnOn);
  check('the source line rendered', r.sourcePresent);
  check('no written fact copy', r.factAbsent);

  // Scrolled to the bottom, the button must still be there — that is the whole point
  // of it being sticky, and it is where a player ends up after reading.
  await p.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await p.waitForTimeout(300);
  const pinned = await p.evaluate(() => {
    const b = document.getElementById('submitBtn').getBoundingClientRect();
    return b.bottom <= window.innerHeight + 1 && b.top >= 0;
  });
  check('button stays pinned when scrolled to the fact', pinned);
  check('no JS errors', errs.length === 0, errs[0] || '');

  await ctx.close();
}

console.log(failures ? `\n${failures} ORIENTATION CHECK(S) FAILED` : '\nALL ORIENTATION CHECKS PASSED');
await browser.close();
process.exit(failures ? 1 : 0);
