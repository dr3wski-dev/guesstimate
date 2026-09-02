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
// The person behind a question, ignoring which season it is about.
function personOf(q) {
  return q.targetPlayer.split(',')[0].trim();
}

/* What a player actually experiences as "the same question again".
 *
 * Not the athlete — the CHART. Career doubles against career home runs is one
 * puzzle shape, and it does not become a different one because the dot is Sammy
 * Sosa this time instead of Mike Schmidt.
 *
 * The pair of axis labels, not the id prefix. The prefix looks like the right key
 * and is not: `mlb-so` covers strikeouts against ERA, which is a pitcher, AND
 * strikeouts against batting average, which is a hitter. Keyed on the prefix those
 * two are one shape, so a Tom Seaver chart and a Carlos Delgado chart would block
 * each other while being nothing alike — over-constraining real variety and making
 * pitching queue behind hitting for a single slot. Keyed on the labels the pool has
 * 57 shapes rather than 47, and each one is what a player actually sees. */
function archetypeOf(q) {
  return `${q.xLabel} / ${q.yLabel}`;
}

/* How many days a chart shape sits out before it can come back.
 *
 * The league rotation fixed clumping one level up and stopped there, so nothing
 * was watching the shapes. Measured over the calendar as it stood: an archetype
 * repeated on consecutive days 0.79 times per day, "career doubles / career home
 * runs" went out four days in five, and 2026-09-05 was dealt TWO
 * receptions/receiving-yards charts in the same five-question puzzle.
 *
 * The cause is that the deal is one shuffled list consumed front to back, so
 * questions that land next to each other in the shuffle land on days next to each
 * other too. Shuffling harder does not fix that — only constraining the deal does,
 * which is the same lesson ROTATION already learned about leagues.
 *
 * Five is chosen to be satisfiable rather than ideal: the thinnest league carries
 * about eleven archetypes and draws roughly 1.7 slots a day, so a five-day memory
 * is comfortably inside what the pool can actually honour. */
const ARCHETYPE_COOLDOWN = 5;

/* Names a person actually looked at and vouched for.
 *
 * athlete_pool.csv carries a Tier column — Stud, Sneaky Stud, Role Player — filled
 * in by hand. 173 names were later added on objective bars instead (8 All-Star
 * selections, or 400 home runs, or 250 wins, and so on) and never got one. Those
 * bars are honest measures of a career and a poor measure of whether anybody has
 * heard of the man: they let in Ewell Blackwell and Bucky Walters on the same
 * footing as Steve Carlton.
 *
 * The damage is concentrated in baseball, because that is where the expansion
 * landed: 64% of MLB answers are untiered against 6% of NBA ones. Left alone the
 * calendar was dealing 24 of the next 21 days' 35 MLB slots to names nobody had
 * vetted, which is what "these players are so random" is describing. */
function curatedNames(csvPath) {
  const names = new Set();
  const text = fs.readFileSync(csvPath, 'utf8').split('\n');
  const head = text[0].split(',');
  const iName = head.indexOf('Player'), iTier = head.indexOf('Tier');
  for (const line of text.slice(1)) {
    const cell = line.split(',');
    if (cell.length <= iTier) continue;
    if (cell[iTier].trim()) names.add(cell[iName].trim());
  }
  return names;
}

/* How many unvetted names one puzzle may contain.
 *
 * A cap rather than a ban, and a cap rather than a cut-list. Untiered does not mean
 * obscure — Ichiro Suzuki, Cal Ripken, Willie Stargell and Rich Gossage sit in the
 * same bucket as the deep cuts, because the bucket means "never judged", not "not
 * famous". Banning it would throw them out; hand-cutting it would mean adjudicating
 * 147 names on taste and getting some wrong.
 *
 * Two out of five leaves every puzzle at least three names a player recognises,
 * which is the thing that was actually broken, and needs no opinion about any
 * individual. Tiering the rest properly is the real fix and is a content job, not a
 * scheduling one. */
const MAX_UNCURATED = 2;

function frozenThrough() {
  return new Date().toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
}

/* The three-day league rotation.
 *
 * 2/2/1, 1/2/2, 2/1/2 — which sums to five per league per cycle, dead even, without
 * any single day reading as a themed day.
 *
 * It exists because the plain deal clumps. Puzzle #4 shipped as five NBA questions,
 * and a football fan got nothing that day; five of the first 77 days were
 * single-league. Shuffling a pool that is 38% basketball produces all-basketball days
 * at exactly the rate chance says it should, and no amount of re-shuffling fixes a
 * distribution — only constraining the deal does.
 *
 * A balanced rotation is only as long as the smallest league times three, which is
 * why this could not be switched on earlier: at 63 MLB questions it would have
 * SHORTENED the calendar from 41 days to 38. It is on now because every league
 * clears 150.
 */
const ROTATION = [
  { NBA: 2, NFL: 2, MLB: 1 },
  { NBA: 1, NFL: 2, MLB: 2 },
  { NBA: 2, NFL: 1, MLB: 2 },
];

