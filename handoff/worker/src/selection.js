/* ============================= DAILY SELECTION =============================
   Moved here from guesstimate-scatter.html, which no longer contains a copy —
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
export function roundsForDate(dateStr, pool){
  return pool.length >= DAILY_COUNT
    ? selectDailyBag(dateStr, pool, DAILY_COUNT)
    : selectDailyQuestions(dateStr, pool, pool.length);
}
