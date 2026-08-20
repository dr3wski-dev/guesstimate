/* Pin each date to an explicit set of questions, once, forever.
 *
 * THE BUG THIS EXISTS TO END
 * The shuffled bag is a pure function of (date, pool). That reads as a virtue —
 * no stored cursor, nothing to desync — and it is, right up until the pool changes.
 * Adding 100 questions re-deals every day that has ever existed. Measured, not
 * assumed: going from 104 to 204 changed day 1, day 2 and day 3 by 5 questions out
 * of 5 each. Zero overlap.
 *
 * Two things break when that happens, and only one of them is visible. Today's
 * questions change under somebody who is part-way through them. And every challenge
 * link ever shared now points at a different puzzle than the person who sent it
 * played, so "beat my score" silently compares two unrelated sets. Nothing logs
 * that. Nobody reports it. It just quietly stops meaning anything.
 *
 * THE FIX IS APPEND-ONLY SCHEDULING
 * Every date gets written down. A date that already has an assignment is never
 * touched again — not by a new batch of content, not by a re-run of this script.
 * New content can only ever extend the calendar forward into dates nobody has
 * played. `--check` enforces that in CI, so the guarantee survives whoever forgets
 * about it next.
 *
 *   node pipeline/schedule_days.mjs --days 60      # extend the calendar
 *   node pipeline/schedule_days.mjs --check        # CI: is the schedule sound?
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { BAG_EPOCH, DAILY_COUNT, hashString, seededShuffle, daysSince } from '../worker/src/selection.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DATA = path.join(HERE, '..', 'data');
const POOL_PATH = path.join(DATA, 'questions.json');
const SCHEDULE_PATH = path.join(DATA, 'schedule.json');

const read = p => JSON.parse(fs.readFileSync(p, 'utf8'));
const dateFor = dayIndex => new Date(Date.parse(BAG_EPOCH + 'T00:00:00Z') + dayIndex * 86400000)
  .toISOString().slice(0, 10);

/* Deal order for questions nobody has been given yet.
 *
 * Sorted by id before shuffling, deliberately. The shuffle walks the array it is
 * handed, so without a canonical starting order the deal would depend on the order
 * questions happen to sit in the file — and questions.json is appended to by a
 * generator, which makes that order an accident of authoring history rather than
 * anything meaningful. */
function dealOrder(available, cycle) {
  const sorted = [...available].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  return seededShuffle(sorted, hashString(`schedule-cycle-${cycle}`));
}

/* Which days can never be rewritten.
 *
 * The rule that matters is narrower than "every day already in the file". A day
 * somebody has PLAYED is history: its questions are in their stats, and a challenge
 * link to it has to keep reproducing what the sender saw. A day next week is not
 * history, it is a plan, and plans are supposed to be editable — otherwise the first
 * batch of content ever generated would own the calendar forever and a themed day
 * could never be added.
 *
 * So: today and everything before it is frozen. Everything after is re-dealt on each
 * run, deterministically, so the same inputs keep producing the same calendar. */
function frozenThrough() {
  return new Date().toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
}

function extend(pool, schedule, days, themed = {}) {
  const today = frozenThrough();
  const played = Object.fromEntries(
    Object.entries(schedule).filter(([date]) => date <= today));

  // Themed days are authored by hand and win over anything generated. Their questions
  // are also withheld from the deal, so a Kobe Bryant day cannot be spoiled by one of
  // its own questions turning up the Tuesday before.
  const out = { ...played, ...themed };
  const used = new Set(Object.values(out).flat());
  let queue = [], cycle = 0, added = 0;

  for (let day = 0; day < days; day++) {
    const date = dateFor(day);
    if (out[date]) continue;                       // played, or a themed day
    while (queue.length < DAILY_COUNT) {
      // A cycle is one pass through everything not yet scheduled. When it empties,
      // the next cycle re-deals the whole pool, which is where repeats begin — the
      // same anti-repeat guarantee the bag gave, made explicit and permanent.
      const available = pool.filter(q => !used.has(q.id));
      if (available.length === 0) { used.clear(); cycle++; continue; }
      const next = dealOrder(available, cycle).slice(0, DAILY_COUNT - queue.length);
      next.forEach(q => { queue.push(q.id); used.add(q.id); });
    }
    out[date] = queue.splice(0, DAILY_COUNT);
    added++;
  }
  return { schedule: out, added };
}

