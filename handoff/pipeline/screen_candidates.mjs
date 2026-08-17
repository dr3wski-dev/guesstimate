/* Screen generated candidates through the fairness gate BEFORE anyone writes copy.
 *
 * WHY THIS SITS BETWEEN THE TWO STEPS IT DOES
 * build_questions.py emits candidates ranked by how interesting the underlying stat
 * line is. That ranking knows nothing about how the question will actually play —
 * it cannot, since play depends on the axis windows and the scoring curve. So the
 * expensive human step (reading the candidate, deciding it is a good question,
 * writing the fact copy against real sources) was being spent on candidates that
 * were going to fail the fairness gate at build time anyway.
 *
 * Screening first inverts that: the only candidates a human ever looks at are ones
 * that already reward knowing the answer. On the first run this dropped 2 of 55,
 * which sounds small until you notice the previous pool shipped 10 failures out of
 * 68 — because nothing was screening at all.
 *
 *   node pipeline/build_questions.py --league nba --top 60 --json cand-nba.json
 *   node pipeline/screen_candidates.mjs cand-nba.json [...]  -o passing.json
 *
 * Output is candidates only. They are NOT questions yet: every one still needs fact
 * copy written against a named source, and still has to clear verify_questions.py.
 * Nothing here bypasses either.
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { audit, MAX_CENTRE, MIN_LIFT } from './audit_fairness.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const POOL = path.join(HERE, '..', 'data', 'questions.json');

const args = process.argv.slice(2);
const oi = args.indexOf('-o');
const out = oi >= 0 ? args[oi + 1] : null;
// The `oi >= 0` guard matters: without it, a run with no -o flag has oi === -1, so
// `i !== oi + 1` excludes index 0 and the FIRST candidate file is silently dropped.
// That cost a whole league — 34 MLB candidates vanished from a batch and the tool
// cheerfully reported the smaller number as the total.
const files = args.filter((a, i) =>
  !a.startsWith('-') && (oi < 0 || (i !== oi && i !== oi + 1)));
if (files.length !== new Set(files).size) {
  console.error('duplicate candidate file passed twice'); process.exit(2);
}
if (!files.length) {
  console.error('usage: screen_candidates.mjs <candidates.json...> [-o passing.json]');
  process.exit(2);
}

const pool = JSON.parse(fs.readFileSync(POOL, 'utf8'));
const haveId = new Set(pool.map(q => q.id));
const havePlayer = new Set(pool.map(q => q.targetPlayer));

let cands = [];
for (const f of files) cands = cands.concat(JSON.parse(fs.readFileSync(f, 'utf8')));

/* Two questions on the same axes showing the same three reference players are the
 * same chart with a different answer. The fairness audit scores both as fine —
 * they are fine, individually — but a pool built this way feels repetitive in a way
 * players notice and cannot name. The generator produces these readily, because it
 * picks references at fixed quantiles: one batch offered four "career strikeouts vs
 * career home runs" questions all anchored on Lofton, Aaron and Henderson.
 *
 * Keyed on axes plus the reference set, ignoring order. The pool is included in the
 * key space so a new candidate can't duplicate a question that already shipped. */
const shape = q => q.xLabel + '|' + q.yLabel + '|' +
  q.referencePlayers.map(p => p.name).sort().join(',');
const seenShape = new Set(pool.map(shape));

const fresh = cands.filter(q => !haveId.has(q.id));
const scored = fresh.map(q => ({ q, a: audit(q) }));
const fair = scored.filter(r => r.a.centre <= MAX_CENTRE && r.a.lift >= MIN_LIFT);

// Best-first, so when several candidates share a chart the strongest one survives.
fair.sort((a, b) => b.a.lift - a.a.lift);
const pass = [];
let dupes = 0;
for (const r of fair) {
  const k = shape(r.q);
  if (seenShape.has(k)) { dupes++; continue; }
  seenShape.add(k);
  pass.push(r);
}
// Not a rejection — a returning player is fine and often welcome — but worth
// surfacing so a batch doesn't quietly become the same twelve names again.
const repeats = pass.filter(r => havePlayer.has(r.q.targetPlayer)).length;

const byLeague = {};
for (const r of pass) byLeague[r.q.league] = (byLeague[r.q.league] || 0) + 1;

console.log(`candidates ${cands.length}   new ids ${fresh.length}   ` +
            `pass fairness ${pass.length}   rejected ${fresh.length - pass.length}`);
console.log(`by league  ${JSON.stringify(byLeague)}   dropped as duplicate charts: ${dupes}   ` +
            `reusing a player already in the pool: ${repeats}`);
console.log(`pool would go ${pool.length} -> ${pool.length + pass.length} ` +
            `(${Math.floor((pool.length + pass.length) / 5)} days before a repeat)`);

pass.sort((a, b) => b.a.lift - a.a.lift);
console.log('\nranked by lift — write copy from the top down:');
for (const r of pass.slice(0, 25)) {
  console.log(`  lift ${String(r.a.lift).padStart(2)}  centre ${String(r.a.centre).padStart(2)}  ` +
              `${r.q.league}  ${r.q.targetPlayer}  —  ${r.q.xLabel} vs ${r.q.yLabel}`);
}

if (out) {
  fs.writeFileSync(out, JSON.stringify(pass.map(r => ({ ...r.q, _fair: r.a })), null, 1) + '\n');
  console.log(`\nwrote ${pass.length} to ${out} — still needs fact copy and verify_questions.py`);
}
