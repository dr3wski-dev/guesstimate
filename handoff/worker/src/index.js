/* Guesstimate daily-questions API — one stateless Cloudflare Worker.
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
import { roundsForDate, puzzleNumber, todayDateString, BAG_EPOCH } from './selection.js';

const json = (body, cacheControl, extra = {}) => new Response(JSON.stringify(body), {
  headers: {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': cacheControl,
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
   serve yesterday's puzzle to a returning player after midnight. Expiring the
   browser copy exactly at the ET rollover is the whole fix, and it means the
   24-hour lifetime applies where it's actually safe: the shared edge cache,
   via s-maxage. */
const EDGE_TTL = 86400; // 24h, matching the daily rotation
function secondsUntilEtMidnight(now = new Date()){
  const et = new Date(now.toLocaleString('en-US', { timeZone: 'America/New_York' }));
  const next = new Date(et);
  next.setHours(24, 0, 0, 0);
  return Math.max(60, Math.min(EDGE_TTL, Math.round((next - et) / 1000)));
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
      const cacheKey = new Request(`https://guesstimate.invalid/daily/${date}`, { method: 'GET' });
      if(cache){
        const hit = await cache.match(cacheKey);
        // Re-derive max-age on a hit: the stored copy was written with the TTL
        // that was correct when it was computed, which shrinks as the day goes on.
        if(hit){
          const fresh = new Response(hit.body, hit);
          fresh.headers.set('cache-control', `public, max-age=${secondsUntilEtMidnight()}, s-maxage=${EDGE_TTL}`);
          fresh.headers.set('x-cache', 'HIT');
          return fresh;
        }
      }

      const res = json({
        date,
        today,
        puzzleNumber: puzzleNumber(date),
        questions: roundsForDate(date, POOL),
      }, `public, max-age=${secondsUntilEtMidnight()}, s-maxage=${EDGE_TTL}`, { 'x-cache': 'MISS' });

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