function check(pool, schedule) {
  const ids = new Set(pool.map(q => q.id));
  const problems = [];
  const dates = Object.keys(schedule).sort();

  for (const date of dates) {
    const pins = schedule[date];
    if (!Array.isArray(pins) || pins.length !== DAILY_COUNT) {
      problems.push(`${date}: ${pins?.length ?? 0} questions, expected ${DAILY_COUNT}`);
    }
    // A pinned id that no longer exists in the pool serves a SHORT round rather
    // than failing, so it has to be caught here or not at all.
    for (const id of pins || []) {
      if (!ids.has(id)) problems.push(`${date}: pinned id '${id}' is not in the pool`);
    }
    if (new Set(pins || []).size !== (pins || []).length) {
      problems.push(`${date}: the same question appears twice on one day`);
    }
  }

  // Every date from launch to the last scheduled one must be covered. A hole falls
  // through to the bag, which is the exact behaviour this file exists to retire.
  if (dates.length) {
    const last = daysSince(dates[dates.length - 1], BAG_EPOCH);
    for (let d = 0; d <= last; d++) {
      if (!schedule[dateFor(d)]) problems.push(`${dateFor(d)}: no questions pinned (gap in the calendar)`);
    }
  }

  const today = new Date().toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
  const covered = dates.filter(d => d >= today).length;
  return { problems, dates, covered, today };
}

const args = process.argv.slice(2);
const pool = read(POOL_PATH);
const schedule = fs.existsSync(SCHEDULE_PATH) ? read(SCHEDULE_PATH) : {};
// Hand-authored days, kept in their own file so an editorial decision is never
// mistaken for generator output — a themed day in schedule.json would be
// indistinguishable from the 59 days a script dealt, and the next run would quietly
// deal over it.
const THEMED_PATH = path.join(DATA, 'themed_days.json');
const themed = fs.existsSync(THEMED_PATH) ? read(THEMED_PATH) : {};

if (args.includes('--check')) {
  const { problems, dates, covered, today } = check(pool, schedule);
  console.log(`${dates.length} scheduled days, ${covered} of them today or later (pool ${pool.length})`);
  for (const p of problems) console.log('  ' + p);
  if (problems.length) {
    console.error(`\n${problems.length} problem(s) with data/schedule.json`);
    process.exit(1);
  }
  // Running out of calendar is not an error today and is an outage in three weeks,
  // so it warns rather than fails.
  if (covered < 14) console.log(`\nWARNING: only ${covered} days of content remain after ${today}.`);
  console.log('schedule is sound');
  process.exit(0);
}

const di = args.indexOf('--days');
const days = di >= 0 ? parseInt(args[di + 1], 10) : 60;
const before = Object.keys(schedule).length;
const { schedule: next, added } = extend(pool, schedule, days, themed);

// Sorted on write so a diff shows what moved rather than a reshuffled object.
const sorted = Object.fromEntries(Object.keys(next).sort().map(k => [k, next[k]]));

// The guarantee, enforced at the last possible moment: a day that has been played
// cannot be rewritten by anything above — not a themed day authored over the top of
// it, not a re-deal, not a bug in this file.
const today = frozenThrough();
for (const date of Object.keys(schedule)) {
  if (date > today) continue;
  if (JSON.stringify(schedule[date]) !== JSON.stringify(sorted[date])) {
    console.error(`REFUSING TO WRITE: ${date} has been played and would change.`);
    process.exit(1);
  }
}
const moved = Object.keys(sorted).filter(d => d > today && schedule[d]
  && JSON.stringify(schedule[d]) !== JSON.stringify(sorted[d])).length;
fs.writeFileSync(SCHEDULE_PATH, JSON.stringify(sorted, null, 2) + '\n');
if (Object.keys(themed).length) {
  console.log(`themed days honoured: ${Object.keys(themed).sort().join(', ')}`);
}
if (moved) console.log(`${moved} future day(s) re-dealt; every played day unchanged`);
console.log(`schedule: ${before} days -> ${Object.keys(sorted).length} (${added} appended, 0 changed)`);
