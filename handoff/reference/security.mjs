/* Security regression suite.
 *
 * Reading the code proves what it was meant to do; this proves what it does. Every
 * check here corresponds to a way a player could try to cheat, break, or attack the
 * game, and each one is a claim that would otherwise only be tested by someone
 * trying it in production.
 *
 * WHAT IT COVERS
 *   1  XSS through the challenge link's ?from= name (the only free text a stranger
 *      controls and another player sees)
 *   2  score/date parameter tampering
 *   3  the API refusing to be walked into the future — the whole point of the Worker
 *   4  the question pool being unreachable as a static file
 *   5  poisoned or malformed localStorage neither executing nor bricking the page
 *   6  malicious restore codes, driven through the real UI rather than by calling
 *      an internal — an earlier version of this suite called importCode() directly,
 *      got "not defined", and counted that as a PASS. A probe that cannot reach the
 *      code it is probing reports safety it never checked.
 *   7  API response headers and method handling
 *
 * Run against the dev server, which serves the real Worker under the real CSP:
 *   node handoff/pipeline/devserver.mjs 8903
 *   node handoff/reference/security.mjs
 */
import { chromium } from 'playwright';
const BASE = process.env.BASE || 'http://localhost:8903/';
const b=await chromium.launch();
let fails=0, pass=0;
const ok=(n,c,d='')=>{ c?pass++:fails++; console.log(`  ${c?'PASS':'FAIL'}  ${n}${d?'  — '+d:''}`); };

// --- 1. XSS through challenge params -------------------------------------
const payloads=[
  `"><script>window.__pwn=1<\/script>`,
  `'><img src=x onerror=window.__pwn=1>`,
  `javascript:window.__pwn=1`,
  `<svg/onload=window.__pwn=1>`,
  `"><script>window.__pwn=1</script>`,
  `<iframe srcdoc="<script>parent.__pwn=1<\/script>">`,
];
for(const p of payloads){
  const pg=await b.newPage(); const errs=[];
  pg.on('pageerror',e=>errs.push(e.message));
  await pg.goto(`${BASE}?challenge=1&from=${encodeURIComponent(p)}&score=100&d=2026-08-13`);
  await pg.waitForTimeout(350);
  const pwn=await pg.evaluate(()=>window.__pwn||0);
  const shown=await pg.evaluate(()=>document.body.innerText.slice(0,400));
  ok(`no exec via ?from= ${p.slice(0,26)}`, !pwn, shown.match(/script|onerror|svg/i)?'literal text only':'');
  await pg.close();
}
// --- 2. score / date param tampering -------------------------------------
{
  const pg=await b.newPage();
  await pg.goto(`${BASE}?challenge=1&from=Bob&score=999999999&d=2026-08-13`);
  await pg.waitForTimeout(350);
  const t=await pg.evaluate(()=>document.body.innerText);
  ok('score clamped, no absurd number rendered', !/999999999/.test(t));
  await pg.goto(`${BASE}?challenge=1&from=Bob&score=-5&d=2026-08-13`);
  await pg.waitForTimeout(300);
  ok('negative score rejected', !/-5\b/.test(await pg.evaluate(()=>document.body.innerText)));
  await pg.close();
}
// --- 3. future date cannot be walked forward ------------------------------
{
  const r=await fetch(`${BASE}api/daily?d=2099-01-01`); const j=await r.json();
  ok('future date refused by API', j.date!=='2099-01-01', `served ${j.date}`);
  const r2=await fetch(`${BASE}api/daily?d=../../etc/passwd`); const j2=await r2.json();
  ok('path-ish date refused', /^\d{4}-\d{2}-\d{2}$/.test(j2.date), `served ${j2.date}`);
  const r3=await fetch(`${BASE}api/daily`); const j3=await r3.json();
  ok('API returns exactly 5 questions, never the pool', j3.questions.length===5, `${j3.questions.length}`);
}
// --- 4. pool not reachable as a static file -------------------------------
for(const p of ['data/questions.json','questions.json','data/schedule.json','handoff/data/questions.json']){
  const r=await fetch(BASE+p);
  ok(`pool not served at /${p}`, r.status===404, `HTTP ${r.status}`);
}
// --- 5. poisoned localStorage must not execute or crash -------------------
{
  const pg=await b.newPage(); const errs=[];
  pg.on('pageerror',e=>errs.push(e.message));
  await pg.goto(BASE);
  await pg.evaluate(()=>localStorage.setItem('statmap_stats_v1','{"streak":"<img src=x onerror=window.__pwn=1>","best":{},"days":[1,2]}'));
  await pg.reload(); await pg.waitForTimeout(400);
  ok('poisoned localStorage does not execute', !(await pg.evaluate(()=>window.__pwn||0)));
  ok('poisoned localStorage does not crash the page', errs.length===0, errs[0]||'');
  await pg.evaluate(()=>localStorage.setItem('statmap_stats_v1','{{{not json'));
  await pg.reload(); await pg.waitForTimeout(400);
  ok('malformed localStorage recovers', await pg.locator('#startBtn').isVisible().catch(()=>false));
  await pg.close();
}
// --- 6. restore code injection, driven through the real UI ----------------
{
  const pg=await b.newPage(); const errs=[];
  pg.on('pageerror',e=>errs.push(e.message));
  await pg.goto(BASE);
  await pg.click('#statsBtn'); await pg.waitForTimeout(200);
  await pg.click('#pasteCodeBtn'); await pg.waitForTimeout(150);
  for(const bad of [
      'SM1-<img src=x onerror=window.__pwn=1>',
      '<script>window.__pwn=1<\/script>',
      'SM1-"><svg/onload=window.__pwn=1>',
  ]){
    await pg.fill('#codeIn', bad);
    await pg.click('#applyCodeBtn'); await pg.waitForTimeout(250);
    const st=await pg.locator('#restoreStatus').innerText().catch(()=>'');
    ok(`restore rejects ${bad.slice(0,28)}`, !/restored/i.test(st), st.slice(0,54));
    ok('  ...and did not execute', !(await pg.evaluate(()=>window.__pwn||0)));
    const html=await pg.locator('#restoreStatus').innerHTML().catch(()=>'');
    ok('  ...and rendered no live markup', !/<(img|svg|script|iframe)/i.test(html));
  }
  ok('restore probe raised no page errors', errs.length===0, errs[0]||'');
  await pg.close();
}
// --- 7. security headers on the API ---------------------------------------
{
  const r=await fetch(`${BASE}api/daily`);
  ok('API sets nosniff', r.headers.get('x-content-type-options')==='nosniff');
  ok('API is json', /application\/json/.test(r.headers.get('content-type')||''));
  const bad=await fetch(`${BASE}api/daily`,{method:'POST'});
  ok('API refuses non-GET', bad.status===405, `HTTP ${bad.status}`);
}
console.log(`\n${pass} passed, ${fails} failed`);
await b.close();
process.exit(fails?1:0);
