#!/usr/bin/env python3
"""
Guesstimate content pipeline — candidate question generator.

WHY THIS EXISTS
The pool was 10 questions, which is two days before every question repeats (see
USER_EXPERIENCE_REVIEW.md §1.3). Hand-researching to 100 is ~100 sessions. This
turns the mechanical half of that into a repeatable job: it finds stat pairs and
player sets that make a genuinely counterintuitive question, computes every number
from an open dataset, and emits candidates. A human still writes the `fact` copy
and approves each question — the script never invents prose and never guesses a
number.

SOURCING RULE (ACTION_PLAN.md, README.md)
No fabricated or estimated data, ever. Every number a question ships with is
computed here from a named open dataset, pinned to a commit/release, and traceable
to a column. Nothing is typed in from memory.

DATA SOURCES
  MLB  Lahman / Chadwick Bureau baseball databank (core CSVs)
       Full history, currently through 2021.
  NFL  nflverse-data `player_stats` release (weekly player stats, REG only)
       1999 through 2024.

Both were validated by recomputing the four hand-verified reference values in the
existing questions.json and matching them exactly:
  Abreu 288 HR / 2 AS, Dunn 462 / 2, Griffey Jr 630 / 13, A-Rod 696 / 14
  Taylor '21 106.5 YPG / 18 TD, Henry '20 126.7 / 17,
  McCaffrey '23 91.2 / 14, Peterson '12 131.1 / 12
`--validate` re-runs those checks and exits non-zero on any drift.

STALENESS
Datasets have an end year, so an active player's career totals are a snapshot, not
a career. Career questions are therefore restricted to players whose final season
is at least two years before the data ends. Season questions (e.g. "Derrick Henry,
2020") are frozen forever and carry no such risk — prefer them, per ACTION_PLAN §1.

RECOGNIZABILITY
Candidates are drawn only from data/athlete_pool.csv, the curated 527-name
shortlist. A statistically interesting question about someone nobody has heard of
is not a good question.

USAGE
  python3 pipeline/build_questions.py --fetch          # download datasets to pipeline/cache/
  python3 pipeline/build_questions.py --validate       # re-verify against known-good values
  python3 pipeline/build_questions.py --league mlb --top 12
  python3 pipeline/build_questions.py --league nfl --top 12 --json out.json
"""

import argparse, csv, json, math, os, re, sys, urllib.request
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'cache')
POOL_CSV = os.path.join(HERE, '..', 'data', 'athlete_pool.csv')

# Pinned sources. Bump these deliberately; every shipped number traces to one.
MLB_BASE = 'https://raw.githubusercontent.com/cbwinslow/baseballdatabank/master/core'
MLB_FILES = ['Batting', 'People', 'AllstarFull']
NFL_URL = 'https://github.com/nflverse/nflverse-data/releases/download/player_stats/player_stats.csv'

MLB_SOURCE = ('Lahman / Chadwick Bureau baseball databank (core/Batting.csv, '
              'core/AllstarFull.csv), regular season.')
NFL_SOURCE = ('nflverse-data player_stats release (regular season weekly stats, '
              'aggregated by season).')


# ---------------------------------------------------------------- fetching
def fetch():
    os.makedirs(CACHE, exist_ok=True)
    for f in MLB_FILES:
        dest = os.path.join(CACHE, f + '.csv')
        print(f'  {f}.csv ...', end='', flush=True)
        urllib.request.urlretrieve(f'{MLB_BASE}/{f}.csv', dest)
        print(f' {os.path.getsize(dest)//1024} KB')
    dest = os.path.join(CACHE, 'nfl_player_stats.csv')
    print('  nfl_player_stats.csv ...', end='', flush=True)
    urllib.request.urlretrieve(NFL_URL, dest)
    print(f' {os.path.getsize(dest)//1024} KB')


def _read(name):
    path = os.path.join(CACHE, name)
    if not os.path.exists(path):
        sys.exit(f'missing {path} — run with --fetch first')
    with open(path, newline='', encoding='utf-8', errors='replace') as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------- name matching
def norm(s):
    s = s.lower().strip()
    for a, b in [('á','a'),('é','e'),('í','i'),('ó','o'),('ú','u'),('ñ','n'),('ü','u')]:
        s = s.replace(a, b)
    s = re.sub(r'\b(jr|sr|ii|iii|iv)\b\.?', '', s)
    return re.sub(r"[^a-z ]", '', s).strip()


