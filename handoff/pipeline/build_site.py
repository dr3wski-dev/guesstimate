#!/usr/bin/env python3
"""
Assemble the deployable site into site/ from the canonical sources.

WHY A BUILD STEP
The game lives at handoff/reference/statmap.html and fetches
`../data/questions.json`, which means it can't be served from a web root and can't
be opened from disk at all. The obvious fix — copy the file and hand-edit it — creates
a second copy that drifts. So the reference file stays the single source of truth and
this script produces the deployable tree from it:

  site/
    index.html          the game, with root-relative data path and absolute OG URLs
    data/questions.json
    assets/             fonts + OG image
    _headers            CSP and caching for Netlify / Cloudflare Pages
    vercel.json         the same for Vercel
    robots.txt

Everything here is derived. Never hand-edit site/ — edit the reference file or the
data and re-run.

USAGE
  python3 pipeline/build_site.py --url https://statmap.example
  python3 pipeline/build_site.py --url https://statmap.example --check
  python3 pipeline/build_site.py --url https://statmap.example \\
      --analytics plausible --analytics-domain statmap.example
"""
import argparse, json, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
SRC_HTML = os.path.join(ROOT, 'reference', 'statmap.html')
SRC_DATA = os.path.join(ROOT, 'data', 'questions.json')
SRC_SCHEDULE = os.path.join(ROOT, 'data', 'schedule.json')
SRC_GAMES = os.path.join(ROOT, 'data', 'games.json')
SRC_ASSETS = os.path.join(ROOT, 'assets')
OUT = os.path.join(ROOT, '..', 'site')

# The meta CSP in the reference file is defence-in-depth for local use. Served over
# HTTP the header version is the one that counts — a header can carry directives a
# meta tag cannot (frame-ancestors), and it applies before the document parses.
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
       "style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; base-uri 'none'; object-src 'none'; form-action 'self'; "
       "frame-ancestors 'none'")


# Analytics providers. The game calls track() unconditionally and no-ops when no
# provider is installed, so this is purely a deploy-time decision — nothing here is
# ever hand-pasted into the reference file, and building without --analytics produces
# a site with no third-party requests at all.
ANALYTICS = {
    'plausible': {
        'tag': ('<script defer data-domain="{domain}" '
                'src="https://plausible.io/js/script.js"></script>\n'
                '<script>window.plausible=window.plausible||function(){{'
                '(window.plausible.q=window.plausible.q||[]).push(arguments)}}</script>'),
        'csp': {'script-src': ['https://plausible.io'],
                'connect-src': ['https://plausible.io']},
    },
    'umami': {
        # Umami Cloud free tier. ~2 KB script, cookieless, no consent banner, and it
        # supports the custom events this game is instrumented for — which Cloudflare
        # Web Analytics does not. --analytics-domain takes the website ID (a UUID).
        'tag': ('<script defer src="https://cloud.umami.is/script.js" '
                'data-website-id="{domain}"></script>'),
        # connect-src MUST list the host the script POSTs to, which is NOT the host
        # it is served from. Umami Cloud serves script.js from cloud.umami.is and
        # sends events to gateway.umami.is. Allowing only the script origin produces
        # a site that loads the tag, reports no error anywhere on the server side,
        # and collects nothing — which is what shipped, and it stayed invisible for a
        # day because the only symptom is an empty dashboard that looks like "no
        # traffic yet".
        #
        # This list was corrected from a real browser console, not from documentation:
        # "Connecting to 'https://gateway.umami.is/api/send' violates ... connect-src".
        # api-gateway.umami.dev was in here and is not a host the script ever contacts.
        # After changing analytics providers, open the console on the deployed site
        # and confirm there are no CSP errors — there is no way to catch this from the
        # build, because the send host only appears at runtime.
        'csp': {'script-src': ['https://cloud.umami.is'],
                'connect-src': ['https://cloud.umami.is', 'https://gateway.umami.is']},
    },
    'cloudflare': {
        # Free, cookieless, no consent banner needed. Custom events are not supported
        # on the free tier — pageviews only — so the track() calls stay inert here.
        'tag': ('<script defer src="https://static.cloudflareinsights.com/beacon.min.js" '
                'data-cf-beacon=\'{{"token": "{domain}"}}\'></script>'),
        'csp': {'script-src': ['https://static.cloudflareinsights.com'],
                'connect-src': ['https://cloudflareinsights.com']},
    },
}


def csp_with(provider):
    """Extend the base policy for a provider rather than loosening it globally. Adding
    an analytics host must not quietly become 'script-src *'."""
    if not provider:
        return CSP
    extra = ANALYTICS[provider]['csp']
    out = []
    for directive in CSP.split('; '):
        name = directive.split(' ', 1)[0]
        if name in extra:
            directive = directive + ' ' + ' '.join(extra[name])
        out.append(directive)
    return '; '.join(out)


