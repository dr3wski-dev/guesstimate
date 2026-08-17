/* ============================= DAILY SELECTION =============================
   Moved here from the game (now reference/statmap.html), which no longer has a copy —
   there is exactly one implementation of this logic and it now runs on the
   server. The functions themselves are unchanged from the versions that were
   built and tested in guesstimate-slider-legacy.html and then ported into the
   scatter build; the only edit is that `roundsForDate` takes the pool as an
   argument instead of reading a `QUESTION_POOL` global, because a Worker has no
   page-global to read. Behavior is identical: same date + same pool produce the
   same questions in the same order, which is the property the whole daily-game
   contract rests on.

   Keeping it pure and dependency-free is deliberate — it means the same file can
   be unit-tested in plain Node with no Workers runtime involved. */

// Fixed origin for the daily rotation so day numbering never shifts.
export const BAG_EPOCH = '2026-01-01';
export const DAILY_COUNT = 5;

export function hashString(str){
  let h = 0;
  for(let i=0;i<str.length;i++){ h = (Math.imul(31,h) + str.charCodeAt(i)) | 0; }
  return h >>> 0;
}
export function mulberry32(seed){
  return function(){
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
export function seededShuffle(arr, seed){
  const rng = mulberry32(seed);
  const a = [...arr];
  for(let i=a.length-1;i>0;i--){ const j=Math.floor(rng()*(i+1)); [a[i],a[j]]=[a[j],a[i]]; }
  return a;
}
// Fixed reference timezone so every player gets the same "today" regardless of
// their own. This used to run in the browser off the device clock, which meant a
// player could change their system clock and be served a different day's puzzle;
// it runs here now and the client no longer has a vote.
export function todayDateString(tz='America/New_York'){
  return new Date().toLocaleDateString('en-CA', { timeZone: tz }); // e.g. "2026-08-10"
}
export function selectDailyQuestions(dateStr, pool, count=5){
  const seed = hashString(dateStr);
  return seededShuffle(pool, seed).slice(0, Math.min(count, pool.length));
}

// Shuffled-bag anti-repeat rotation (ACTION_PLAN.md v1.1). Concatenate
// independently-shuffled copies of the pool end-to-end ("cycle 0", "cycle 1", ...)
// into one infinite sequence, then hand out `count` consecutive items per calendar
// day. Every item appears exactly once before any item repeats, and it's still a
// pure function of (dateStr, pool, count): no stored cursor, nothing to desync.
export function daysSince(dateStr, epoch){
  return Math.floor((Date.parse(dateStr + 'T00:00:00Z') - Date.parse(epoch + 'T00:00:00Z')) / 86400000);
}
export function puzzleNumber(dateStr){
  return Math.max(0, daysSince(dateStr, BAG_EPOCH)) + 1; // day one is #1
}
export function selectDailyBag(dateStr, pool, count=5){
  if(pool.length === 0) return [];
  const dayIndex = Math.max(0, daysSince(dateStr, BAG_EPOCH));
  const startIdx = dayIndex * count;
  const cycleShuffles = new Map();
  const result = [];
  for(let i = startIdx; i < startIdx + count; i++){
    const cycleIndex = Math.floor(i / pool.length);
    const posInCycle = i % pool.length;
    if(!cycleShuffles.has(cycleIndex)){
      cycleShuffles.set(cycleIndex, seededShuffle(pool, hashString(`bag-cycle-${cycleIndex}`)));
    }
    result.push(cycleShuffles.get(cycleIndex)[posInCycle]);
  }
  return result;
}
// Questions for the daily set on `dateStr` — used both for today and for
// replaying the day a challenge link was sent from. The pool-size branch is
// preserved exactly: the bag rotation needs at least a full day's worth of
// questions, and below that it falls back to the plain seeded selection.
/* Optional hand-scheduled days, authored as a spreadsheet and compiled to
   data/schedule.json by pipeline/import_questions.py — `{ "2026-09-01": ["id", …] }`.
   A pinned date serves exactly those questions; every other date keeps falling back
   to the shuffled bag, so this is an override rather than a replacement and the
   selection stays a pure function of (date, pool, schedule).

   Questions appearing anywhere in the schedule are removed from the bag entirely.
   Without that, the bag could serve one of a themed day's questions the week
   before and spoil it — and the exclusion has to be date-independent, or replaying
   an old challenge link would stop reproducing that day's puzzle. */
export function bagPool(pool, schedule){
  const pinned = new Set(Object.values(schedule || {}).flat());
  if(pinned.size === 0) return pool;
  const rest = pool.filter(q => !pinned.has(q.id));
  // If scheduling has eaten so much of the pool that an unscheduled day can't be
  // filled, the schedule is the broken thing — serve from everything rather than
  // hand the player a short round.
  return rest.length >= DAILY_COUNT ? rest : pool;
}
export function roundsForDate(dateStr, pool, schedule){
  const pins = schedule && schedule[dateStr];
  if(pins && pins.length){
    const byId = new Map(pool.map(q => [q.id, q]));
    const picked = pins.map(id => byId.get(id)).filter(Boolean);
    // Every pinned id unknown means the schedule is stale against the pool; fall
    // through to the bag rather than serving an empty round.
    if(picked.length) return picked;
  }
  const usable = bagPool(pool, schedule);
  return usable.length >= DAILY_COUNT
    ? selectDailyBag(dateStr, usable, DAILY_COUNT)
    : selectDailyQuestions(dateStr, usable, usable.length);
}
