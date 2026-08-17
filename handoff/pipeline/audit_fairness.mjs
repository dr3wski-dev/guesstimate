/* Fairness audit — does each question actually test knowledge?
 *
 * WHY THIS EXISTS
 * verify_questions.py proves every number is real. That is necessary and not
 * sufficient: a question can be perfectly accurate and still be a bad question.
 * Score is distance normalised by the PLOTTED DOMAIN, and the domain is chosen for
 * tick aesthetics — so how hard a question plays is partly a side effect of where
 * nice_domain() happened to put the axis edges. Nobody was measuring that, and two
 * shipped questions had drifted to the point where clicking the middle of the chart
 * beat actually knowing the answer.
 *
 * THE TWO GATES
 *   centre  — - what a player scores by clicking the middle with no knowledge at all.
 *             High means free points: the domain is drawn so tightly around the
 *             answer that the whole chart is the answer's neighbourhood.
 *   lift    — informed score minus centre score. This is the question's actual
 *             discriminating power. Near zero means knowing the answer is worth
 *             nothing, which is the real failure mode — a question that cannot
 *             distinguish a fan from a stranger is decoration.
 *
 * The informed model: a player who can place the target relative to the three
 * visible reference players but not exactly, i.e. gaussian error at 25% of the
 * spread of those references. Error is modelled in STAT units and scored in DOMAIN
 * units, which is precisely the mismatch this audit is here to surface.
 *
 * WHY NODE AND NOT PYTHON
 * The rest of the pipeline is Python, but the scoring curve lives in the game. This
 * script parses SCORE_SIGMA, SCORE_SHAPE and the domain rules straight out of the
 * reference HTML rather than restating them, so the audit cannot drift away from the
 * scoring it is auditing. A second hand-copied curve would eventually disagree with
 * the real one and this whole check would quietly become fiction.
 *
 *   node pipeline/audit_fairness.mjs            # audit, exit 1 on failure
 *   node pipeline/audit_fairness.mjs --suggest  # also print repaired domains
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, '..');
const SRC_HTML = path.join(ROOT, 'reference', 'statmap.html');
const SRC_DATA = path.join(ROOT, 'data', 'questions.json');

// Thresholds. Both were read off the pool's own distribution rather than picked as
// round numbers: the median question gives a centre-clicker 20 and a lift of 56, so
// these sit far enough out to catch genuine outliers without condemning the middle
// of the pack. Tightening them is a content decision, not a code one.
export const MAX_CENTRE = 35;   // above this the chart hands out too much for free
export const MIN_LIFT   = 30;   // below this the question barely rewards knowing

// ---- scoring constants, read from the game so they cannot drift ----
const html = fs.readFileSync(SRC_HTML, 'utf8');
function constant(name) {
  const m = html.match(new RegExp(`const ${name}\\s*=\\s*([0-9.]+)`));
  if (!m) throw new Error(`could not read ${name} from ${path.basename(SRC_HTML)} — ` +
    'the audit reads the real scoring constants on purpose; fix the parse rather ' +
    'than hardcoding a copy here');
  return parseFloat(m[1]);
}
const SIGMA = constant('SCORE_SIGMA');
const SHAPE = constant('SCORE_SHAPE');
const score = (d) => Math.round(100 * Math.exp(-Math.pow(d / SIGMA, SHAPE)));

// ---- domain resolution, mirroring resolveDomain() in the game ----
function autoDomain(vals, target) {
  const all = [...vals, target];
  const lo = Math.min(...all), hi = Math.max(...all);
  const pad = (hi - lo) * 0.15 || 1;
  return [lo - pad, hi + pad];
}
function resolveDomain(explicit, refVals, target) {
  if (Array.isArray(explicit) && explicit.length === 2 && explicit[0] < explicit[1]) {
    let [lo, hi] = explicit;
    if (target < lo || target > hi) {
      const pad = (hi - lo) * 0.1;
      lo = Math.min(lo, target - pad); hi = Math.max(hi, target + pad);
    }
    return [lo, hi];
  }
  return autoDomain(refVals, target);
}

// Deterministic RNG: an audit that reports a different number every run is one
// nobody can bisect against.
let seed = 12345;
const rand = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };
const gauss = () => {
  let u = 0, v = 0;
  while (!u) u = rand();
  while (!v) v = rand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
};

const N = 4000;
export function audit(q) {
  const xs = q.referencePlayers.map(p => p.x), ys = q.referencePlayers.map(p => p.y);
  const [x0, x1] = resolveDomain(q.xDomain, xs, q.targetX);
  const [y0, y1] = resolveDomain(q.yDomain, ys, q.targetY);
  const xR = x1 - x0, yR = y1 - y0;
  const xSpread = Math.max(...xs) - Math.min(...xs) || Math.abs(q.targetX) * 0.1 || 1;
  const ySpread = Math.max(...ys) - Math.min(...ys) || Math.abs(q.targetY) * 0.1 || 1;

  const centre = score(Math.hypot(
    ((x0 + x1) / 2 - q.targetX) / xR, ((y0 + y1) / 2 - q.targetY) / yR));

  seed = 12345;
  let sum = 0;
  for (let i = 0; i < N; i++) {
    let gx = q.targetX + gauss() * 0.25 * xSpread;
    let gy = q.targetY + gauss() * 0.25 * ySpread;
    gx = Math.max(x0, Math.min(x1, gx));
    gy = Math.max(y0, Math.min(y1, gy));
    sum += score(Math.hypot((gx - q.targetX) / xR, (gy - q.targetY) / yR));
  }
  const informed = sum / N;
  return {
    id: q.id, league: q.league, centre, informed: Math.round(informed),
    lift: Math.round(informed - centre),
    xPos: (q.targetX - x0) / xR, yPos: (q.targetY - y0) / yR,
  };
}

/* Repair a question by re-choosing its axis windows.
 *
 * WHY A SEARCH AND NOT A FORMULA
 * The first cut of this was a formula — anchor at zero, pad the top. It made several
 * questions worse, because zero is meaningless for some stats (a true shooting
 * percentage axis starting at 0 wastes three quarters of the chart) and because
 * moving one edge can push the target TOWARD the centre, which is the failure being
 * repaired. Domain choice has a real objective — make the centre of the chart a bad
 * guess — so it is solved as an optimisation against that objective rather than
 * guessed at.
 *
 * WHAT IS ALLOWED TO CHANGE
 * Only the viewport. Every plotted value is verified against the raw datasets and
 * must not move to make a question play better; a domain is a choice about what
 * window to draw, and re-choosing it changes no claim about any player.
 *
 * THE CONSTRAINTS ARE THE INTERESTING PART
 * Minimising the centre score alone would produce absurd axes — span 0 to 10,000 and
 * the centre is always terrible, but so is the chart. So candidates must stay
 * readable: every point on screen with margin, a real zero only where the stat has
 * one, and enough of the axis actually occupied that the plot doesn't collapse into
 * a corner. The search maximises discriminating power subject to those. */
