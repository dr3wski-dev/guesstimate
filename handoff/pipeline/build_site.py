#!/usr/bin/env python3
"""
Assemble the deployable site into site/ from the canonical sources.

WHY A BUILD STEP
The game currently lives at handoff/reference/guesstimate-scatter.html and fetches
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
  python3 pipeline/build_site.py --url https://guesstimate.example
  python3 pipeline/build_site.py --url https://guesstimate.example --check
  python3 pipeline/build_site.py --url https://guesstimate.example \\
      --analytics plausible --analytics-domain guesstimate.example
"""
import argparse, json, os, re, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
SRC_HTML = os.path.join(ROOT, 'reference', 'guesstimate-scatter.html')
SRC_DATA = os.path.join(ROOT, 'data', 'questions.json')
SRC_SCHEDULE = os.path.join(ROOT, 'data', 'schedule.json')
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
        'csp': {'script-src': ['https://cloud.umami.is'],
                'connect-src': ['https://cloud.umami.is', 'https://api-gateway.umami.dev']},
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


def build(site_url, check=False, provider=None, domain=None):
    site_url = site_url.rstrip('/')
    html = open(SRC_HTML, encoding='utf-8').read()

    # 1. The data path. In the reference tree the game sits one directory below the
    #    data; at a web root they're siblings.
    html, n = re.subn(r"fetch\('\.\./data/questions\.json'\)",
                      "fetch('data/questions.json')", html)
    assert n == 1, f'expected exactly one data fetch to rewrite, found {n}'
    html, ns = re.subn(r"fetch\('\.\./data/schedule\.json'\)",
                       "fetch('data/schedule.json')", html)
    assert ns == 1, f'expected exactly one schedule fetch to rewrite, found {ns}'

    # 2. Fonts move from ../assets/fonts to assets/fonts for the same reason.
    html, nf = re.subn(r"url\('\.\./assets/fonts/", "url('assets/fonts/", html)
    assert nf > 0, 'expected font URLs to rewrite'

    # 3. Absolute OG/Twitter URLs. Relative ones are the single most common reason a
    #    link card renders blank, and for a game distributed by pasted links that card
    #    IS the landing page. iMessage in particular will not resolve a relative
    #    og:image.
    html = html.replace('content="assets/og-image.png"',
                        f'content="{site_url}/assets/og-image.png"')
    if 'property="og:url"' not in html:
        html = html.replace('<meta property="og:type" content="website">',
                            f'<meta property="og:type" content="website">\n'
                            f'<meta property="og:url" content="{site_url}/">')
    html = html.replace('<title>', f'<link rel="canonical" href="{site_url}/">\n<title>', 1)

    if provider:
        tag = ANALYTICS[provider]['tag'].format(domain=domain)
        html = html.replace('</head>', tag + '\n</head>', 1)

    leftovers = re.findall(r'(?:content|href|src)="(?!https?:|data:|#)[^"]*\.\./[^"]*"', html)
    assert not leftovers, f'unresolved relative paths: {leftovers}'

    if check:
        problems = []
        if 'content="assets/og-image.png"' in html:
            problems.append('og:image still relative')
        if "fetch('../data" in html:
            problems.append('data path still relative')
        pool = json.load(open(SRC_DATA))
        if len(pool) < 5:
            problems.append(f'question pool too small to fill a day: {len(pool)}')
        print('CHECK:', 'ok' if not problems else 'FAILED')
        for p in problems:
            print('  -', p)
        return 1 if problems else 0

    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(os.path.join(OUT, 'data'), exist_ok=True)
    open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8').write(html)
    shutil.copy2(SRC_DATA, os.path.join(OUT, 'data', 'questions.json'))
    # Always emit a schedule, even an empty one. The game treats a missing file as
    # "no pinned days" and carries on, but the browser still logs a 404 for it on
    # every single page load, which is noise in every player's console and in ours.
    dest_sched = os.path.join(OUT, 'data', 'schedule.json')
    if os.path.exists(SRC_SCHEDULE):
        shutil.copy2(SRC_SCHEDULE, dest_sched)
    else:
        open(dest_sched, 'w').write('{}\n')
    shutil.copytree(SRC_ASSETS, os.path.join(OUT, 'assets'),
                    ignore=shutil.ignore_patterns('og-source.html'))

    # Netlify / Cloudflare Pages. questions.json is deliberately short-cached: it is
    # the one file that changes when content ships, and a stale copy means a player
    # sees yesterday's puzzle. Fonts are immutable and cached hard.
    csp = csp_with(provider)
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

/data/*.json
  Cache-Control: public, max-age=300, must-revalidate

/index.html
  Cache-Control: public, max-age=0, must-revalidate
""")

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
            {"source": "/data/questions.json", "headers": [
                {"key": "Cache-Control", "value": "public, max-age=300, must-revalidate"}]},
        ],
    }, open(os.path.join(OUT, 'vercel.json'), 'w'), indent=2)

    open(os.path.join(OUT, 'robots.txt'), 'w').write(
        f'User-agent: *\nAllow: /\nSitemap: {site_url}/sitemap.xml\n')
    open(os.path.join(OUT, 'sitemap.xml'), 'w').write(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f'  <url><loc>{site_url}/</loc><changefreq>daily</changefreq></url>\n'
        '</urlset>\n')

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
    ap.add_argument('--url', required=True, help='absolute site origin, e.g. https://guesstimate.app')
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
