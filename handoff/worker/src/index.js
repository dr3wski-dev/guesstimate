/* StatMap daily-questions API — one stateless Cloudflare Worker.
   No database, no accounts, no auth, no stored state of any kind: every response
   is a pure function of (server clock, bundled question pool).

   It exists to close two gaps that are unfixable in a client that holds the whole
   pool:
   1. The client used to fetch data/questions.json, so every future day's answers
      were one dev-tools panel away. Only the selected day's questions are ever
      sent now.
   2. "Today" used to come from the device clock, so setting your system clock
      back replayed old puzzles and inflated streaks. The date is decided here.

   Worth being precise about what this does NOT fix, because it would be easy to
   over-read: the five questions being played still travel to the browser with
   their answers attached (targetX/targetY/fact), because scoring and the reveal
   happen client-side. A determined player can still read today's five answers
   out of the network tab. Hiding those too would mean posting guesses to the
   server for scoring, which is a real backend with real abuse surface — out of
   scope by ACTION_PLAN.md section 6, and not what the leak was about. */
// Import attribute form (`with { type: 'json' }`) rather than a bare JSON import,
// so the identical file runs unmodified both under Wrangler/esbuild and in plain
// Node — which is what lets the test suite exercise the real Worker without a
// Workers runtime in the loop.
import POOL from '../../data/questions.json' with { type: 'json' };
// Optional pinned days. Bundled the same way as the pool so the Worker stays a
// pure function of its bundle — an empty object simply means "no pinned days".
import SCHEDULE from '../../data/schedule.json' with { type: 'json' };
import { roundsForDate, puzzleNumber, todayDateString, BAG_EPOCH } from './selection.js';

const json = (body, cacheControl, extra = {}) => new Response(JSON.stringify(body), {
  headers: {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': cacheControl,
    // Which pool this Worker is actually holding. It is the same fingerprint the
    // cache key uses, so it changes when and only when the answers could have
    // changed, and it is a hash — it discloses nothing about the content.
    //
    // It exists so "did the deploy land?" is a question with an answer. A Worker
    // that uploads a version without releasing it, or an edge that keeps serving
    // yesterday, both look completely healthy from outside: the API responds, the
    // questions are well-formed, and they are the wrong ones. Comparing this header
    // against the fingerprint of the checked-out pool turns that into a failure the
    // deploy job can catch, which is how it is used in .github/workflows/checks.yml.
    'x-build': BUILD,
    ...extra,
    // The site is served from the same origin as this Worker in the deployed
    // setup (a /api/* route), so CORS isn't needed there and the page's CSP can
    // stay connect-src 'self'. This header only matters if the API is ever
    // called from a different origin; it's read-only public content either way.
    'access-control-allow-origin': '*',
    'x-content-type-options': 'nosniff',
  },
});

/* A date arriving from the client is only ever honored for replaying a puzzle
   that has already happened — that's what challenge links need. Anything in the
   future is refused rather than clamped, so this endpoint can't be walked
   forward to read tomorrow's questions, which is the exact hole the client-side
   date created. Malformed input and anything before the epoch are refused too. */
function acceptPastDate(raw, today){
  if(!raw || !/^\d{4}-\d{2}-\d{2}$/.test(raw)) return null;
  const t = Date.parse(raw + 'T00:00:00Z');
  if(!Number.isFinite(t)) return null;
  if(t < Date.parse(BAG_EPOCH + 'T00:00:00Z')) return null;
  if(t > Date.parse(today + 'T00:00:00Z')) return null;
  return raw;
}

/* How long a BROWSER may reuse a daily response. Deliberately not 24 hours: the
   edge cache is keyed by date and so re-keys itself the moment the date rolls,
   but a browser cache has no such key — it would just hold a stale entry and
   serve yesterday's puzzle to a returning player after midnight.

   The first version of this set the browser TTL to the seconds remaining until ET
   midnight, so the copy expired exactly at the rollover. Correct for the rollover,
   and wrong for everything else: it also meant a browser that loaded at noon could
   not be reached by ANY deploy for the rest of the day. That is not hypothetical —
   a puzzle-numbering fix shipped, deployed cleanly, showed 0 errors, and the site
   kept serving the old number for hours because every browser that had already
   asked was holding a five-hour-old answer.

   So the browser TTL is now short and the shared edge cache keeps the long one. The
   edge absorbs the traffic either way — every visitor on a given date gets the same
   bytes — so a browser re-asking every few minutes costs a conditional hit on a
   cache that is already warm, and buys the ability to fix something mid-day. */