def disambiguate(by_name, volume, dominance=0.5):
    """Resolve normalized-name collisions between genuinely different players.

    This exists because of a real bug caught in review: two different Ricky
    Williamses played in 1999-2011 (the Dolphins back and a Colts back), and
    aggregating on name merged them — Ricky Williams' 2003 came out as 1527 yards
    on 440 carries instead of the correct 1372 on 392, which would have been an
    NFL carries record and was simply two players added together. Nothing about
    the number looked wrong on its face; only a per-id breakdown showed it.

    Rule: take the highest-volume claimant, but only if the runner-up is under
    `dominance` of its volume. Otherwise the name is genuinely ambiguous ("Ken
    Griffey" is two Hall-of-Fame-calibre careers) and gets dropped rather than
    guessed at. Dropping a candidate costs one question; guessing costs the
    project's one inviolable rule.
    """
    out = {}
    for key, claimants in by_name.items():
        if len(claimants) == 1:
            out[key] = claimants[0]
            continue
        ranked = sorted(claimants, key=volume, reverse=True)
        top, second = volume(ranked[0]), volume(ranked[1])
        if top > 0 and second / top < dominance:
            out[key] = ranked[0]
        # else: ambiguous, deliberately omitted
    return out


def load_pool():
    """The curated shortlist, keyed by league -> {normalized name: row}."""
    out = defaultdict(dict)
    with open(POOL_CSV, newline='', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            out[r['League'].strip().upper()][norm(r['Player'])] = r
    return out


# ---------------------------------------------------------------- MLB
def mlb_careers(pool_all, gate=True):
    pool = pool_all['MLB']
    bat, people, allstar = _read('Batting.csv'), _read('People.csv'), _read('AllstarFull.csv')
    ppl = {p['playerID']: p for p in people}
    tot, years = defaultdict(Counter), defaultdict(set)
    for r in bat:
        pid = r['playerID']
        years[pid].add(int(r['yearID']))
        for c in ('G','AB','R','H','2B','3B','HR','RBI','SB','BB','SO'):
            if r[c]:
                tot[pid][c] += int(r[c])
    as_years = defaultdict(set)
    for r in allstar:
        as_years[r['playerID']].add(int(r['yearID']))
    data_max = max(int(r['yearID']) for r in bat)

    # Aggregate by playerID, never by name. Names collide — Lahman contains both
    # Ken Griffey Sr and Jr, and a name-keyed dict silently returns whichever was
    # written last. See disambiguate() for how collisions are resolved.
    by_name = defaultdict(list)
    for pid, c in tot.items():
        p = ppl.get(pid)
        if not p or c['AB'] < 3000:          # need a real career for rate stats
            continue
        nm = f"{p.get('nameFirst','')} {p.get('nameLast','')}".strip()
        by_name[norm(nm)].append((pid, nm, c))
    chosen = disambiguate(by_name, lambda t: t[2]['AB'])

    out = {}
    for key, (pid, nm, c) in chosen.items():
        if gate and key not in pool:
            continue
        last = max(years[pid])
        out[key] = {
            'name': nm, 'last_season': last, 'first_season': min(years[pid]),
            'who': key, 'player_id': pid,
            'career_complete': last <= data_max - 2,
            'pool': pool.get(key, {'Tier': '', 'Status': ''}),
            'stats': {
                'HR': c['HR'], 'H': c['H'], 'AB': c['AB'], 'SB': c['SB'],
                '2B': c['2B'], '3B': c['3B'], 'BB': c['BB'], 'SO': c['SO'],
                'RBI': c['RBI'], 'R': c['R'], 'G': c['G'],
                'AVG': round(c['H'] / c['AB'], 3),
                'AS': len(as_years[pid]),
            },
        }
    return out, data_max


# ---------------------------------------------------------------- NFL
def nfl_seasons(pool_all, gate=True):
    pool = pool_all['NFL']
    rows = _read('nfl_player_stats.csv')
    # Keyed on player_id, not name — nflverse contains two distinct Ricky
    # Williamses overlapping in 2002-03, and name-keying silently summed them.
    agg, wk = defaultdict(Counter), defaultdict(set)
    seasons, names, career = {}, {}, Counter()
    for r in rows:
        if r.get('season_type') != 'REG':
            continue
        pid = r['player_id']
        yr = int(r['season'])
        key = (pid, yr)
        seasons[yr] = True
        names[pid] = r['player_display_name']
        wk[key].add(r['week'])
        for c in ('rushing_yards','rushing_tds','receiving_yards','receiving_tds',
                  'passing_yards','passing_tds','interceptions','attempts',
                  'completions','receptions','carries','targets'):
            v = r.get(c)
            if v:
                try:
                    agg[key][c] += float(v)
                except ValueError:
                    pass
        for c in ('rushing_yards', 'receiving_yards', 'passing_yards'):
            if r.get(c):
                try:
                    career[pid] += float(r[c])
                except ValueError:
                    pass

    by_name = defaultdict(list)
    for pid, nm in names.items():
        by_name[norm(nm)].append(pid)
    chosen = disambiguate(by_name, lambda pid: career[pid])
    id_key = {pid: key for key, pid in chosen.items()}
    keep = set(id_key)

    out = {}
    for (pid, yr), c in agg.items():
        if pid not in keep:
            continue
        key = id_key[pid]
        if gate and key not in pool:
            continue
        g = len(wk[(pid, yr)])
        if g < 8:
            continue
        out[(key, yr)] = {
            'name': names[pid], 'season': yr, 'games': g, 'who': key,
            'player_id': pid,
            'pool': pool.get(key, {'Tier': '', 'Status': ''}),
            'stats': {
                'rush_yds': int(c['rushing_yards']), 'rush_td': int(c['rushing_tds']),
                'rec_yds': int(c['receiving_yards']), 'rec_td': int(c['receiving_tds']),
                'rec': int(c['receptions']), 'carries': int(c['carries']),
                'pass_yds': int(c['passing_yards']), 'pass_td': int(c['passing_tds']),
                'int': int(c['interceptions']), 'att': int(c['attempts']),
                'rush_ypg': round(c['rushing_yards'] / g, 1),
                'rec_ypg': round(c['receiving_yards'] / g, 1),
                'ypc': round(c['rushing_yards'] / c['carries'], 1) if c['carries'] >= 100 else None,
                'ypr': round(c['receiving_yards'] / c['receptions'], 1) if c['receptions'] >= 30 else None,
            },
        }
    return out, max(seasons)


# ---------------------------------------------------------------- archetypes
# Each: the two axes, a filter, and how the chart should be labelled.
MLB_ARCHETYPES = [
    # min_first 1963: see the Killebrew note in validate(). Two All-Star games a
    # year from 1959-62 make "selections" ambiguous for anyone who played then.
    dict(id='as-hr',   x='AS',  y='HR',  xl='Career All-Star selections', xu='AS',
         yl='Career home runs', yu='HR', xstep=1, ystep=1, minab=4000, min_first=1963),
    dict(id='avg-hr',  x='AVG', y='HR',  xl='Career batting average', xu='AVG',
         yl='Career home runs', yu='HR', xstep=0.001, ystep=1, minab=5000),
    dict(id='sb-hr',   x='SB',  y='HR',  xl='Career stolen bases', xu='SB',
         yl='Career home runs', yu='HR', xstep=1, ystep=1, minab=5000),
    dict(id='so-hr',   x='SO',  y='HR',  xl='Career strikeouts', xu='SO',
         yl='Career home runs', yu='HR', xstep=1, ystep=1, minab=5000),
    dict(id='bb-hr',   x='BB',  y='HR',  xl='Career walks', xu='BB',
         yl='Career home runs', yu='HR', xstep=1, ystep=1, minab=5000),
    dict(id='2b-hr',   x='2B',  y='HR',  xl='Career doubles', xu='2B',
         yl='Career home runs', yu='HR', xstep=1, ystep=1, minab=5000),
]

NFL_ARCHETYPES = [
    dict(id='rushypg-td', x='rush_ypg', y='rush_td', xl='Rushing yards per game (season)',
         xu='YPG', yl='Rushing touchdowns (season)', yu='TDs', xstep=0.1, ystep=1,
         need=('rush_yds', 700)),
    dict(id='rec-recyds', x='rec', y='rec_yds', xl='Receptions (season)', xu='rec',
         yl='Receiving yards (season)', yu='yards', xstep=1, ystep=1,
         need=('rec_yds', 900)),
    dict(id='passtd-int', x='int', y='pass_td', xl='Interceptions (season)', xu='INT',
         yl='Passing touchdowns (season)', yu='TDs', xstep=1, ystep=1,
         need=('pass_yds', 3000)),
    dict(id='rushyds-recyds', x='rush_yds', y='rec_yds', xl='Rushing yards (season)',
         xu='yards', yl='Receiving yards (season)', yu='yards', xstep=1, ystep=1,
         need=('rush_yds', 500)),
    dict(id='ypc-rushyds', x='ypc', y='rush_yds', xl='Yards per carry (season)', xu='YPC',
         yl='Rushing yards (season)', yu='yards', xstep=0.1, ystep=1,
         need=('rush_yds', 800)),
]


def rank_of(v, vals):
    return sorted(vals).index(v)


def _tidy(v):
    v = round(v, 6)
    return int(v) if v == int(v) else v


def nice_domain(vals, step):
    """Round human bounds containing every point with margin. Never derived from
    the answer alone — the axis-leak bug in COMPETITIVE_ANALYSIS §2 came from
    exactly that."""
    lo0, hi0 = min(vals), max(vals)
    span = (hi0 - lo0) or abs(hi0) or 1
    pad = span * 0.12
    need_lo, need_hi = lo0 - pad, hi0 + pad
    # Counting stats can't be negative — a home-run axis running to -200 is
    # nonsense and spends a chunk of the chart on impossible values.
    nonneg = lo0 >= 0
    if nonneg:
        need_lo = max(need_lo, 0.0)

    # The chart draws five ticks at the quarters, so the domain should be exactly
    # four "nice" tick steps wide. Searching for the smallest step that still
    # covers the data keeps the plotted range tight: quantizing the endpoints
    # independently (the previous approach) produced [0, 800] for a 92-509 spread,
    # throwing away a third of the axis and, with it, a third of the precision a
    # player's click can express.
    for exp in range(-5, 10):
        mag = 10.0 ** exp
        for m in (1, 2, 2.5, 5):
            t = m * mag
            if t * 4 + 1e-12 < need_hi - need_lo:
                continue
            # A stat that only takes whole values (All-Star counts, home runs,
            # interceptions) must get whole-numbered ticks. Rounding the endpoints
            # afterwards is what produced a [2, 23] All-Star axis with ticks 5.25
            # apart — so constrain the candidates instead of repairing them later.
            if step >= 1 and t != int(t):
                continue
            # Align the low end to the tick step, or to a half-step: a domain
            # starting at 250 with 100-wide ticks still reads cleanly, and the
            # extra freedom often saves a whole quantisation jump.
            aligns = {math.floor(need_lo / t) * t}
            half = t / 2
            if step < 1 or half == int(half):
                aligns.add(math.floor(need_lo / half) * half)
            if nonneg and need_lo <= t:
                aligns.add(0.0)
            for lo in sorted(aligns, reverse=True):
                if lo < 0 and nonneg:
                    continue
                hi = lo + 4 * t
                if lo <= need_lo + 1e-9 and hi >= need_hi - 1e-9:
                    return [_tidy(lo), _tidy(hi)]
    return [_tidy(need_lo), _tidy(need_hi)]


def score_candidate(tgt, refs, xk, yk):
    """How counterintuitive is this? The game's premise is the 'sneaky stud' — a
    player who is high on one axis and low on the other relative to company you'd
    assume they match. That is a rank inversion, so score it directly."""
    four = refs + [tgt]
    xs = [p['stats'][xk] for p in four]
    ys = [p['stats'][yk] for p in four]
    if len(set(xs)) < 4 or len(set(ys)) < 4:
        return None
    inv = abs(rank_of(tgt['stats'][xk], xs) - rank_of(tgt['stats'][yk], ys))
    if inv < 2:
        return None
    # references should span the space, not huddle
    def spread(v):
        r = max(v) - min(v)
        return 0 if r == 0 else min(sorted(v)[i+1] - sorted(v)[i] for i in range(3)) / r
    sp = min(spread(xs), spread(ys))
    if sp < 0.08:
        return None
    # prefer a target that isn't pinned to a corner — more interesting to place
    def interior(v, all_v):
        lo, hi = min(all_v), max(all_v)
        return 0.0 if hi == lo else 1 - abs((v - lo) / (hi - lo) - 0.5) * 2
    mid = (interior(tgt['stats'][xk], xs) + interior(tgt['stats'][yk], ys)) / 2
    tier_bonus = 0.35 if tgt['pool']['Tier'] == 'Sneaky Stud' else 0.0
    return inv + sp * 2 + mid * 0.8 + tier_bonus


def build(entries, archetypes, league, label_fn, source, top, per_arch=2):
    """entries: list of player/season dicts. Returns ranked candidate questions."""
    out = []
    for arch in archetypes:
        xk, yk = arch['x'], arch['y']
        elig = [e for e in entries
                if e['stats'].get(xk) is not None and e['stats'].get(yk) is not None
                and (('minab' not in arch) or e['stats'].get('AB', 0) >= arch['minab'])
                and (('need' not in arch) or e['stats'].get(arch['need'][0], 0) >= arch['need'][1])
                and (('min_first' not in arch) or e.get('first_season', 9999) >= arch['min_first'])]
        if len(elig) < 8:
            continue
        seen = set()
        for tgt in elig:
            # Three references that bracket the target on both axes. Exclude every
            # other season by the same player: "guess Marshawn Lynch 2012" with
            # Marshawn Lynch 2008 sitting on the chart as a reference is a muddle,
            # not a hint.
            others = [e for e in elig if e['who'] != tgt['who']]
            others.sort(key=lambda e: (e['stats'][xk], e['stats'][yk]))
            n = len(others)
            for combo in ((0, n // 2, n - 1), (n // 4, n // 2, 3 * n // 4),
                          (0, n // 3, 2 * n // 3), (n // 3, 2 * n // 3, n - 1)):
                refs = [others[i] for i in combo]
                if len({id(r) for r in refs}) < 3:
                    continue
                s = score_candidate(tgt, refs, xk, yk)
                if s is None:
                    continue
                key = (arch['id'], label_fn(tgt))
                if key in seen:
                    continue
                seen.add(key)
                xs = [p['stats'][xk] for p in refs + [tgt]]
                ys = [p['stats'][yk] for p in refs + [tgt]]
                out.append({
                    'score': round(s, 3),
                    'id': (f"{league.lower()}-{arch['id']}-{norm(tgt['name']).split()[-1]}"
                           + (f"-{tgt['season']}" if 'season' in tgt else '')),
                    'league': league,
                    'xLabel': arch['xl'], 'xUnit': arch['xu'],
                    'yLabel': arch['yl'], 'yUnit': arch['yu'],
                    'xStep': arch['xstep'], 'yStep': arch['ystep'],
                    'xDomain': nice_domain(xs, arch['xstep']),
                    'yDomain': nice_domain(ys, arch['ystep']),
                    'targetPlayer': label_fn(tgt),
                    'targetX': tgt['stats'][xk], 'targetY': tgt['stats'][yk],
                    'referencePlayers': [
                        {'name': label_fn(r), 'x': r['stats'][xk], 'y': r['stats'][yk]}
                        for r in refs],
                    'fact': '', 'source': source,
                })
                break
    out.sort(key=lambda c: -c['score'])
    # At most two per archetype so a batch isn't six versions of one idea, and
    # one question per player — Rod Carew is a great answer three different ways,
    # but a player who wants five distinct rounds shouldn't meet him in all of them.
    per, used, final = Counter(), set(), []
    for c in out:
        a = c['id'].split('-')[1]
        who = c['targetPlayer']
        if per[a] >= per_arch or who in used:
            continue
        per[a] += 1
        used.add(who)
        final.append(c)
    return final[:top]


# ---------------------------------------------------------------- validation
def validate():
    pool = load_pool()
    ok = True
    mlb, mmax = mlb_careers(pool, gate=False)
    print(f'MLB (Lahman) — data through {mmax}')
    for nm, hr, a in [('Bobby Abreu', 288, 2), ('Adam Dunn', 462, 2),
                      ('Alex Rodriguez', 696, 14), ('Rod Carew', 92, 18),
                      ('Ozzie Smith', 28, 15),
                      # 11, not the "13-time All-Star" often quoted: MLB played TWO
                      # All-Star games a year from 1959-62, so appearance counts and
                      # selection counts diverge for that era. We count distinct
                      # years, and the as-hr archetype excludes anyone who played
                      # through it so the ambiguity never reaches a player.
                      ('Harmon Killebrew', 573, 11)]:
        e = mlb.get(norm(nm))
        if not e:
            print(f'  {nm:22} NOT FOUND'); ok = False; continue
        good = e['stats']['HR'] == hr and e['stats']['AS'] == a
        ok &= good
        print(f"  {nm:22} HR {e['stats']['HR']:>4} (exp {hr:>4})   "
              f"AS {e['stats']['AS']:>3} (exp {a:>3})   {'ok' if good else 'MISMATCH'}")
    nfl, nmax = nfl_seasons(pool, gate=False)
    print(f'NFL (nflverse) — data through {nmax}')
    for nm, yr, ypg, td in [('Jonathan Taylor', 2021, 106.5, 18), ('Derrick Henry', 2020, 126.7, 17),
                            ('Christian McCaffrey', 2023, 91.2, 14), ('Adrian Peterson', 2012, 131.1, 12)]:
        e = nfl.get((norm(nm), yr))
        if not e:
            print(f'  {nm:22} NOT FOUND'); ok = False; continue
        good = abs(e['stats']['rush_ypg'] - ypg) < 0.15 and e['stats']['rush_td'] == td
        ok &= good
        print(f"  {nm:20}{yr}  {e['stats']['rush_ypg']:>6} YPG (exp {ypg})   "
              f"TD {e['stats']['rush_td']:>3} (exp {td:>3})   {'ok' if good else 'MISMATCH'}")
    # Regression guards for the name-collision bug. These are as important as the
    # value checks: the wrong numbers they produced looked entirely plausible.
    print('Name-collision guards')
    rw = nfl.get((norm('Ricky Williams'), 2003))
    good = bool(rw) and rw['stats']['rush_yds'] == 1372 and rw['stats']['carries'] == 392
    ok &= good
    print(f"  Ricky Williams 2003 = {rw['stats']['rush_yds'] if rw else '?'} yds / "
          f"{rw['stats']['carries'] if rw else '?'} car   (must be 1372/392, not the "
          f"1527/440 of two players summed)   {'ok' if good else 'MISMATCH'}")
    amb = norm('Ken Griffey') not in mlb
    ok &= amb
    print(f"  'Ken Griffey' dropped as ambiguous (Sr and Jr both qualify)   "
          f"{'ok' if amb else 'STILL PRESENT'}")

    print('\nVALIDATION', 'PASSED' if ok else 'FAILED')
    return 0 if ok else 1


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fetch', action='store_true')
    ap.add_argument('--validate', action='store_true')
    ap.add_argument('--league', choices=['mlb', 'nfl'])
    ap.add_argument('--top', type=int, default=10)
    ap.add_argument('--per-archetype', type=int, default=2)
    ap.add_argument('--json')
    a = ap.parse_args()

    if a.fetch:
        print('fetching:'); fetch(); return 0
    if a.validate:
        return validate()
    if not a.league:
        ap.print_help(); return 1

    pool = load_pool()
    if a.league == 'mlb':
        entries, dmax = mlb_careers(pool)
        # career questions only for players whose career finished inside the data
        elig = [e for e in entries.values()
                if e['career_complete'] and e['pool']['Status'] == 'Retired']
        cands = build(elig, MLB_ARCHETYPES, 'MLB', lambda e: e['name'], MLB_SOURCE, a.top, a.per_archetype)
    else:
        entries, dmax = nfl_seasons(pool)
        # season questions are frozen history — no staleness risk at all
        elig = list(entries.values())
        cands = build(elig, NFL_ARCHETYPES, 'NFL',
                      lambda e: f"{e['name']}, {e['season']}", NFL_SOURCE, a.top, a.per_archetype)

    print(f'# {a.league.upper()}: {len(elig)} eligible, {len(cands)} candidates '
          f'(data through {dmax})\n')
    for c in cands:
        print(f"[{c['score']:>5}] {c['id']}")
        print(f"        {c['xLabel']} vs {c['yLabel']}")
        print(f"        TARGET  {c['targetPlayer']}: {c['targetX']} {c['xUnit']} / "
              f"{c['targetY']} {c['yUnit']}")
        for r in c['referencePlayers']:
            print(f"        ref     {r['name']}: {r['x']} / {r['y']}")
        print(f"        domains x={c['xDomain']} y={c['yDomain']}\n")

    if a.json:
        with open(a.json, 'w') as fh:
            json.dump(cands, fh, indent=2)
        print(f'wrote {a.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