function extend(pool, schedule, days, themed = {}, curated = new Set()) {
  const today = frozenThrough();
  const played = Object.fromEntries(
    Object.entries(schedule).filter(([date]) => date <= today));

  // Themed days are authored by hand and win over anything generated. Their questions
  // are also withheld from the deal, so a Kobe Bryant day cannot be spoiled by one of
  // its own questions turning up the Tuesday before.
  const out = { ...played, ...themed };
  const used = new Set(Object.values(out).flat());
  const byId = new Map(pool.map(q => [q.id, q]));
  let cycle = 0, added = 0, relaxed = 0;

  // The day index each chart shape last went out on. Seeded as the calendar is
  // walked — including the days this run skips — so the first newly dealt day knows
  // what yesterday actually served rather than starting from a blank memory.
  const lastSeen = new Map();
  const remember = (day, ids) => {
    for (const id of ids) {
      const q = byId.get(id);
      if (q) lastSeen.set(archetypeOf(q), day);
    }
  };

  /* Deal one day without touching anything shared, so a failed attempt costs
   * nothing. `cooldown` is how many days an archetype must have sat out; the caller
   * lowers it and retries rather than letting a day come up short. */
  function dealDay(day, cooldown, maxUncurated) {
    const want = { ...ROTATION[day % ROTATION.length] };
    const seen = new Set(used);
    const onDeck = new Set(), shapes = new Set();
    const queue = [];
    let cyc = cycle, uncurated = 0;

    for (let guard = 0; queue.length < DAILY_COUNT && guard < 8; guard++) {
      // A cycle is one pass through everything not yet scheduled. When it empties,
      // the next cycle re-deals the whole pool, which is where repeats begin — the
      // same anti-repeat guarantee the bag gave, made explicit and permanent.
      const available = pool.filter(q => !seen.has(q.id));
      if (available.length === 0) { seen.clear(); cyc++; continue; }
      let took = 0;
      for (const q of dealOrder(available, cyc)) {
        if (queue.length >= DAILY_COUNT) break;
        if (!want[q.league]) continue;             // this league is filled for today
        // Never the same person twice on one day. A player can answer more than one
        // question now — different seasons — so the deal could otherwise put Kobe
        // Bryant in rounds two and four of one puzzle, which reads as a bug.
        const p = personOf(q);
        if (onDeck.has(p)) continue;
        // Never the same chart shape twice on one day either, at any cooldown. Two
        // receptions-against-receiving-yards charts in one five-question puzzle read
        // as the game repeating itself, and the calendar had one dealt for
        // 2026-09-05 before this existed.
        const a = archetypeOf(q);
        if (shapes.has(a)) continue;
        if (cooldown && day - (lastSeen.get(a) ?? -Infinity) < cooldown) continue;
        // Keep most of the puzzle to names somebody vetted.
        const vetted = curated.has(p);
        if (!vetted && uncurated >= maxUncurated) continue;
        if (!vetted) uncurated++;
        onDeck.add(p); shapes.add(a); want[q.league]--;
        queue.push(q.id); seen.add(q.id); took++;
      }
      // Nothing taken with stock still on the shelf means the remaining questions
      // cannot satisfy the quota — start the next cycle rather than spin.
      if (took === 0) { seen.clear(); cyc++; }
    }
    return { queue, seen, cycle: cyc };
  }

  for (let day = 0; day < days; day++) {
    const date = dateFor(day);
    // Played and themed days are not dealt, but they are still days a player saw, so
    // the cooldown has to count them. Skipping them silently is how a themed Kobe day
    // would let the chart it used come straight back the morning after.
    if (out[date]) { remember(day, out[date]); continue; }

    // Ask for everything, then give ground in a fixed order rather than shipping a
    // short day. Chart spacing yields before the name cap down to three days, since
    // a shape returning on the fourth day is a much smaller thing than a puzzle full
    // of strangers; below that the cap gives way too. A short day is never an
    // option — five questions is the game.
    //
    // The rotation slot is keyed on the day index, not on how many days this run
    // happens to fill, so a day's league mix does not depend on when it was dealt.
    let attempt = null;
    for (const [cooldown, cap] of [
      [ARCHETYPE_COOLDOWN, MAX_UNCURATED], [4, MAX_UNCURATED], [3, MAX_UNCURATED],
      [3, MAX_UNCURATED + 1], [2, MAX_UNCURATED + 1],
      [2, DAILY_COUNT], [0, DAILY_COUNT],
    ]) {
      attempt = dealDay(day, cooldown, cap);
      if (attempt.queue.length === DAILY_COUNT) {
        if (cooldown < ARCHETYPE_COOLDOWN || cap > MAX_UNCURATED) relaxed++;
        break;
      }
    }

    out[date] = attempt.queue.slice(0, DAILY_COUNT);
    used.clear();
    for (const id of attempt.seen) used.add(id);
    for (const id of out[date]) used.add(id);
    cycle = attempt.cycle;
    remember(day, out[date]);
    added++;
  }
  return { schedule: out, added, relaxed };
}