const EDGE_TTL = 86400;     // 24h at the edge, matching the daily rotation
const BROWSER_TTL = 300;    // 5 min in the browser, so a deploy can actually land
/* A fingerprint of everything this bundle would serve. Computed once per isolate
   over the pool, the schedule and the epoch, so it changes when and only when the
   answer could change — which is what makes it safe to put in a cache key.

   Deliberately not a timestamp or a random value: those would change on every cold
   start and throw away a cache that is supposed to last the day. */
const BUILD = (() => {
  const src = BAG_EPOCH + '|' + JSON.stringify(SCHEDULE) + '|' + JSON.stringify(POOL);
  let h = 5381;
  for (let i = 0; i < src.length; i++) h = ((h * 33) ^ src.charCodeAt(i)) >>> 0;
  return h.toString(36);
})();


/* Never longer than the time left until the rollover — a browser must not hold a
   copy across midnight — and never longer than BROWSER_TTL, so a deploy reaches
   people within minutes rather than at the end of the day. */
function browserTtl(now = new Date()){
  const et = new Date(now.toLocaleString('en-US', { timeZone: 'America/New_York' }));
  const next = new Date(et);
  next.setHours(24, 0, 0, 0);
  const untilRollover = Math.round((next - et) / 1000);
  // No floor. A floor of even 30s lets a copy fetched at 23:59:40 outlive the
  // rollover, which is the exact thing this function exists to prevent; in the last
  // seconds of a day the right answer is simply "revalidate".
  return Math.max(0, Math.min(BROWSER_TTL, untilRollover));
}

export default {
  async fetch(request, env, ctx){
    if(request.method !== 'GET' && request.method !== 'HEAD'){
      return new Response('Method not allowed', { status: 405, headers:{ allow:'GET, HEAD' } });
    }
    const url = new URL(request.url);
    const path = url.pathname.replace(/^\/api/, '').replace(/\/$/, '') || '/daily';
    const today = todayDateString();

    if(path === '/daily'){
      const date = acceptPastDate(url.searchParams.get('d'), today) || today;

      /* Edge cache. Every visitor on a given day gets a byte-identical answer, so
         the selection should run once per day per edge location, not once per
         request. The cache key is a synthetic URL containing the resolved date —
         not the incoming request URL, which is the important part twice over:
         it means `/daily`, `/api/daily`, and `/daily?d=<today>` all share one
         entry instead of three, and it means the key changes by itself at
         midnight ET. Nothing ever has to purge this cache; yesterday's entry is
         simply never asked for again. */
      const cache = globalThis.caches?.default;
      // The key carries BUILD as well as the date. Keyed on date alone, a deploy did
      // not invalidate anything: the edge kept serving a body computed by the
      // PREVIOUS bundle until the date rolled, so new questions, corrected facts and
      // a changed epoch could all sit undelivered for up to 24 hours while the
      // deployment log said success. That is the same silent-staleness failure the
      // whole bundled-pool design was meant to avoid, reintroduced one layer down.
      const cacheKey = new Request(`https://statmap.invalid/daily/${date}/${BUILD}`, { method: 'GET' });
      if(cache){
        const hit = await cache.match(cacheKey);
        // Re-derive max-age on a hit: the stored copy was written with the TTL
        // that was correct when it was computed, which shrinks as the day goes on.
        if(hit){
          const fresh = new Response(hit.body, hit);
          fresh.headers.set('cache-control', `public, max-age=${browserTtl()}, s-maxage=${EDGE_TTL}`);
          fresh.headers.set('x-cache', 'HIT');
          return fresh;
        }
      }

      const res = json({
        date,
        today,
        puzzleNumber: puzzleNumber(date),
        questions: roundsForDate(date, POOL, SCHEDULE),
      }, `public, max-age=${browserTtl()}, s-maxage=${EDGE_TTL}`, { 'x-cache': 'MISS' });

      if(cache){
        // Don't make the player wait on the cache write.
        const write = cache.put(cacheKey, res.clone());
        if(ctx?.waitUntil) ctx.waitUntil(write); else await write;
      }
      return res;
    }

    return new Response('Not found', { status: 404 });
  },
};