const NICE = [1, 2, 2.5, 4, 5, 10];
function niceSteps(rough) {
  const mag = Math.pow(10, Math.floor(Math.log10(rough)));
  return NICE.map(n => n * mag).filter(s => s > 0);
}

function repair(q) {
  const xs = q.referencePlayers.map(p => p.x), ys = q.referencePlayers.map(p => p.y);
  const best = { x: null, y: null };
  for (const [axis, vals, target] of [['x', xs, q.targetX], ['y', ys, q.targetY]]) {
    const all = [...vals, target];
    const lo0 = Math.min(...all), hi0 = Math.max(...all);
    const spread = hi0 - lo0 || Math.abs(target) * 0.2 || 1;
    const zeroOk = lo0 >= 0;
    // Whole stats keep whole ticks: a "touchdowns" axis labelled 2.5 is nonsense.
    const whole = all.every(v => Number.isInteger(v));

    let bestCand = null;
    for (const step of niceSteps(spread / 3)) {
      if (whole && !Number.isInteger(step)) continue;
      // Four tick intervals, as the chart draws five labels.
      for (let ticks = 4; ticks <= 4; ticks++) {
        const range = step * ticks;
        if (range < spread * 1.05) continue;          // must contain the data
        for (let k = 0; k <= ticks; k++) {
          const lo = Math.round((hi0 - range + step * k) / step) * step;
          const hi = lo + range;
          if (lo > lo0 - spread * 0.04 || hi < hi0 + spread * 0.04) continue;  // margin
          if (zeroOk && lo < 0) continue;             // no negative axis on a count
          // Stay near the data. Without this the search happily proposes a receptions
          // axis running to 2,500 — the centre of that chart is certainly a bad guess,
          // but no human has ever caught 2,500 passes and the axis quietly implies
          // someone might. An axis may extend past the data; it may not invent a
          // world beyond it.
          if (hi > hi0 + spread * 0.8 || lo < lo0 - spread * 0.8) continue;
          const fill = spread / range;
          if (fill < 0.38) continue;                  // plot must not collapse
          // objective: push the target away from the centre of the axis
          const off = Math.abs((target - lo) / range - 0.5);
          const sc = off + 0.15 * fill;               // tie-break toward a fuller plot
          if (!bestCand || sc > bestCand.sc) bestCand = { lo, hi, sc };
        }
      }
    }
    best[axis] = bestCand ? [bestCand.lo, bestCand.hi] : null;
  }
  if (!best.x || !best.y) return null;
  const trial = { ...q, xDomain: best.x, yDomain: best.y };
  return { xDomain: best.x, yDomain: best.y, after: audit(trial) };
}