function check(pool, schedule, curated = new Set()) {
  const ids = new Set(pool.map(q => q.id));
  const byId = new Map(pool.map(q => [q.id, q]));
  const problems = [];
  const dates = Object.keys(schedule).sort();

  for (const date of dates) {
    const pins = schedule[date];
    if (!Array.isArray(pins) || pins.length !== DAILY_COUNT) {
      problems.push(`${date}: ${pins?.length ?? 0} questions, expected ${DAILY_COUNT}`);
    }
    // A pinned id that no longer exists in the pool serves a SHORT round rather
    // than failing, so it has to be caught here or not at all.
    //
    // On a day that has been PLAYED this is the more serious version of the same
    // thing: a challenge link to that day has to keep reproducing what the sender
    // saw, so a question that has ever been served can never be deleted, even when
    // its whole archetype is retired. Retiring the usage-rate charts hit exactly
    // this — one of them had gone out that morning — and the message says so,
    // because "not in the pool" alone reads like a typo rather than like history
    // being rewritten.
    const played = date <= new Date().toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
    for (const id of pins || []) {
      if (!ids.has(id)) {
        problems.push(played
          ? `${date}: '${id}' was SERVED on this day and is no longer in the pool. `
            + `A question that has been played cannot be removed — restore it.`
          : `${date}: pinned id '${id}' is not in the pool`);
      }
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

  /* The deal makes two promises the deal alone cannot keep.
   *
   * Both of these are properties of the OUTPUT, so checking them here rather than
   * trusting extend() is the difference between a guarantee and an intention. The
   * whole reason they exist is that nothing was watching: the calendar had a day
   * dealt two receptions-against-receiving-yards charts, and career doubles against
   * career home runs went out four days in five, and every gate in the project was
   * green throughout.
   *
   * Only future days are judged. The played ones predate the constraint, and two of
   * them do repeat a chart internally — that is history, not a fault, and failing on
   * it would make the gate unfixable. */
  const quality = [];
  const future = dates.filter(d => d > today);
  const shapesOn = d => (schedule[d] || []).map(id => byId.get(id))
    .filter(Boolean).map(archetypeOf);

  for (const d of future) {
    const s = shapesOn(d);
    if (new Set(s).size !== s.length) {
      quality.push(`${d}: the same chart appears twice in one puzzle`);
    }
    const strangers = (schedule[d] || []).map(id => byId.get(id)).filter(Boolean)
      .filter(q => !curated.has(personOf(q)));
    if (strangers.length > MAX_UNCURATED) {
      quality.push(`${d}: ${strangers.length} un-tiered names in one puzzle `
        + `(cap is ${MAX_UNCURATED}) — ${strangers.map(personOf).join(', ')}`);
    }
  }
  for (let i = 1; i < future.length; i++) {
    const shared = shapesOn(future[i]).filter(a => shapesOn(future[i - 1]).includes(a));
    for (const a of shared) {
      quality.push(`${future[i]}: "${a}" also went out the day before`);
    }
  }

  const covered = dates.filter(d => d >= today).length;
  return { problems, quality, dates, covered, today };
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
  const curatedCheck = curatedNames(path.join(DATA, 'athlete_pool.csv'));
  const { problems, quality, dates, covered, today } = check(pool, schedule, curatedCheck);
  console.log(`${dates.length} scheduled days, ${covered} of them today or later (pool ${pool.length})`);
  for (const p of problems) console.log('  ' + p);
  if (problems.length) {
    console.error(`\n${problems.length} problem(s) with data/schedule.json`);
    process.exit(1);
  }
  /* A repeated chart is not corruption, so this warns rather than fails: as the
   * calendar runs further ahead of the pool the spacing has to give somewhere, and a
   * gate that fails on that would be telling you to write more questions by breaking
   * the build. It is loud because the alternative is what already happened — nobody
   * noticing for sixteen days. */
  if (quality.length) {
    console.log(`\n${quality.length} variety warning(s) on upcoming days:`);
    for (const q of quality.slice(0, 20)) console.log('  ' + q);
    if (quality.length > 20) console.log(`  ...and ${quality.length - 20} more`);
    console.log('  Re-run `node pipeline/schedule_days.mjs --days N` to re-deal, or add questions.');
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
const curated = curatedNames(path.join(DATA, 'athlete_pool.csv'));
const { schedule: next, added, relaxed } = extend(pool, schedule, days, themed, curated);

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
// Worth saying out loud: a day that needed a constraint loosened is a day the pool
// was too thin to serve properly, which is a content signal rather than a bug.
if (relaxed) console.log(`${relaxed} day(s) needed chart spacing or the name cap relaxed to fill`);
console.log(`schedule: ${before} days -> ${Object.keys(sorted).length} (${added} appended, 0 changed)`);
