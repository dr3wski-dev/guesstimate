import { chromium, devices } from 'playwright';
const BASE = process.env.BASE || 'http://localhost:8903/';
const b=await chromium.launch(); let fails=0;
const ck=(n,ok,d='')=>{console.log(`  ${ok?'PASS':'FAIL'}  ${n}${d?'  — '+d:''}`); if(!ok)fails++;};

// Device A: play a round, export a code
const ca=await b.newContext({permissions:['clipboard-read','clipboard-write']});
const A=await ca.newPage(); const errs=[]; A.on('pageerror',e=>errs.push(e.message));
await A.goto(BASE); await A.waitForSelector('#startBtn');
await A.evaluate(()=>{ saveStats(Object.assign({}, DEFAULT_STATS, {
  lastPlayed: TODAY, currentStreak:12, bestStreak:19, daysPlayed:40,
  totalPoints:14000, bestRound:472, tiers:{Great:60, Close:80, Bullseye:9} })); });
await A.click('#statsBtn'); await A.waitForTimeout(200);
await A.click('#copyCodeBtn'); await A.waitForTimeout(250);
const code = await A.locator('#myCode').inputValue();
console.log('  code:', code.slice(0,52)+'...', `(${code.length} chars)`);
ck('code has version prefix and checksum', /^SM1-[A-Z0-9]{1,4}-/.test(code));
ck('no JS errors on device A', errs.length===0, errs[0]||'');

// Device B: fresh browser, paste it
const cb=await b.newContext(); const B=await cb.newPage();
const errsB=[]; B.on('pageerror',e=>errsB.push(e.message));
await B.goto(BASE); await B.waitForSelector('#startBtn');
ck('device B starts with no streak', await B.evaluate(()=>liveStreak(loadStats(), TODAY))===0);
await B.click('#statsBtn'); await B.waitForTimeout(200);
ck('paste box offered even with no stats', await B.locator('#pasteCodeBtn').count()===1);
await B.click('#pasteCodeBtn'); await B.waitForTimeout(150);
await B.fill('#codeIn', code);
await B.click('#applyCodeBtn'); await B.waitForTimeout(300);
const got=await B.evaluate(()=>loadStats());
ck('streak restored', got.currentStreak===12, `streak ${got.currentStreak}`);
ck('best streak restored', got.bestStreak===19);
ck('days played restored', got.daysPlayed===40);
ck('tier breakdown restored', got.tiers.Close===80 && got.tiers.Bullseye===9, JSON.stringify(got.tiers));
ck('status line confirms', (await B.locator('#restoreStatus').innerText()).includes('12-day streak'));
ck('no JS errors on device B', errsB.length===0, errsB[0]||'');
await B.screenshot({path:'v-restore.png'});

// Corruption handling
const bad=await B.evaluate(()=>{
  const out={};
  const cases={ 'truncated':'SM1-ABCD-eyJsYXN0', 'wrong prefix':'XX1-ABCD-eyJhIjoxfQ',
                'garbage':'hello world', 'bad checksum':'SM1-ZZZZ-eyJhIjoxfQ' };
  for(const [k,v] of Object.entries(cases)){
    try{ readRestoreCode(v); out[k]='ACCEPTED (bad)'; }catch(e){ out[k]='rejected: '+e.message; }
  }
  return out;
});
Object.entries(bad).forEach(([k,v])=>ck(`rejects ${k}`, v.startsWith('rejected'), v));

// Restoring must not let you replay today for extra credit
const dbl=await B.evaluate(()=>{
  const before=loadStats().daysPlayed;
  registerCompletion([100,100,100,100,100], TODAY);
  return {before, after:loadStats().daysPlayed};
});
ck('restored lastPlayed still blocks a second completion today', dbl.before===dbl.after,
   `${dbl.before} -> ${dbl.after}`);
await b.close();
console.log(fails? `\n${fails} FAILED` : '\nALL RESTORE CHECKS PASSED');
process.exit(fails?1:0);