/* Tighten a chart until it is as full as fairness allows.
 *
 * WHY THIS IS A SEPARATE PASS FROM repair()
 * repair() widens an axis to push the target away from the centre. Tighten pulls the
 * other way, to fill the plot. They are opposing forces on the same knob, and the
 * useful answer is the tightest window that still passes both gates — so this runs
 * over the whole pool, not only over failures.
 *
 * THE METRIC WAS WRONG, WHICH IS WHY THIS IS NEEDED
 * The original constraint was per-axis fill at 38%. But a reader perceives AREA, and
 * 0.4 x 0.4 is 16% of the plot. Twenty questions came out under a quarter covered
 * and read as mostly empty space, all of them passing a fill check that was measuring
 * the wrong thing. Optimising area directly fixes the class, not the instances.
 *
 * Centre score is exact and cheap, so it filters candidates first; lift needs a
 * simulation, so it only runs on the handful that survive, best-area first. */
function tighten(q) {
  const cand = {};
  for (const [axis, vals, target] of
       [['x', q.referencePlayers.map(p => p.x), q.targetX],
        ['y', q.referencePlayers.map(p => p.y), q.targetY]]) {
    const all = [...vals, target];
    const lo0 = Math.min(...all), hi0 = Math.max(...all);
    const spread = hi0 - lo0 || Math.abs(target) * 0.2 || 1;
    const zeroOk = lo0 >= 0;
    const whole = all.every(v => Number.isInteger(v));
    const out = [];
    for (const step of niceSteps(spread / 3)) {
      if (whole && !Number.isInteger(step)) continue;
      const range = step * 4;
      if (range < spread * 1.02) continue;
      for (let k = 0; k <= 4; k++) {
        const lo = Math.round((hi0 - range + step * k) / step) * step;
        const hi = lo + range;
        if (lo > lo0 - spread * 0.03 || hi < hi0 + spread * 0.03) continue;
        if (zeroOk && lo < 0) continue;
        out.push({ lo, hi, fill: spread / range });
      }
    }
    cand[axis] = out;
  }
  if (!cand.x.length || !cand.y.length) return null;

  const combos = [];
  for (const cx of cand.x) for (const cy of cand.y) {
    const trial = { ...q, xDomain: [cx.lo, cx.hi], yDomain: [cy.lo, cy.hi] };
    // Cheap exact filter before paying for the simulation.
    const xs = q.referencePlayers.map(p => p.x), ys = q.referencePlayers.map(p => p.y);
    const xR = cx.hi - cx.lo, yR = cy.hi - cy.lo;
    const centre = score(Math.hypot(
      ((cx.lo + cx.hi) / 2 - q.targetX) / xR, ((cy.lo + cy.hi) / 2 - q.targetY) / yR));
    if (centre > MAX_CENTRE) continue;
    void xs; void ys;
    combos.push({ trial, area: cx.fill * cy.fill });
  }
  combos.sort((a, b) => b.area - a.area);
  for (const c of combos.slice(0, 40)) {
    const a = audit(c.trial);
    if (a.centre <= MAX_CENTRE && a.lift >= MIN_LIFT) {
      return { xDomain: c.trial.xDomain, yDomain: c.trial.yDomain, area: c.area, after: a };
    }
  }
  return null;
}

function areaOf(q) {
  const xs = q.referencePlayers.map(p => p.x).concat(q.targetX);
  const ys = q.referencePlayers.map(p => p.y).concat(q.targetY);
  const [x0, x1] = resolveDomain(q.xDomain, q.referencePlayers.map(p => p.x), q.targetX);
  const [y0, y1] = resolveDomain(q.yDomain, q.referencePlayers.map(p => p.y), q.targetY);
  return ((Math.max(...xs) - Math.min(...xs)) / (x1 - x0)) *
         ((Math.max(...ys) - Math.min(...ys)) / (y1 - y0));
}

function runTighten(pool) {
  const before = pool.map(areaOf);
  let improved = 0;
  for (const q of pool) {
    const cur = areaOf(q);
    const t = tighten(q);
    // Only take a real improvement; churning a domain for two percent is noise in
    // the diff and a re-verification for nothing.
    if (t && t.area > cur + 0.04) {
      q.xDomain = t.xDomain; q.yDomain = t.yDomain; improved++;
    }
  }
  const after = pool.map(areaOf);
  const mean = a => a.reduce((s, v) => s + v, 0) / a.length;
  const under = (a, v) => a.filter(x => x < v).length;
  console.log(`tightened ${improved} of ${pool.length} charts`);
  console.log(`  mean coverage   ${(mean(before) * 100).toFixed(0)}% -> ${(mean(after) * 100).toFixed(0)}%`);
  console.log(`  under 25% cover ${under(before, .25)} -> ${under(after, .25)}`);
  console.log(`  sparsest chart  ${(Math.min(...before) * 100).toFixed(0)}% -> ${(Math.min(...after) * 100).toFixed(0)}%`);
  return improved;
}

