#!/usr/bin/env python3
"""
StatMap content pipeline — candidate question generator.

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

import argparse, csv, json, math, os, random, re, sys, unicodedata, urllib.request, zlib
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'cache')
POOL_CSV = os.path.join(HERE, '..', 'data', 'athlete_pool.csv')

# Pinned sources. Bump these deliberately; every shipped number traces to one.
MLB_BASE = 'https://raw.githubusercontent.com/cbwinslow/baseballdatabank/master/core'
MLB_FILES = ['Batting', 'Pitching', 'People', 'AllstarFull']
NFL_URL = 'https://github.com/nflverse/nflverse-data/releases/download/player_stats/player_stats.csv'
# hoopR / sportsdataverse republishes stats.nba.com's leaguedashplayerstats per season.
# One file per season, so fetch() collapses the ones we need into a single compact CSV.
NBA_URL = ('https://github.com/sportsdataverse/sportsdataverse-data/releases/download/'
           'nba_stats_player_season_stats/player_season_stats_{season}.csv')
NBA_SEASONS = range(2000, 2025)          # season = start year; 2024 is 2024-25
NBA_COMPACT = 'nba_player_seasons.csv'

MLB_SOURCE = ('Lahman / Chadwick Bureau baseball databank (core/Batting.csv, '
              'core/AllstarFull.csv), regular season.')
MLB_PITCH_SOURCE = ('Lahman / Chadwick Bureau baseball databank (core/Pitching.csv), '
                    'regular season. Career rates are recomputed from season totals '
                    '— ERA as earned runs per 27 outs, K/9 and BB/9 likewise — rather '
                    'than averaged across seasons, which would weight a September '
                    'call-up the same as a 250-inning year.')
# Aggregated from play-by-play, which is stated plainly because it is not identical
# to the official gamebook. Spot-checked against 18 well-known season figures: every
# discrete count (touchdowns, receptions, interceptions, completions) matched exactly,
# while yardage totals drifted by a yard or two in a few seasons — and by 114 yards
# for Marshall Faulk in 1999. Hence NFL_MIN_SEASON below.
NFL_SOURCE = ('nflverse-data player_stats release, regular-season weekly rows '
              'aggregated by player_id and season. Season yardage is derived from '
              'play-by-play and can differ from official gamebook totals by a yard '
              'or two.')
# 1999-2001 play-by-play is materially less complete than 2002 onward.
NFL_MIN_SEASON = 2002
# Targets are UNUSABLE for 2003-2008. In that window the column simply echoes
# receptions: measured across the cache, targets == receptions in 99-100% of rows
# with a catch, against roughly 30-40% in every other season. Marvin Harrison's 2003
# comes out as 94 targets and 94 catches — a hundred per cent catch rate, when he was
# actually thrown at about 141 times.
#
# This shipped before it was noticed, in four plotted values, and the verifier passed
# them: it re-derives targets from the same column, so both sides agreed and both were
# wrong. Agreement between two readings of one broken source is not verification.
# Anything derived from targets is withheld for these seasons instead.
NFL_TARGETS_BROKEN = range(2003, 2009)
# Air yards and yards-after-catch simply do not exist before 2006 — every row with
# catches reports zero, which is a missing measurement wearing a real number's
# clothes. Left as 0 it would plot Jerry Rice as having caught every ball at the line
# of scrimmage. Withheld, so no archetype can reach for it.
NFL_AIRYARDS_FROM = 2006
NBA_SOURCE = ('stats.nba.com leaguedashplayerstats, via the sportsdataverse/hoopR '
              'nba_stats_player_season_stats release. Regular-season per-game averages.')


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
    fetch_nba()


def fetch_nba():
    """Season files are ~3.7 MB each and carry six measure types x two per-modes x
    two season types. We want one slice of that — regular season, per-game, with the
    'base' and 'advanced' rows merged so counting stats and TS% land on one row — so
    collapse it here rather than caching 90 MB of mostly-unused columns."""
    keep = ['pts','reb','ast','stl','blk','fga','fg3a','fg3_pct','fg3m','min','tov',
            'usg_pct','ts_pct']
    rows = []
    for season in NBA_SEASONS:
        print(f'  nba {season} ...', end='', flush=True)
        with urllib.request.urlopen(NBA_URL.format(season=season)) as fh:
            data = fh.read().decode('utf-8', 'replace')
        merged = {}
        rows_by_measure = {'base': [], 'advanced': []}
        for r in csv.DictReader(data.splitlines()):
            if (r['season_type'] != 'regular-season' or r['per_mode'] != 'pergame'
                    or r['measure_type'] not in ('base', 'advanced')):
                continue
            rows_by_measure[r['measure_type']].append(r)
        # base FIRST, and it wins: in pergame mode the 'advanced' rows still carry
        # FGA as a season total (Curry 2016-17 is 18.3 in base and 1443 in advanced),
        # so taking whichever appeared first in the file quietly mixed per-game and
        # total values on the same row. advanced only fills what base doesn't have —
        # ts_pct and usg_pct.
        for measure in ('base', 'advanced'):
            for r in rows_by_measure[measure]:
                d = merged.setdefault(r['player_id'], {
                    'season': season, 'player_id': r['player_id'],
                    'player_name': r['player_name'], 'gp': r['gp']})
                for c in keep:
                    v = r.get(c, '')
                    if v not in ('', None) and not d.get(c):
                        d[c] = v
        rows.extend(merged.values())
        print(f' {len(merged)}')
    dest = os.path.join(CACHE, NBA_COMPACT)
    cols = ['season', 'player_id', 'player_name', 'gp'] + keep
    with open(dest, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        for d in rows:
            w.writerow(d)
    print(f'  {NBA_COMPACT}: {len(rows)} player-seasons, '
          f'{os.path.getsize(dest)//1024} KB')


def _read(name):
    path = os.path.join(CACHE, name)
    if not os.path.exists(path):
        sys.exit(f'missing {path} — run with --fetch first')
    with open(path, newline='', encoding='utf-8', errors='replace') as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------- name matching
def norm(s):
    # Decompose and drop combining marks rather than listing substitutions — the NBA
    # data is full of names a hand-written table misses (Jokić, Dončić, Šengün).
    s = unicodedata.normalize('NFD', s.lower().strip())
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
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


# ---------------------------------------------------------------- MLB pitchers
def mlb_pitchers(pool_all, gate=True):
    """Career pitching lines.

    WHY THIS EXISTS SEPARATELY FROM mlb_careers
    42 of the 158 curated MLB names are pitchers, and every one of them was
    unreachable — the loader read Batting.csv, where a pitcher's line is a handful of
    at-bats or nothing at all. That is most of the reason MLB was the thinnest league
    at 48 questions against the NBA's 84, and why it capped the league rotation.

    RATES ARE RECOMPUTED, NOT AVERAGED
    ERA, K/9 and BB/9 are all "per 9 innings", and innings are counted here in OUTS
    (IPouts), which is how the databank stores them. A career ERA is earned runs
    across the whole career per 27 outs across the whole career. Averaging the season
    ERAs instead would weight a September call-up the same as a 250-inning season and
    quietly produce a number that appears nowhere in any record book.
    """
    pool = pool_all['MLB']
    pitch, people = _read('Pitching.csv'), _read('People.csv')
    ppl = {p['playerID']: p for p in people}
    tot, years = defaultdict(Counter), defaultdict(set)
    for r in pitch:
        pid = r['playerID']
        years[pid].add(int(r['yearID']))
        for c in ('W','L','G','GS','CG','SHO','SV','IPouts','H','ER','HR','BB','SO'):
            if r[c]:
                tot[pid][c] += int(r[c])
    data_max = max(int(r['yearID']) for r in pitch)

    by_name = defaultdict(list)
    for pid, c in tot.items():
        p = ppl.get(pid)
        # 900 outs is 300 innings — enough that a rate stat means something, low
        # enough to keep a short peak career like Koufax's, which is exactly the kind
        # of career worth asking about.
        if not p or c['IPouts'] < 900:
            continue
        nm = f"{p.get('nameFirst','')} {p.get('nameLast','')}".strip()
        by_name[norm(nm)].append((pid, nm, c))
    chosen = disambiguate(by_name, lambda t: t[2]['IPouts'])

    out = {}
    for key, (pid, nm, c) in chosen.items():
        if gate and key not in pool:
            continue
        outs = c['IPouts']
        last = max(years[pid])
        out[key] = {
            'name': nm, 'last_season': last, 'first_season': min(years[pid]),
            'who': key, 'player_id': pid,
            'career_complete': last <= data_max - 2,
            'pool': pool.get(key, {'Tier': '', 'Status': ''}),
            'stats': {
                'W': c['W'], 'L': c['L'], 'G': c['G'], 'GS': c['GS'],
                'CG': c['CG'], 'SHO': c['SHO'], 'SV': c['SV'], 'SO': c['SO'],
                'BB': c['BB'], 'H': c['H'], 'ER': c['ER'], 'HR': c['HR'],
                'IP': round(outs / 3, 1),
                'ERA': round(c['ER'] * 27 / outs, 2),
                'K9': round(c['SO'] * 27 / outs, 1),
                'BB9': round(c['BB'] * 27 / outs, 1),
                'WHIP': round((c['H'] + c['BB']) * 3 / outs, 2),
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
        # Counting stats only, summed. NOT target_share / racr / wopr: those are
        # weekly RATIOS, so summing them is meaningless and averaging them is an
        # approximation of a season share rather than the season share — the true
        # figure needs team totals this file does not carry. A number that is nearly
        # right is the one thing this pipeline will not ship.
        for c in ('rushing_yards','rushing_tds','receiving_yards','receiving_tds',
                  'passing_yards','passing_tds','interceptions','attempts',
                  'completions','receptions','carries','targets',
                  'receiving_air_yards','receiving_yards_after_catch',
                  'receiving_first_downs'):
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
                'tgt': None if yr in NFL_TARGETS_BROKEN else int(c['targets']),
                'comp': int(c['completions']),
                'air_yds': (int(c['receiving_air_yards'])
                            if yr >= NFL_AIRYARDS_FROM else None),
                'yac': (int(c['receiving_yards_after_catch'])
                        if yr >= NFL_AIRYARDS_FROM else None),
                'rec_fd': (int(c['receiving_first_downs'])
                           if yr >= NFL_AIRYARDS_FROM else None),
                # Both exact: a ratio of two summed counts, not an average of ratios.
                'ypt': (round(c['receiving_yards'] / c['targets'], 1)
                        if c['targets'] >= 50 and yr not in NFL_TARGETS_BROKEN else None),
                'catch_pct': (round(c['receptions'] / c['targets'] * 100, 1)
                              if c['targets'] >= 50 and yr not in NFL_TARGETS_BROKEN else None),
                'pass_yds': int(c['passing_yards']), 'pass_td': int(c['passing_tds']),
                'int': int(c['interceptions']), 'att': int(c['attempts']),
                'rush_ypg': round(c['rushing_yards'] / g, 1),
                'rec_ypg': round(c['receiving_yards'] / g, 1),
                'ypc': round(c['rushing_yards'] / c['carries'], 1) if c['carries'] >= 100 else None,
                'ypr': round(c['receiving_yards'] / c['receptions'], 1) if c['receptions'] >= 30 else None,
            },
        }
    return out, max(seasons)


# ---------------------------------------------------------------- NBA
def nba_seasons(pool_all, gate=True):
    """Season-level per-game averages, keyed by stats.nba.com player_id.

    Season questions only, never careers: the data starts at 2000, so a career line
    for anyone who played earlier would be a partial career presented as a whole —
    the same class of error as an active player's totals going stale, but silent.
    A single season is frozen history and safe forever.
    """
    pool = pool_all['NBA']
    rows = _read(NBA_COMPACT)
    names, career = {}, Counter()
    for r in rows:
        names[r['player_id']] = r['player_name']
        career[r['player_id']] += float(r['gp'] or 0)
    by_name = defaultdict(list)
    for pid, nm in names.items():
        by_name[norm(nm)].append(pid)
    chosen = disambiguate(by_name, lambda pid: career[pid])
    id_key = {pid: key for key, pid in chosen.items()}

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    out, seasons = {}, set()
    for r in rows:
        pid = r['player_id']
        if pid not in id_key:
            continue
        key = id_key[pid]
        if gate and key not in pool:
            continue
        gp, yr = num(r['gp']), int(r['season'])
        seasons.add(yr)
        if not gp or gp < 40:                       # a partial season isn't a season
            continue
        st = {k: num(r.get(k)) for k in
              ('pts', 'reb', 'ast', 'stl', 'blk', 'fga', 'fg3a', 'fg3_pct', 'min',
               'tov', 'usg_pct', 'ts_pct')}
        if st['pts'] is None:
            continue
        st['ra'] = (round(st['reb'] + st['ast'], 1)
                    if None not in (st['reb'], st['ast']) else None)
        # Percentages ship as 0-1 in the source; the game labels them as percentages.
        for k in ('ts_pct', 'fg3_pct', 'usg_pct'):
            if st[k] is not None:
                st[k] = round(st[k] * 100, 1)
        out[(key, yr)] = {
            'name': names[pid], 'season': yr, 'games': int(gp), 'who': key,
            'player_id': pid, 'pool': pool.get(key, {'Tier': '', 'Status': ''}),
            'stats': st,
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
    # Everything above ends in home runs, which made the MLB half of the pool one
    # chart with the answer moved. These pair a stat you rarely see plotted with one
    # everybody reads instantly, which is the shape the game is actually about.
    dict(id='3b-hr',   x='3B',  y='HR',  xl='Career triples', xu='3B',
         yl='Career home runs', yu='HR', xstep=1, ystep=1, minab=5000),
    dict(id='so-avg',  x='SO',  y='AVG', xl='Career strikeouts', xu='SO',
         yl='Career batting average', yu='AVG', xstep=1, ystep=0.001, minab=5000),
    dict(id='sb-rbi',  x='SB',  y='RBI', xl='Career stolen bases', xu='SB',
         yl='Career runs batted in', yu='RBI', xstep=1, ystep=1, minab=5000),
    dict(id='bb-so',   x='BB',  y='SO',  xl='Career walks', xu='BB',
         yl='Career strikeouts', yu='SO', xstep=1, ystep=1, minab=5000),
    dict(id='g-hr',    x='G',   y='HR',  xl='Career games played', xu='G',
         yl='Career home runs', yu='HR', xstep=1, ystep=1, minab=5000),
    dict(id='h-bb',    x='H',   y='BB',  xl='Career hits', xu='H',
         yl='Career walks', yu='BB', xstep=1, ystep=1, minab=5000),
    dict(id='r-sb',    x='R',   y='SB',  xl='Career runs scored', xu='R',
         yl='Career stolen bases', yu='SB', xstep=1, ystep=1, minab=5000),
]

MLB_PITCH_ARCHETYPES = [
    # Every one of these pairs something you rarely see plotted against something a
    # baseball fan reads instantly, which is the shape the game is built on.
    dict(id='so-era',  x='SO',  y='ERA', xl='Career strikeouts', xu='K',
         yl='Career earned run average', yu='ERA', xstep=1, ystep=0.01,
         need=('IP', 1000)),
    # The chart the entire "wins are a bad statistic" argument has always wanted.
    dict(id='w-era',   x='W',   y='ERA', xl='Career wins', xu='W',
         yl='Career earned run average', yu='ERA', xstep=1, ystep=0.01,
         need=('IP', 1000)),
    dict(id='k9-bb9',  x='K9',  y='BB9', xl='Career strikeouts per nine innings',
         xu='K/9', yl='Career walks per nine innings', yu='BB/9',
         xstep=0.1, ystep=0.1, need=('IP', 1000)),
    # An era question wearing a player question's clothes: a 1970s workhorse and a
    # modern strikeout arm sit in opposite corners and never meet.
    dict(id='cg-so',   x='CG',  y='SO',  xl='Career complete games', xu='CG',
         yl='Career strikeouts', yu='K', xstep=1, ystep=1, need=('IP', 1000)),
    # Closers, where the counting stat and the quality stat come apart hard. The
    # innings gate has to drop or every reliever is filtered out before we start.
    dict(id='sv-era',  x='SV',  y='ERA', xl='Career saves', xu='SV',
         yl='Career earned run average', yu='ERA', xstep=1, ystep=0.01,
         need=('SV', 50)),
    dict(id='ip-so',   x='IP',  y='SO',  xl='Career innings pitched', xu='IP',
         yl='Career strikeouts', yu='K', xstep=0.1, ystep=1, need=('IP', 1000)),
    dict(id='whip-so', x='WHIP', y='SO', xl='Career WHIP', xu='WHIP',
         yl='Career strikeouts', yu='K', xstep=0.01, ystep=1, need=('IP', 1000)),
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
    dict(id='carries-rushtd', x='carries', y='rush_td', xl='Carries (season)', xu='carries',
         yl='Rushing touchdowns (season)', yu='TDs', xstep=1, ystep=1,
         need=('carries', 120)),
    dict(id='rec-rectd', x='rec', y='rec_td', xl='Receptions (season)', xu='rec',
         yl='Receiving touchdowns (season)', yu='TDs', xstep=1, ystep=1,
         need=('rec', 40)),
    dict(id='ypr-recyds', x='ypr', y='rec_yds', xl='Yards per catch (season)', xu='YPC',
         yl='Receiving yards (season)', yu='yards', xstep=0.1, ystep=1,
         need=('rec_yds', 700)),
    dict(id='comp-passtd', x='comp', y='pass_td', xl='Completions (season)', xu='comp',
         yl='Passing touchdowns (season)', yu='TDs', xstep=1, ystep=1,
         need=('pass_yds', 3000)),
    # Receivers. The pool leaned on running backs because rushing archetypes were
    # written first; every column these need was already in the cache, unused.
    #
    # Deliberately NO target-derived archetypes. Targets echo receptions for six
    # seasons, which shipped four wrong values before it was noticed, and a column
    # that needs an era-specific asterisk to be trusted is one that will be trusted
    # wrongly again. Receptions carries the same meaning with none of that: it is
    # counted the same way in every season and it is the number a fan already knows.
    # The withholding logic and the verifier gate stay in place regardless, so
    # re-adding a target archetype fails loudly rather than quietly.
    dict(id='airyds-yac', x='air_yds', y='yac', xl='Receiving air yards (season)',
         xu='air yds', yl='Yards after catch (season)', yu='YAC', xstep=1, ystep=1,
         need=('rec_yds', 700)),
    dict(id='rec-fd', x='rec', y='rec_fd', xl='Receptions (season)', xu='rec',
         yl='Receiving first downs (season)', yu='1st downs', xstep=1, ystep=1,
         need=('rec', 45)),
    dict(id='airyds-rectd', x='air_yds', y='rec_td', xl='Receiving air yards (season)',
         xu='air yds', yl='Receiving touchdowns (season)', yu='TDs', xstep=1, ystep=1,
         need=('rec_yds', 600)),
    dict(id='rushtd-rectd', x='rush_td', y='rec_td', xl='Rushing touchdowns (season)',
         xu='TDs', yl='Receiving touchdowns (season)', yu='TDs', xstep=1, ystep=1,
         need=('rush_yds', 400)),
]


NBA_ARCHETYPES = [
    dict(id='ppg-ra', x='pts', y='ra', xl='Points per game (season)', xu='PPG',
         yl='Rebounds + assists per game (season)', yu='REB+AST',
         xstep=0.1, ystep=0.1, need=('pts', 12)),
    dict(id='fga-ts', x='fga', y='ts_pct', xl='Field goal attempts per game (season)',
         xu='FGA', yl='True shooting percentage (season)', yu='TS%',
         xstep=0.1, ystep=0.1, need=('fga', 8)),
    dict(id='stl-blk', x='stl', y='blk', xl='Steals per game (season)', xu='SPG',
         yl='Blocks per game (season)', yu='BPG', xstep=0.1, ystep=0.1,
         need=('min', 24)),
    dict(id='mpg-ppg', x='min', y='pts', xl='Minutes per game (season)', xu='MPG',
         yl='Points per game (season)', yu='PPG', xstep=0.1, ystep=0.1,
         need=('pts', 12)),
    dict(id='3pa-3pct', x='fg3a', y='fg3_pct', xl='3-point attempts per game (season)',
         xu='3PA', yl='3-point percentage (season)', yu='3P%', xstep=0.1, ystep=0.1,
         need=('fg3a', 3)),
    dict(id='usg-ts', x='usg_pct', y='ts_pct', xl='Usage rate (season)', xu='USG%',
         yl='True shooting percentage (season)', yu='TS%', xstep=0.1, ystep=0.1,
         need=('min', 24)),
    dict(id='ast-tov', x='ast', y='tov', xl='Assists per game (season)', xu='APG',
         yl='Turnovers per game (season)', yu='TOV', xstep=0.1, ystep=0.1,
         need=('min', 24)),
    dict(id='reb-ast', x='reb', y='ast', xl='Rebounds per game (season)', xu='RPG',
         yl='Assists per game (season)', yu='APG', xstep=0.1, ystep=0.1,
         need=('min', 24)),
    dict(id='pts-ast', x='pts', y='ast', xl='Points per game (season)', xu='PPG',
         yl='Assists per game (season)', yu='APG', xstep=0.1, ystep=0.1,
         need=('pts', 12)),
    dict(id='reb-blk', x='reb', y='blk', xl='Rebounds per game (season)', xu='RPG',
         yl='Blocks per game (season)', yu='BPG', xstep=0.1, ystep=0.1,
         need=('min', 24)),
    dict(id='fg3a-ts', x='fg3a', y='ts_pct', xl='3-point attempts per game (season)',
         xu='3PA', yl='True shooting percentage (season)', yu='TS%',
         xstep=0.1, ystep=0.1, need=('fg3a', 3)),
    dict(id='tov-pts', x='tov', y='pts', xl='Turnovers per game (season)', xu='TOV',
         yl='Points per game (season)', yu='PPG', xstep=0.1, ystep=0.1,
         need=('min', 24)),
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


def ref_combos(n, seed):
    """Index triples into the sorted eligible list, to use as reference players.

    WHY THIS IS JITTERED AND NOT FIXED
    This used to be four hardcoded quantile triples — (0, n//2, n-1) and friends —
    tried in order until one scored. Almost every target took the first, so every
    chart in an archetype ended up anchored at the same three quantiles. For career
    stats, where the eligible set barely changes between targets, that meant the
    literal same three players: one batch produced four "career strikeouts vs career
    home runs" questions all anchored on Lofton, Aaron and Henderson. For season
    stats it was subtler and just as repetitive — different names, but sitting at the
    same three x-positions on every chart, because a quantile is a position.

    The seed is derived from the archetype and the target, so a given question always
    gets the same references and builds stay reproducible. It is deliberately NOT
    global randomness: a generator whose output changes run to run makes the
    verification step meaningless.
    """
    rnd = random.Random(seed)
    lo_hi, mid_hi = max(1, n // 3), max(2, 2 * n // 3)
    combos = [(0, n // 2, n - 1), (n // 4, n // 2, 3 * n // 4),
              (0, n // 3, 2 * n // 3), (n // 3, 2 * n // 3, n - 1)]
    for _ in range(10):
        lo = rnd.randrange(0, lo_hi)
        mid = rnd.randrange(lo_hi, mid_hi)
        hi = rnd.randrange(mid_hi, n)
        combos.append((lo, mid, hi))
    return combos


def build(entries, archetypes, league, label_fn, source, top, per_arch=2, only=None,
          per_player=1):
    """entries: list of player/season dicts. Returns ranked candidate questions.

    `only` is a normalised player key. Passing one builds a THEMED DAY: every
    candidate has that player as the answer, and the two rules that normally stop a
    player recurring — one question per person, and never re-use someone who is
    already an answer in the pool — are lifted, because for a themed day recurrence
    is the entire point. Those rules exist to stop a player meeting Rod Carew in
    three rounds by accident; a Kobe Bryant day is not an accident.

    They are lifted for the TARGET only. References are still three distinct people
    and still exclude every other season of the target, so a chart never shows the
    answer sitting next to himself.
    """
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
        # How often each player has already been used as a reference in THIS
        # archetype. Spreading references around is the difference between a pool
        # that feels like many charts and one that feels like a single chart with the
        # answer moved — a sameness players notice without being able to name it.
        ref_use = Counter()
        # A themed day narrows who can be the ANSWER; `elig` stays whole, so the
        # references still come from the full field.
        targets = [e for e in elig if e['who'] == only] if only else elig
        for tgt in targets:
            # Three references that bracket the target on both axes. Exclude every
            # other season by the same player: "guess Marshawn Lynch 2012" with
            # Marshawn Lynch 2008 sitting on the chart as a reference is a muddle,
            # not a hint.
            others = [e for e in elig if e['who'] != tgt['who']]
            others.sort(key=lambda e: (e['stats'][xk], e['stats'][yk]))
            n = len(others)
            key = (arch['id'], label_fn(tgt))
            if key in seen or n < 4:
                continue
            # Evaluate every combo and take the best, rather than the first that
            # merely works. "First that works" is what collapsed all of these onto
            # one set of anchors: the first combo tried almost always scored, so the
            # remaining three were dead code in practice.
            seed = zlib.crc32(f"{arch['id']}|{tgt['who']}".encode())
            best = None
            for combo in ref_combos(n, seed):
                if len(set(combo)) < 3 or max(combo) >= n:
                    continue
                refs = [others[i] for i in combo]
                # Three distinct players, not three seasons of the same one: a chart
                # with Shawn Marion 2001-02 and Shawn Marion 2007-08 as two separate
                # reference dots reads as a mistake.
                if len({r['who'] for r in refs}) < 3:
                    continue
                s = score_candidate(tgt, refs, xk, yk)
                if s is None:
                    continue
                # Penalise anchors this archetype has already leaned on. Weight is
                # small on purpose: a genuinely better chart should still win over a
                # fresher but weaker one.
                s -= 0.18 * sum(ref_use[r['who']] for r in refs)
                if best is None or s > best[0]:
                    best = (s, refs)
            if best is None:
                continue
            s, refs = best
            seen.add(key)
            for r in refs:
                ref_use[r['who']] += 1
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
                'target_who': tgt['who'],
                'targetX': tgt['stats'][xk], 'targetY': tgt['stats'][yk],
                'referencePlayers': [
                    {'name': label_fn(r), 'x': r['stats'][xk], 'y': r['stats'][yk]}
                    for r in refs],
                'fact': '', 'source': source,
            })
    out.sort(key=lambda c: -c['score'])
    # At most `per_arch` per archetype so a batch isn't six versions of one idea, and
    # one question per player — Rod Carew is a great answer three different ways,
    # but a player who wants five distinct rounds shouldn't meet him in all of them.
    #
    # Players already used as the ANSWER to a shipped question. Without this the
    # generator re-proposes the same top-ranked names on every run — a second batch
    # came back with 6 new candidates out of 80, because 74 were questions the pool
    # already had. The point of a batch is new content, so what already shipped has
    # to be an input.
    # Two different keys on purpose. Within a run the dataset's player id is the
    # right identity — it is what disambiguated the two Ricky Williamses. Against the
    # shipped pool only the display name is available, since questions.json stores no
    # ids, so that comparison has to go through normalised names.
    shipped = shipped_targets() if not only else set()
    # per_player > 1 lets one player answer more than one question, and it is what
    # makes a long calendar possible at all: an NBA player has sixteen distinct
    # seasons and the pool was using one of them. The rule it relaxes exists to stop
    # somebody meeting Rod Carew in three rounds out of five — across seventy days
    # that costs far more than it protects.
    #
    # Only ever with a DIFFERENT season and a different archetype, so the second
    # question is a different question and not the same chart re-dealt. For a career
    # league there is only one career, so callers leave this at 1 there.
    per, used, final = Counter(), Counter(), []
    seasons_used = defaultdict(set)
    for c in out:
        a = c['id'].split('-')[1]
        who = c['target_who']
        season = c['targetPlayer'].split(',')[-1].strip() if ',' in c['targetPlayer'] else None
        # On a themed day the same person is the answer every round by design, so the
        # one-per-player rule is skipped — but one question per ARCHETYPE still holds,
        # or five Kobe questions could all be usage-vs-true-shooting with the season
        # swapped, which is one question shown five times.
        if per[a] >= per_arch:
            continue
        if not only:
            if used[who] >= per_player:
                continue
            # A second question about the same player has to be a second SEASON.
            if season is not None and season in seasons_used[who]:
                continue
            if norm(c['targetPlayer'].split(',')[0]) in shipped:
                continue
        per[a] += 1
        used[who] += 1
        if season is not None:
            seasons_used[who].add(season)
        final.append(c)
    return final[:top]


def shipped_targets():
    """Normalised identities of every player who is already the answer to a question.

    Matched on the normalised name rather than the dataset's internal id, because the
    pool stores display names ("Jermaine O'Neal, 2002-03") and the generator works in
    player ids. A season suffix is stripped so a player cannot come back as the answer
    to a different season of the same archetype — appearing as the answer twice is
    the thing being prevented, and which season it was does not change that."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data',
                        'questions.json')
    if not os.path.exists(path):
        return set()
    out = set()
    for q in json.load(open(path, encoding='utf-8')):
        out.add(norm(q['targetPlayer'].split(',')[0]))
    return out


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
    nba, nbamax = nba_seasons(pool, gate=False)

    print('Name-collision guards')
    rw = nfl.get((norm('Ricky Williams'), 2003))
    good = bool(rw) and rw['stats']['rush_yds'] == 1372 and rw['stats']['carries'] == 392
    ok &= good
    print(f"  Ricky Williams 2003 = {rw['stats']['rush_yds'] if rw else '?'} yds / "
          f"{rw['stats']['carries'] if rw else '?'} car   (must be 1372/392, not the "
          f"1527/440 of two players summed)   {'ok' if good else 'MISMATCH'}")
    # Era guard: these are the checks that established NFL_MIN_SEASON. Counts are
    # exact in every era; the 1999 yardage gap is why pre-2002 seasons are excluded.
    faulk = nfl.get((norm('Marshall Faulk'), 1999))
    drift = faulk and abs(faulk['stats']['rush_yds'] - 1381) > 50
    ok &= bool(drift)
    print(f"  pre-2002 yardage drift still present (Faulk 1999 = "
          f"{faulk['stats']['rush_yds'] if faulk else '?'} vs official 1381), so "
          f"NFL content stays >= {NFL_MIN_SEASON}   {'ok' if drift else 'RECHECK'}")
    for nm, yr, col, exp in [('Peyton Manning', 2004, 'pass_td', 49),
                             ('Randy Moss', 2007, 'rec_td', 23),
                             ('Larry Fitzgerald', 2016, 'rec', 107),
                             ('Chris Johnson', 2009, 'rush_yds', 2006)]:
        e = nfl.get((norm(nm), yr))
        good = bool(e) and e['stats'][col] == exp
        ok &= good
        print(f"  {nm:20}{yr} {col:9} {e['stats'][col] if e else '?':>6} (exp {exp:>6})   "
              f"{'ok' if good else 'MISMATCH'}")
    kobe = nba.get((norm('Kobe Bryant'), 2005))
    fga_ok = bool(kobe) and 20 < kobe['stats']['fga'] < 30
    ok &= fga_ok
    print(f"  NBA FGA is per-game, not a season total: Kobe 2005-06 = "
          f"{kobe['stats']['fga'] if kobe else '?'} (must be ~27, not ~2173)   "
          f"{'ok' if fga_ok else 'MISMATCH'}")
    amb = norm('Ken Griffey') not in mlb
    ok &= amb
    print(f"  'Ken Griffey' dropped as ambiguous (Sr and Jr both qualify)   "
          f"{'ok' if amb else 'STILL PRESENT'}")

    print(f'NBA (hoopR / stats.nba.com) — data through {nbamax}')
    for nm, yr, pts, reb, ast in [('Stephen Curry', 2016, 25.3, 4.5, 6.6),
                                  ('Russell Westbrook', 2016, 31.6, 10.7, 10.4),
                                  ('James Harden', 2018, 36.1, 6.6, 7.5),
                                  ('Nikola Jokic', 2021, 27.1, 13.8, 7.9),
                                  ('Rudy Gobert', 2016, 14.0, 12.8, 1.2)]:
        e = nba.get((norm(nm), yr))
        if not e:
            print(f'  {nm:22} NOT FOUND'); ok = False; continue
        st = e['stats']
        good = (abs(st['pts']-pts) < .05 and abs(st['reb']-reb) < .05
                and abs(st['ast']-ast) < .05)
        ok &= good
        print(f"  {nm:20}{yr}-{str(yr+1)[2:]}  {st['pts']:>5} pts / {st['reb']:>5} reb / "
              f"{st['ast']:>5} ast  (exp {pts}/{reb}/{ast})   {'ok' if good else 'MISMATCH'}")

    print('\nVALIDATION', 'PASSED' if ok else 'FAILED')
    return 0 if ok else 1


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fetch', action='store_true')
    ap.add_argument('--validate', action='store_true')
    ap.add_argument('--league', choices=['mlb', 'mlbp', 'nfl', 'nba'],
                    help="mlbp is MLB pitchers, which are a separate dataset "
                         "(Pitching.csv) and separate archetypes from the hitters")
    ap.add_argument('--top', type=int, default=10)
    ap.add_argument('--per-archetype', type=int, default=2)
    ap.add_argument('--per-player', type=int, default=1,
                    help='how many questions one player may answer, each from a '
                         'different season (season leagues only)')
    ap.add_argument('--only', metavar='PLAYER',
                    help='themed day: build candidates whose ANSWER is always this '
                         'player, one per archetype (e.g. --only "Kobe Bryant")')
    ap.add_argument('--json')
    a = ap.parse_args()
    # Resolved once, and loudly: a typo'd name would otherwise produce an empty batch
    # that looks like "no good candidates" rather than "no such player".
    only = norm(a.only) if a.only else None

    if a.fetch:
        print('fetching:'); fetch(); return 0
    if a.validate:
        return validate()
    if not a.league:
        ap.print_help(); return 1

    pool = load_pool()
    if a.league == 'nba':
        entries, dmax = nba_seasons(pool)
        elig = list(entries.values())
        cands = build(elig, NBA_ARCHETYPES, 'NBA',
                      lambda e: f"{e['name']}, {e['season']}-{str(e['season']+1)[2:]}",
                      NBA_SOURCE, a.top, a.per_archetype, only=only,
                      per_player=a.per_player)
    elif a.league == 'mlb':
        entries, dmax = mlb_careers(pool)
        # career questions only for players whose career finished inside the data
        elig = [e for e in entries.values()
                if e['career_complete'] and e['pool']['Status'] == 'Retired']
        cands = build(elig, MLB_ARCHETYPES, 'MLB', lambda e: e['name'], MLB_SOURCE, a.top, a.per_archetype, only=only)
    elif a.league == 'mlbp':
        entries, dmax = mlb_pitchers(pool)
        # Same staleness rule as the hitters: a career line for someone still playing
        # is a snapshot being presented as a finished career.
        elig = [e for e in entries.values()
                if e['career_complete'] and e['pool']['Status'] == 'Retired']
        cands = build(elig, MLB_PITCH_ARCHETYPES, 'MLB', lambda e: e['name'],
                      MLB_PITCH_SOURCE, a.top, a.per_archetype, only=only)
    else:
        entries, dmax = nfl_seasons(pool)
        # season questions are frozen history — no staleness risk at all
        elig = [e for e in entries.values() if e['season'] >= NFL_MIN_SEASON]
        cands = build(elig, NFL_ARCHETYPES, 'NFL',
                      lambda e: f"{e['name']}, {e['season']}", NFL_SOURCE, a.top, a.per_archetype, only=only,
                      per_player=a.per_player)

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

    for c in cands:
        c.pop('target_who', None)
    if a.json:
        with open(a.json, 'w') as fh:
            json.dump(cands, fh, indent=2)
        print(f'wrote {a.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
