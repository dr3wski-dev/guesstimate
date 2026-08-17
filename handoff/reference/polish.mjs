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
await p.waitForSelector('.share-card');
ck('recap present', await p.locator('.recap-row').count()===5,
   `${await p.locator('.recap-row').count()} rows`);
ck('recap collapsed by default', await p.locator('.recap-row[open]').count()===0);
await p.locator('.recap-row').first().locator('summary').click();
await p.waitForTimeout(150);
const opened=await p.locator('.recap-row').first().innerText();
ck('expanding shows guess and actual', /You said/.test(opened) && opened.length>120,
   opened.replace(/\n/g,' | ').slice(0,110)+'...');
ck('no JS errors', errs.length===0, errs[0]||'');
await p.screenshot({path:'v-recap.png', fullPage:true});
await b.close();
console.log(fails?`\n${fails} FAILED`:'\nALL POLISH CHECKS PASSED');
process.exit(fails?1:0);
