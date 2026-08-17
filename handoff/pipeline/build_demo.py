#!/usr/bin/env python3
"""
Build a single self-contained HTML fragment of the game, for sharing a playable
demo where there is no server.

WHY THIS IS SEPARATE FROM build_site.py, AND WHY IT IS NOT THE PRODUCTION BUILD
The real game asks a Worker for one day's questions precisely so the rest of the
pool — every future day's answers — never reaches the browser. A demo has no Worker,
so it has to carry the whole pool, which re-opens exactly that leak. That is fine for
a demo you hand to a few people and wrong for anything public, so the two builds are
kept apart deliberately and this one stamps a visible banner on the page saying so.

Never point a public deployment at this output. `build_site.py` is the production
path and it asserts the pool is absent.

HOW IT STAYS HONEST
The demo does not re-implement daily selection. It inlines `worker/src/selection.js`
verbatim and shims `fetch('/api/daily')` to answer from it, so the demo and
production run the same rotation logic — a divergence here would be a real one.

Fonts are inlined as data: URIs because the artifact host blocks external requests;
without that the page falls back to system fonts and stops looking like the game.

  python3 pipeline/build_demo.py -o demo.html
"""
import argparse, base64, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
SRC_HTML = os.path.join(ROOT, 'reference', 'statmap.html')
SRC_DATA = os.path.join(ROOT, 'data', 'questions.json')
SRC_SCHEDULE = os.path.join(ROOT, 'data', 'schedule.json')
SRC_SELECTION = os.path.join(ROOT, 'worker', 'src', 'selection.js')
FONT_DIR = os.path.join(ROOT, 'assets', 'fonts')

BANNER = """
<div class="demo-banner" role="note">
  <b>Demo build.</b> Everything works, but this copy carries the whole question pool
  so it can run without a server — which means the answers are readable in dev tools.
  Fine for trying it out, not for sharing publicly.
</div>
"""

BANNER_CSS = """
  .demo-banner{
    max-width:620px; margin:0 auto 16px; padding:10px 13px;
    font-family:'IBM Plex Mono',monospace; font-size:12px; line-height:1.55;
    color:var(--ink); background:color-mix(in srgb, var(--accent) 20%, var(--paper));
    border:2px solid var(--ink); border-radius:4px;
  }
"""


def inline_fonts(css):
    """Replace url('../assets/fonts/x.woff2') with a data: URI. The artifact host
    blocks every external request, so a linked font would simply never arrive."""
    def repl(m):
        name = m.group(1)
        path = os.path.join(FONT_DIR, name)
        if not os.path.exists(path):
            sys.exit(f'missing font {path}')
        b64 = base64.b64encode(open(path, 'rb').read()).decode()
        return f"url('data:font/woff2;base64,{b64}')"
    css, n = re.subn(r"url\('\.\./assets/fonts/([^']+)'\)", repl, css)
    assert n > 0, 'expected font URLs to inline'
    return css


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-o', '--out', required=True)
    a = ap.parse_args()

    html = open(SRC_HTML, encoding='utf-8').read()
    pool = json.load(open(SRC_DATA))
    schedule = json.load(open(SRC_SCHEDULE))

    style = re.search(r'<style>(.*?)</style>', html, re.S).group(1)
    style = inline_fonts(style) + BANNER_CSS

    body = re.search(r'<body>(.*?)</body>', html, re.S).group(1)
    # The theme bootstrap lives in <head> in the real page; the artifact skeleton
    # owns <head>, so fold it into the body script instead.
    head_script = re.search(r'<head>.*?<script>(.*?)</script>', html, re.S).group(1)

    # selection.js is an ES module. Strip the export keywords and wrap the whole
    # thing in an IIFE: the game declares BAG_EPOCH, daysSince and puzzleNumber
    # itself for labelling, so dropping the module in at top level collides and the
    # page dies before it renders. Nothing leaks out but the four names the shim
    # needs.
    selection = open(SRC_SELECTION, encoding='utf-8').read()
    selection = re.sub(r'^export\s+', '', selection, flags=re.M)
    selection = ('const __sel = (function(){\n' + selection +
                 '\nreturn { roundsForDate, puzzleNumber, todayDateString, BAG_EPOCH };\n})();\n')

    shim = f"""
/* ---- demo shim: no server, so answer /api/daily locally ----
   Uses the Worker's own selection module, inlined above, rather than a second
   implementation — so the demo rotates exactly like production does. */
const DEMO_POOL = {json.dumps(pool, ensure_ascii=False)};
const DEMO_SCHEDULE = {json.dumps(schedule)};
const __realFetch = window.fetch.bind(window);
window.fetch = async function(input, init){{
  const url = typeof input === 'string' ? input : (input && input.url) || '';
  if(url.indexOf('/api/daily') !== -1){{
    const today = __sel.todayDateString();
    let date = today;
    const m = url.match(/[?&]d=([^&]+)/);
    if(m){{
      const asked = decodeURIComponent(m[1]);
      // Same rule as the Worker: a past date is honoured, anything else falls back
      // to today, so the demo can't be walked forward either.
      if(/^\\d{{4}}-\\d{{2}}-\\d{{2}}$/.test(asked)
         && Date.parse(asked + 'T00:00:00Z') >= Date.parse(__sel.BAG_EPOCH + 'T00:00:00Z')
         && Date.parse(asked + 'T00:00:00Z') <= Date.parse(today + 'T00:00:00Z')){{
        date = asked;
      }}
    }}
    return new Response(JSON.stringify({{
      date, today,
      puzzleNumber: __sel.puzzleNumber(date),
      questions: __sel.roundsForDate(date, DEMO_POOL, DEMO_SCHEDULE),
    }}), {{ status:200, headers:{{'content-type':'application/json'}} }});
  }}
  return __realFetch(input, init);
}};
"""

    # The game's own script must run AFTER the shim, so fetch is already patched by
    # the time init() fires.
    body = body.replace('<script>', '<script>\n' + selection + shim, 1)

    # Just the product name. The gallery shows a description under the title, so an
    # appended "— Demo" would only be noise; the banner on the page says it anyway.
    out = (f'<title>StatMap</title>\n'
           f'<style>\n{style}\n</style>\n'
           f'<script>\n{head_script}\n</script>\n'
           f'{BANNER}\n{body}\n')

    with open(a.out, 'w', encoding='utf-8') as fh:
        fh.write(out)
    kb = os.path.getsize(a.out) / 1024
    print(f'wrote {a.out} ({kb:.0f} KB, {len(pool)} questions, fonts inlined)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