def fairness_gate():
    """Refuse to build a site containing a question that doesn't reward knowing the
    answer. This is a hard gate rather than a warning on purpose: the failure it
    catches is invisible from the outside — a question with perfectly verified stats
    where clicking the middle of the chart beats knowing the answer looks completely
    normal in review, and two of them shipped before anyone measured it. A warning
    printed during a build nobody reads would not have caught them either."""
    audit = os.path.join(HERE, 'audit_fairness.mjs')
    try:
        r = subprocess.run(['node', audit], capture_output=True, text=True)
    except FileNotFoundError:
        sys.exit('node is required to run the fairness audit before a build.\n'
                 'The audit reads the scoring curve out of the game itself, so it '
                 'cannot be reimplemented here in Python without the two drifting '
                 'apart — which would make the gate meaningless.')
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        sys.exit('fairness audit failed — fix or quarantine the questions above, then '
                 'rebuild.\n  node handoff/pipeline/audit_fairness.mjs --suggest')
    print(r.stdout.strip().splitlines()[-1])


def games_gate():
    """The games manifest has to agree with the pool, the schedules and the Worker
    before any of it is published. Same reasoning as the fairness gate above: the
    failure it catches — a game that loads, answers, and serves nothing — looks
    completely healthy from outside."""
    checker = os.path.join(HERE, 'check_games.mjs')
    r = subprocess.run(['node', checker], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        sys.exit('games manifest is inconsistent — fix it before building.')
    print(r.stdout.strip().splitlines()[-1])


def game_page(html, game, games, site_url, depth):
    """One game's page, from the one template.

    `depth` is how many directories below the web root the page sits: 0 for the
    original game at /, 1 for /nba/. It decides the asset paths, and those are the
    only thing that differs structurally between the pages — the reference file
    already writes '../assets/...' because it lives one directory below the data, so
    a page at depth 1 wants them left exactly as they are and a page at the root
    wants them flattened. Getting this backwards produces a page that loads, renders,
    and silently falls back to system fonts.
    """
    url = site_url + ('/' if depth == 0 else f"/{game['slug']}/")

    # Which game this page is, read by the single GAME/GAMES declaration in the
    # template. Injected rather than string-replaced into the body: there is one
    # place the page learns its identity, and it is a data assignment, so a page
    # cannot half-change.
    manifest = [{'id': gid, 'slug': g['slug'], 'name': g['name'], 'short': g['short'],
                 'status': g['status']}
                for gid, g in games.items()]
    me = {'id': game['id'], 'slug': game['slug'], 'name': game['name'],
          'short': game['short'], 'blurb': game['blurb'], 'epoch': game['epoch']}
    inject = ('<script>window.__SM_GAME=' + json.dumps(me, separators=(',', ':'))
              + ';window.__SM_GAMES=' + json.dumps(manifest, separators=(',', ':'))
              + ';</script>')
    html = html.replace('</head>', inject + '\n</head>', 1)

    if depth == 0:
        html, nf = re.subn(r"url\('\.\./assets/fonts/", "url('assets/fonts/", html)
        assert nf > 0, 'expected font URLs to rewrite'
        html, np = re.subn(r'href="\.\./assets/', 'href="assets/', html)
        assert np > 0, 'expected font preload hrefs to rewrite'
    else:
        # Left alone on purpose — see the docstring. Asserted rather than assumed,
        # because "the fonts are missing on the NBA page" is the kind of thing that
        # gets noticed a week later.
        assert "url('../assets/fonts/" in html, 'expected relative font URLs to survive'

    # og:image has to be absolute whatever the depth: a relative one is the single
    # most common reason a pasted link renders a blank card, and iMessage will not
    # resolve one at all.
    html = html.replace('content="assets/og-image.png"',
                        f'content="{site_url}/assets/og-image.png"')
    html = html.replace('content="../assets/og-image.png"',
                        f'content="{site_url}/assets/og-image.png"')

    if 'property="og:url"' not in html:
        html = html.replace('<meta property="og:type" content="website">',
                            f'<meta property="og:type" content="website">\n'
                            f'<meta property="og:url" content="{url}">')
    html = html.replace('<title>', f'<link rel="canonical" href="{url}">\n<title>', 1)

    # Title and social copy name the game. A minigame sharing hard mode's title is
    # the sort of thing that makes two different pages indistinguishable in a tab
    # strip, in search results and in a pasted link card.
    if game['id'] != 'main':
        title = game['title']
        html = html.replace('<title>StatMap: Daily Sports Stat Guessing Game</title>',
                            f'<title>{title}</title>', 1)
        for prop in ('property="og:title"', 'name="twitter:title"'):
            html = re.sub(f'<meta {prop} content="[^"]*"',
                          f'<meta {prop} content="{title}"', html)
        for prop in ('property="og:description"', 'name="twitter:description"'):
            html = re.sub(f'<meta {prop} content="[^"]*"',
                          f'<meta {prop} content="{game["blurb"]}"', html)
    return html


def build(site_url, check=False, provider=None, domain=None):
    site_url = site_url.rstrip('/')
    fairness_gate()
    games_gate()
    games = json.load(open(SRC_GAMES))
    live = {gid: dict(g, id=gid) for gid, g in games.items() if g['status'] == 'live'}
    html = open(SRC_HTML, encoding='utf-8').read()

    # 1. The data path. In the reference tree the game sits one directory below the
    #    data; at a web root they're siblings.
    # No data-path rewrite any more: the client fetches /api/daily and the pool is
    # bundled into the Worker, never published as a static file. Assert that, since
    # re-introducing a questions.json fetch would silently re-open the leak the
    # Worker exists to close.
    assert not re.search(r"fetch\(\s*['\"][^'\"]*questions\.json", html), \
        'the site must not fetch the question pool — that leaks every future answer'
    assert "API_BASE = '/api'" in html, 'expected the client to call the questions API'

    # BAG_EPOCH is declared in both the game and the Worker: the client needs it to
    # label a puzzle and sanitise a challenge date, the Worker needs it to select the
    # day's questions. If the two drift, the page prints one puzzle number while the
    # server serves a different day's questions, and nothing anywhere errors.
    client_epoch = re.search(r"const BAG_EPOCH = '(\d{4}-\d{2}-\d{2})'", html)
    worker_epoch = re.search(r"BAG_EPOCH = '(\d{4}-\d{2}-\d{2})'",
                             open(os.path.join(ROOT, 'worker', 'src', 'selection.js'),
                                  encoding='utf-8').read())
    assert client_epoch and worker_epoch, 'could not read BAG_EPOCH from both sources'
    assert client_epoch.group(1) == worker_epoch.group(1), (
        f'BAG_EPOCH mismatch: game says {client_epoch.group(1)}, '
        f'Worker says {worker_epoch.group(1)} — the puzzle number and the questions '
        f'served would disagree')

    # 2. The page identity, asset depth, canonical URL and social copy are all
    #    per-game now and live in game_page(). What is left here is everything that
    #    is the same on every page.
    assert 'window.__SM_GAME' in html, (
        'expected the page to read its game identity from window.__SM_GAME — '
        'without it every page would be hard mode wearing a different title')

    if provider:
        tag = ANALYTICS[provider]['tag'].format(domain=domain)
        html = html.replace('</head>', tag + '\n</head>', 1)
        # The meta CSP has to be widened too, not just the header. A browser enforces
        # the INTERSECTION of every policy it is given, so a header that allows the
        # analytics host and a meta tag that does not means the script is blocked —
        # and blocked silently, from the page's point of view: the build succeeds, the
        # tag is present in the HTML, the dashboard just never receives an event.
        # SECURITY_NOTES.md says "change one, change both"; this is the build honouring
        # that rather than trusting anyone to remember.
        meta = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)"', html)
        assert meta, 'expected a meta CSP to widen for the analytics provider'
        widened = []
        extra = ANALYTICS[provider]['csp']
        for directive in meta.group(1).split('; '):
            name = directive.split(' ', 1)[0]
            if name in extra:
                directive = directive + ' ' + ' '.join(extra[name])
            widened.append(directive)
        html = html.replace(meta.group(0),
                            f'<meta http-equiv="Content-Security-Policy" content="{"; ".join(widened)}"')

    # One page per LIVE game. A game that is not live has no page at all: a URL that
    # loads a playable-looking board and then gets a 404 from the API is worse than
    # no URL, and the start screen does not link to one either.
    pages = {}
    for gid, game in sorted(live.items(), key=lambda kv: (kv[1]['slug'] != '', kv[0])):
        depth = 0 if game['slug'] == '' else 1
        page = game_page(html, game, games, site_url, depth)
        leftovers = re.findall(r'(?:content|href|src)="(?!https?:|data:|#)[^"]*\.\./[^"]*"', page)
        if depth == 0:
            assert not leftovers, f'{gid}: unresolved relative paths: {leftovers}'
        pages['index.html' if depth == 0 else f"{game['slug']}/index.html"] = page

    if check:
        problems = []
        for rel, page in pages.items():
            if 'content="assets/og-image.png"' in page:
                problems.append(f'{rel}: og:image still relative')
            if "fetch('../data" in page:
                problems.append(f'{rel}: data path still relative')
        pool = json.load(open(SRC_DATA))
        if len(pool) < 5:
            problems.append(f'question pool too small to fill a day: {len(pool)}')
        print('CHECK:', 'ok' if not problems else 'FAILED', f'({len(pages)} page(s))')
        for p in problems:
            print('  -', p)
        return 1 if problems else 0

    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)
    for rel, page in pages.items():
        dest = os.path.join(OUT, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        open(dest, 'w', encoding='utf-8').write(page)
    shutil.copytree(SRC_ASSETS, os.path.join(OUT, 'assets'),
                    ignore=shutil.ignore_patterns('og-source.html'))

    # Netlify / Cloudflare Pages. questions.json is deliberately short-cached: it is
    # the one file that changes when content ships, and a stale copy means a player
    # sees yesterday's puzzle. Fonts are immutable and cached hard.
    csp = csp_with(provider)
    # A rule PER GAME, in both the directory and the file form, rather than one
    # wildcard. Pages matches these against the request path, and a visitor asks for
    # /nba/ — which `/*/index.html` does not match, so the page a player actually
    # requests would have been the one page with no cache rule on it. Same reasoning
    # as /index.html above: the HTML names the day's puzzle number and the game it
    # belongs to, so a cached copy is a wrong page rather than a slow one.
    game_pages = ''.join(
        f'\n/{g["slug"]}/\n  Cache-Control: public, max-age=0, must-revalidate\n'
        f'\n/{g["slug"]}/index.html\n  Cache-Control: public, max-age=0, must-revalidate\n'
        for g in sorted(live.values(), key=lambda g: g['slug']) if g['slug'])
    open(os.path.join(OUT, '_headers'), 'w').write(f"""/*
  Content-Security-Policy: {csp}
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: geolocation=(), microphone=(), camera=()
  Strict-Transport-Security: max-age=31536000; includeSubDomains

/assets/fonts/*
  Cache-Control: public, max-age=31536000, immutable

/assets/*
  Cache-Control: public, max-age=86400

/api/*
  Cache-Control: public, max-age=300, must-revalidate

/index.html
  Cache-Control: public, max-age=0, must-revalidate
{game_pages}""")

    json.dump({
        "$schema": "https://openapi.vercel.sh/vercel.json",
        "headers": [
            {"source": "/(.*)", "headers": [
                {"key": "Content-Security-Policy", "value": csp},
                {"key": "X-Content-Type-Options", "value": "nosniff"},
                {"key": "Referrer-Policy", "value": "strict-origin-when-cross-origin"},
                {"key": "Permissions-Policy",
                 "value": "geolocation=(), microphone=(), camera=()"},
            ]},
            {"source": "/assets/fonts/(.*)", "headers": [
                {"key": "Cache-Control", "value": "public, max-age=31536000, immutable"}]},
            {"source": "/api/(.*)", "headers": [
                {"key": "Cache-Control", "value": "public, max-age=300, must-revalidate"}]},
        ],
    }, open(os.path.join(OUT, 'vercel.json'), 'w'), indent=2)

    open(os.path.join(OUT, 'robots.txt'), 'w').write(
        f'User-agent: *\nAllow: /\nSitemap: {site_url}/sitemap.xml\n')
    locs = ''.join(
        f'  <url><loc>{site_url}/{g["slug"] + "/" if g["slug"] else ""}</loc>'
        f'<changefreq>daily</changefreq></url>\n'
        for g in sorted(live.values(), key=lambda g: g['slug']))
    open(os.path.join(OUT, 'sitemap.xml'), 'w').write(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + locs + '</urlset>\n')

    pool = json.load(open(SRC_DATA))
    total = sum(os.path.getsize(os.path.join(dp, f))
                for dp, _, fs in os.walk(OUT) for f in fs)
    print(f'built {os.path.relpath(OUT, os.path.join(ROOT, ".."))}/  '
          f'({total/1024:.0f} KB, {len(pool)} questions, ~{len(pool)//5} days before repeat)')
    for dp, _, fs in os.walk(OUT):
        for f in sorted(fs):
            rel = os.path.relpath(os.path.join(dp, f), OUT)
            print(f'  {rel:34} {os.path.getsize(os.path.join(dp, f))//1024:>5} KB')
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', required=True, help='absolute site origin, e.g. https://statmap.app')
    ap.add_argument('--check', action='store_true', help='validate without writing')
    ap.add_argument('--analytics', choices=sorted(ANALYTICS),
                    help='install an analytics provider (adds its host to the CSP)')
    ap.add_argument('--analytics-domain',
                    help='plausible: your site domain. cloudflare: the beacon token.')
    a = ap.parse_args()
    if a.analytics and not a.analytics_domain:
        sys.exit('--analytics needs --analytics-domain')
    if not re.match(r'^https://[^/]+$', a.url.rstrip('/')):
        sys.exit('--url must be an absolute https origin with no path')
    return build(a.url, a.check, a.analytics, a.analytics_domain)


if __name__ == '__main__':
    sys.exit(main())
