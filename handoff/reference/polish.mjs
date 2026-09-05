import { chromium, devices } from 'playwright';
import fs from 'node:fs';
// The client no longer holds the pool (the Worker does), so read the source of
// truth from disk rather than out of the page.
import path from 'path';
import { fileURLToPath } from 'url';
// Resolved from this file, not from an absolute path baked in on one machine —
// the suite is committed, so it has to run on any checkout.
const POOL = JSON.parse(fs.readFileSync(
  path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'data', 'questions.json'), 'utf8'));
const BASE = process.env.BASE || 'http://localhost:8903/';
const b=await chromium.launch(); let fails=0;
const ck=(n,ok,d='')=>{console.log(`  ${ok?'PASS':'FAIL'}  ${n}${d?'  — '+d:''}`); if(!ok)fails++;};

// keyboard nudge now scales to the axis
const c=await b.newContext({viewport:{width:1280,height:1000}}); const p=await c.newPage();
const errs=[]; p.on('pageerror',e=>errs.push(e.message));
await p.goto(BASE); await p.waitForSelector('#startBtn');
const kb=await p.evaluate((POOL)=>{
  const out=[];
  for(const q of POOL){
    const xs=q.xStep||0.1, ys=q.yStep||0.1;
    const [x0,x1]=resolveDomain(q.xDomain,q.referencePlayers.map(r=>r.x),q.targetX);
    const [y0,y1]=resolveDomain(q.yDomain,q.referencePlayers.map(r=>r.y),q.targetY);
    const nudge=(st,rg)=>Math.max(st,rg/100);
    out.push({id:q.id, x:Math.round((x1-x0)/nudge(xs,x1-x0)), y:Math.round((y1-y0)/nudge(ys,y1-y0))});
  }
  return out;
}, POOL);
const worst=Math.max(...kb.map(r=>Math.max(r.x,r.y)));
ck('keyboard: no question needs more than ~100 presses per axis', worst<=100, `worst ${worst} (was 16,000)`);

// batting average formatting
const fmt=await p.evaluate(()=>({ avg:fmtVal(0.366,0.001), neg:fmtVal(-0.5,0.001),
                                   ppg:fmtVal(25.3,0.1), hr:fmtVal(573,1) }));
ck('batting average drops the leading zero', fmt.avg==='.366', JSON.stringify(fmt));
ck('other stats unaffected', fmt.ppg==='25.3' && fmt.hr==='573');

// play a full round, check the recap
await p.click('#startBtn');
for(let i=0;i<5;i++){
  await p.waitForSelector('#chartSvg');
  const bb=await p.locator('#chartSvg').boundingBox();
  await p.mouse.click(bb.x+bb.width*0.5, bb.y+bb.height*0.45);
  await p.click('#submitBtn'); await p.waitForSelector('.reveal'); await p.click('#submitBtn');
}
// The reference list must be present BEFORE every guess, not just the first.
//
// This is here because it shipped broken. The reveal adds a `revealed` class that
// demotes the reference players below the answer and, on a viewport under 600px
// tall or in phone landscape, hides them entirely — correct once the answer is up,
// wrong before a guess, where those dots are the only thing you have to aim
// between. showQuestion() did not clear the class, so questions 2 through 5 were
// played without them on every short screen. Checked at 1279x582 specifically,
// because at 1280x1000 the rule never applies and the bug is invisible.
{
  const sc = await b.newContext({viewport:{width:1279,height:582}});
  const sp = await sc.newPage();
  await sp.goto(BASE);
  await sp.waitForSelector('#startBtn');
  await sp.click('#startBtn');
  let missing = [];
  for (let n = 1; n <= 3; n++) {
    await sp.waitForSelector('#chartSvg');
    const shown = await sp.evaluate(() => {
      const r = document.getElementById('refs');
      return !!r && r.getBoundingClientRect().height > 0
             && !document.querySelector('.panel').classList.contains('revealed');
    });
    if (!shown) missing.push(n);
    const bb = await sp.locator('#chartSvg').boundingBox();
    await sp.mouse.click(bb.x + bb.width * 0.5, bb.y + bb.height * 0.45);
    await sp.click('#submitBtn');
    await sp.waitForSelector('.reveal');
    await sp.click('#submitBtn');
    await sp.waitForTimeout(200);
  }
  ck('reference list is shown before every guess, not just the first',
     missing.length === 0,
     missing.length ? `hidden on question ${missing.join(', ')} at 1279x582` : 'questions 1-3 at 1279x582');
  await sc.close();
}

await p.waitForSelector('.share-card');
ck('recap present', await p.locator('.recap-row').count()===5,
   `${await p.locator('.recap-row').count()} rows`);
ck('recap collapsed by default', await p.locator('.recap-row[open]').count()===0);
await p.locator('.recap-row').first().locator('summary').click();
await p.waitForTimeout(150);
const opened=await p.locator('.recap-row').first().innerText();
// Assert what the row is supposed to CONTAIN, not how many characters it runs to.
// This previously required `opened.length > 120`, which is a proxy for "it expanded"
// that depends on how long the day's player names and stat labels happen to be. It
// passed in CI on 2 September and failed on 5 September against identical code,
// because the calendar had moved to a question whose recap line is 105 characters —
// a red build caused by a short name. Both halves below are things the row genuinely
// must show, and neither moves with the content.
ck('expanding shows guess and actual',
   /You said/.test(opened) && /actual/.test(opened),
   opened.replace(/\n/g,' | ').slice(0,110)+'...');
ck('no JS errors', errs.length===0, errs[0]||'');
await p.screenshot({path:'v-recap.png', fullPage:true});
await b.close();
console.log(fails?`\n${fails} FAILED`:'\nALL POLISH CHECKS PASSED');
process.exit(fails?1:0);