function main() {
  const pool = JSON.parse(fs.readFileSync(SRC_DATA, 'utf8'));

  if (process.argv.includes('--tighten')) {
    const n = runTighten(pool);
    if (process.argv.includes('--apply') && n) {
      fs.writeFileSync(SRC_DATA, JSON.stringify(pool, null, 2) + '\n');
      console.log(`wrote ${path.basename(SRC_DATA)}`);
    } else if (!process.argv.includes('--apply')) {
      console.log('(dry run — add --apply to write)');
    }
  }

  const rows = pool.map(audit);
  const fails = rows.filter(r => r.centre > MAX_CENTRE || r.lift < MIN_LIFT);

  const pct = (a, p) => [...a].sort((x, y) => x - y)[Math.floor(a.length * p)];
  const c = rows.map(r => r.centre), l = rows.map(r => r.lift);
  console.log(`pool ${rows.length}   curve exp(-(d/${SIGMA})^${SHAPE})`);
  console.log(`centre-click  min ${pct(c,0)}  p25 ${pct(c,.25)}  med ${pct(c,.5)}  p75 ${pct(c,.75)}  max ${pct(c,.99)}   (gate: <= ${MAX_CENTRE})`);
  console.log(`lift          min ${pct(l,0)}  p25 ${pct(l,.25)}  med ${pct(l,.5)}  p75 ${pct(l,.75)}  max ${pct(l,.99)}   (gate: >= ${MIN_LIFT})`);

  if (!fails.length) { console.log('\nFAIRNESS PASSED — every question rewards knowing the answer'); return 0; }

  console.log(`\n${fails.length} question(s) failed:`);
  const byId = Object.fromEntries(pool.map(q => [q.id, q]));
  for (const f of fails) {
    const why = [];
    if (f.centre > MAX_CENTRE) why.push(`centre ${f.centre} > ${MAX_CENTRE} (free points)`);
    if (f.lift < MIN_LIFT) why.push(`lift ${f.lift} < ${MIN_LIFT} (knowing barely helps)`);
    console.log(`  ${f.league} ${f.id}`);
    console.log(`      ${why.join('; ')}`);
    console.log(`      target sits at ${(f.xPos*100).toFixed(0)}% / ${(f.yPos*100).toFixed(0)}% of the axes`);
    if (process.argv.includes('--suggest')) {
      const r = repair(byId[f.id]);
      if (!r) { console.log('      no readable domain fixes this — replace the question'); continue; }
      const ok = r.after.centre <= MAX_CENTRE && r.after.lift >= MIN_LIFT;
      console.log(`      ${ok ? 'FIX  ' : 'best '} "xDomain": [${r.xDomain}], "yDomain": [${r.yDomain}]`);
      console.log(`            -> centre ${r.after.centre}, lift ${r.after.lift}${ok ? '' : '  (still failing — likely a weak question, not a bad axis)'}`);
    }
  }
  if (process.argv.includes('--apply')) {
    let fixed = 0;
    const unfixable = [];
    for (const f of fails) {
      const q = byId[f.id];
      const r = repair(q);
      if (r && r.after.centre <= MAX_CENTRE && r.after.lift >= MIN_LIFT) {
        q.xDomain = r.xDomain; q.yDomain = r.yDomain; fixed++;
      } else {
        unfixable.push(f.id);
      }
    }
    fs.writeFileSync(SRC_DATA, JSON.stringify(pool, null, 2) + '\n');
    console.log(`\napplied ${fixed} domain repair(s) to ${path.basename(SRC_DATA)}`);
    if (unfixable.length) {
      // Deliberately NOT auto-removed. Dropping content is a content decision and
      // wants a human looking at which question is leaving; the audit's job is to
      // make sure it cannot leave unnoticed.
      console.log(`${unfixable.length} still failing — no axis saves these, they need replacing:`);
      unfixable.forEach(id => console.log(`  ${id}`));
    }
    return unfixable.length ? 1 : 0;
  }

  console.log('\nFAIRNESS FAILED — re-window the domains (never move a verified stat)');
  console.log('  --suggest  print repaired domains     --apply  write them');
  return 1;
}

if (import.meta.url === `file://${process.argv[1]}`) process.exit(main());
