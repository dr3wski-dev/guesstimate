/* Is the games manifest consistent with everything that has to agree with it?
 *
 * WHY THIS EXISTS
 * Splitting one game into several turns a single consistent thing into four that
 * have to be kept in step: data/games.json says a game exists, questions.json has
 * to actually contain questions for it, data/schedule-<id>.json has to pin its
 * days, the Worker has to import that file, and build_site.py has to emit a page
 * at its slug. Every one of those can be missing on its own, and the failure mode
 * is the project's worst one: a game that loads, answers, and serves nothing or
 * serves the wrong game's questions. None of that errors anywhere.
 *
 * So the rule is: a game marked "live" must be complete on every axis, and this
 * fails the build if it is not. A game marked "soon" or "blocked" is allowed to be
 * empty — that is what those statuses mean — but its shape is still checked, so a
 * typo in a slug or a missing note is caught before anyone flips it to live.
 *
 *   node pipeline/check_games.mjs
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { DAILY_COUNT, poolForGame, gameOf, MAIN_GAME } from '../worker/src/selection.js';
import { SCHEDULES } from '../worker/src/index.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DATA = path.join(HERE, '..', 'data');
const read = f => JSON.parse(fs.readFileSync(path.join(DATA, f), 'utf8'));

const GAMES = read('games.json');
const POOL = read('questions.json');
const STATUSES = new Set(['live', 'soon', 'blocked']);
const problems = [];
const notes = [];

const slugs = new Map();
for (const [id, g] of Object.entries(GAMES)) {
  const where = `games.json/${id}`;
  if (!/^[a-z][a-z0-9-]*$/.test(id)) problems.push(`${where}: id must be lowercase slug-safe`);
  for (const field of ['name', 'title', 'short', 'blurb', 'epoch', 'status']) {
    if (!g[field]) problems.push(`${where}: missing "${field}"`);
  }
  if (!STATUSES.has(g.status)) {
    problems.push(`${where}: status "${g.status}" is not one of ${[...STATUSES].join(', ')}`);
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(g.epoch || '')) problems.push(`${where}: epoch is not a date`);
  // A non-live game is a promise with a reason attached. Shipping one without the
  // reason is how a roadmap turns into a dead link nobody can explain.
  if (g.status !== 'live' && !g.note) {
    problems.push(`${where}: a "${g.status}" game must carry a note saying why`);
  }
  // Slug "" is the root, which only the original game may own.
  if (g.slug === '' && id !== MAIN_GAME) problems.push(`${where}: only "${MAIN_GAME}" may sit at the root`);
  if (g.slug !== '' && !/^[a-z][a-z0-9-]*$/.test(g.slug || '')) {
    problems.push(`${where}: slug "${g.slug}" is not a safe path segment`);
  }
  if (slugs.has(g.slug)) problems.push(`${where}: slug "${g.slug}" is already used by ${slugs.get(g.slug)}`);
  slugs.set(g.slug, id);
}

// Every question must belong to a game that exists. A typo'd game id would drop the
// question out of every pool at once: it would never be served, never be scheduled,
// and never be reported missing, because nothing iterates questions by game.
const unknown = new Map();
for (const q of POOL) {
  const g = gameOf(q);
  if (!GAMES[g]) unknown.set(g, (unknown.get(g) || 0) + 1);
}
for (const [g, n] of unknown) {
  problems.push(`questions.json: ${n} question(s) claim game "${g}", which is not in the manifest`);
}

const today = new Date().toLocaleDateString('en-CA', { timeZone: 'America/New_York' });

for (const [id, g] of Object.entries(GAMES)) {
  const pool = poolForGame(POOL, id);
  const schedule = SCHEDULES[id];
  if (g.status !== 'live') {
    notes.push(`${id.padEnd(5)} ${g.status.padEnd(8)} ${String(pool.length).padStart(4)} questions`);
    continue;
  }
  if (!schedule) {
    problems.push(`${id}: live, but the Worker has no schedule imported for it `
      + `(add it to SCHEDULES in worker/src/index.js)`);
  }
  // Short of a full day the selection silently serves fewer than five questions,
  // which looks like a content decision rather than a fault.
  if (pool.length < DAILY_COUNT) {
    problems.push(`${id}: live with ${pool.length} question(s) — a day needs ${DAILY_COUNT}`);
  }
  // Pinning is what makes a played day immutable. A live game whose schedule does
  // not reach today falls through to the bag, and the next content addition re-deals
  // the day somebody is part-way through.
  if (schedule && !schedule[today]) {
    problems.push(`${id}: live, but data/schedule-*.json pins nothing for today (${today}) `
      + `— today would fall through to the bag`);
  }
  if (new Date(g.epoch) > new Date(today)) {
    problems.push(`${id}: live, but its epoch ${g.epoch} is in the future`);
  }
  notes.push(`${id.padEnd(5)} ${'live'.padEnd(8)} ${String(pool.length).padStart(4)} questions, `
    + `${Object.keys(schedule || {}).length} days pinned`);
}

console.log(`games: ${Object.keys(GAMES).length}`);
for (const n of notes) console.log('  ' + n);
for (const p of problems) console.log('  ' + p);
if (problems.length) {
  console.error(`\n${problems.length} problem(s) with the games manifest`);
  process.exit(1);
}
console.log('games manifest is consistent');
