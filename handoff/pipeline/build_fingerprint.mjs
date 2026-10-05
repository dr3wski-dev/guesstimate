/* Print the fingerprint of the question pool in this checkout.
 *
 * WHY THIS EXISTS
 * The Worker computes the same value at startup and returns it as `x-build`, so this
 * is how you answer "is the thing serving statmap.app the thing I have?" without
 * trusting a deploy log. That question needed an answer after an evening spent on a
 * build that failed while everything downstream of it looked healthy: Pages was
 * green, the API responded, the questions were well-formed, and they were the old
 * ones. Nothing in that picture says "stale", which is exactly what makes it
 * expensive.
 *
 * It deliberately re-implements nothing: it imports the Worker's own BUILD constant,
 * which is the exact value the Worker will put in `x-build`. This used to be a second
 * copy of the hash expression with a comment asking the next person to keep the two
 * identical, and that comment was not enough — adding the games manifest to the
 * fingerprint touched one copy and would have shipped a deploy check that compared a
 * three-part hash against a four-part one and failed on a correct deploy. A
 * fingerprint that can drift from the thing it fingerprints is worse than none.
 *
 *   node pipeline/build_fingerprint.mjs           # print it
 *   node pipeline/build_fingerprint.mjs --check   # compare against the live API
 */
import { BUILD } from '../worker/src/index.js';

export function fingerprint() {
  return BUILD;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const want = fingerprint();
  const check = process.argv.includes('--check');
  if (!check) {
    console.log(want);
    process.exit(0);
  }
  const url = process.env.API || 'https://statmap.app/api/daily';
  // The edge caches for a day, so a just-deployed Worker can take a moment to be the
  // one answering. Retry rather than fail on the first miss, but do not retry
  // forever — "eventually consistent" and "never deployed" look the same at minute
  // one and different at minute two.
  for (let attempt = 1; attempt <= 12; attempt++) {
    const res = await fetch(url, { cache: 'no-store' }).catch(() => null);
    const got = res?.headers.get('x-build');
    if (got === want) {
      console.log(`live pool matches this checkout (${want})`);
      process.exit(0);
    }
    console.log(`attempt ${attempt}: live x-build ${got ?? '(no response)'}, want ${want}`);
    await new Promise(r => setTimeout(r, 10000));
  }
  console.error(
    `\nThe live API is not serving this pool.\n` +
    `  expected  ${want}\n` +
    `A Worker that uploaded a version without releasing it fails exactly like this:\n` +
    `the API answers, the questions are valid, and they are the previous ones.`);
  process.exit(1);
}
