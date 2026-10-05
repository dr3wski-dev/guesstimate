/* ============================= DAILY SELECTION =============================
   Moved here from the game (now reference/statmap.html), which no longer has a copy —
   there is exactly one implementation of this logic and it now runs on the
   server. The functions themselves are unchanged from the versions that were
   built and tested in the original 1D slider prototype and then ported into the
   scatter build; the only edit is that `roundsForDate` takes the pool as an
   argument instead of reading a `QUESTION_POOL` global, because a Worker has no
   page-global to read. Behavior is identical: same date + same pool produce the
   same questions in the same order, which is the property the whole daily-game
   contract rests on.

   Keeping it pure and dependency-free is deliberate — it means the same file can
   be unit-tested in plain Node with no Workers runtime involved. */

// Fixed origin for the daily rotation so day numbering never shifts.
// Launch day. Puzzle numbering counts from here, so day one is #1 rather than
// implying hundreds of puzzles nobody ever played. It also anchors the shuffled
// bag, so moving it reshuffles which questions land on which date — safe before
// launch, disruptive after, because it would renumber every puzzle a player has
// already shared.
export const BAG_EPOCH = '2026-08-17';
export const DAILY_COUNT = 5;

/* ------------------------------- GAMES -------------------------------------
   One pool, several games. A game is a named slice of the pool with its own
   daily rotation, its own epoch and its own puzzle numbering, so "NBA Careers
   #1" can be somebody's first ever puzzle on a day the original game is on
   #50. Membership is a field on the question, not a guess from its labels:
   `game: "nba"`. The original 600 questions carry no field at all and mean
   "main", which keeps hard mode's pool byte-identical to what it has always
   been — see the seed comment in selectDailyBag for why that matters.

   The manifest itself (names, slugs, epochs, which games are open) lives in
   data/games.json and is read by the Worker, the builder and the page. This
   file stays data-free so it can still be unit-tested in plain Node. */
export const MAIN_GAME = 'main';
export function gameOf(q){ return q.game || MAIN_GAME; }
export function poolForGame(pool, gameId = MAIN_GAME){
  return pool.filter(q => gameOf(q) === gameId);
}

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
export function puzzleNumber(dateStr, epoch = BAG_EPOCH){
  return Math.max(0, daysSince(dateStr, epoch)) + 1; // day one is #1
}
/* The shuffle seed for a cycle of a game's bag.

   `main` keeps the bare `bag-cycle-N` string it has always used, with no game
   id in it. That asymmetry is deliberate and must not be tidied up: the seed
   decides which questions land on which date, so changing it for main would
   re-deal every day in the calendar — including days people have already
   played and shared a score for. Played days are immutable. Every other game
   is namespaced, so two games holding similar pools don't march in step. */
function bagSeed(gameId, cycleIndex){
  return gameId === MAIN_GAME ? `bag-cycle-${cycleIndex}` : `bag-cycle-${gameId}-${cycleIndex}`;
}
export function selectDailyBag(dateStr, pool, count=5, epoch = BAG_EPOCH, gameId = MAIN_GAME){
  if(pool.length === 0) return [];
  const dayIndex = Math.max(0, daysSince(dateStr, epoch));
  const startIdx = dayIndex * count;
  const cycleShuffles = new Map();
  const result = [];
  for(let i = startIdx; i < startIdx + count; i++){
    const cycleIndex = Math.floor(i / pool.length);
    const posInCycle = i % pool.length;
    if(!cycleShuffles.has(cycleIndex)){
      cycleShuffles.set(cycleIndex, seededShuffle(pool, hashString(bagSeed(gameId, cycleIndex))));
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
/* `game` is `{ id, epoch }` — defaulting to the original game, so every existing
   caller keeps its exact behaviour. The pool handed in is already this game's
   slice (see poolForGame); the schedule is global and simply doesn't match on
   dates pinned for a different game's questions, because none of those ids are
   in this pool. */
export function roundsForDate(dateStr, pool, schedule, game = {}){
  const gameId = game.id || MAIN_GAME;
  const epoch = game.epoch || BAG_EPOCH;
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
    ? selectDailyBag(dateStr, usable, DAILY_COUNT, epoch, gameId)
    : selectDailyQuestions(dateStr, usable, usable.length);
}
