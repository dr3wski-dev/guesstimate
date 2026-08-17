#!/usr/bin/env python3
"""
Independent verifier for data/questions.json.

Deliberately a separate code path from build_questions.py. The generator could be
wrong — it was: a name-keyed aggregation silently merged two different Ricky
Williamses and produced a plausible-looking 1527-yard season that never happened.
A verifier that reuses the generator's own aggregation would have agreed with it.
So this file re-reads the raw CSVs, re-derives every number from scratch by
(player, stat-label), and compares against what the question actually ships.

Questions whose stat labels aren't in the maps below are reported as UNVERIFIED
rather than passed — currently that's the NBA content, which has no open dataset
behind it yet (see LAUNCH_CHECKLIST.md).

  python3 pipeline/verify_questions.py
"""
import csv, json, os, re, sys, unicodedata
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'cache')
QJSON = os.path.join(HERE, '..', 'data', 'questions.json')

MLB_LABELS = {
    'Career All-Star selections': 'AS',
    'Career home runs': 'HR',
    'Career stolen bases': 'SB',
    'Career batting average': 'AVG',
    'Career doubles': '2B',
    'Career strikeouts': 'SO',
}
NBA_LABELS = {
    'Points per game (season)': 'pts',
    'Rebounds + assists per game (season)': 'ra',
    'Field goal attempts per game (season)': 'fga',
    'True shooting percentage (season)': 'ts_pct',
    'Steals per game (season)': 'stl',
    'Blocks per game (season)': 'blk',
    'Minutes per game (season)': 'min',
    '3-point attempts per game (season)': 'fg3a',
    '3-point percentage (season)': 'fg3_pct',
    'Usage rate (season)': 'usg_pct',
}
NFL_LABELS = {
    'Rushing yards per game (season)': 'rush_ypg',
    'Rushing touchdowns (season)': 'rush_td',
    'Yards per carry (season)': 'ypc',
    'Rushing yards (season)': 'rush_yds',
    'Receiving yards (season)': 'rec_yds',
    'Receptions (season)': 'rec',
    'Interceptions (season)': 'int',
    'Passing touchdowns (season)': 'pass_td',
}


# Curator-confirmed disambiguations. The tables below deliberately refuse to guess
# between two players sharing a normalized name, which means a legitimately-authored
# question naming one of them can't be checked automatically. Pinning the exact
# dataset ID here keeps the question verifiable without weakening the general rule.
# Add an entry only when you have confirmed which player is meant.
MLB_ALIAS = {
    'Ken Griffey Jr.': 'griffke02',   # not griffke01, his father, debut 1973
}


def norm(s):
    s = unicodedata.normalize('NFD', s.lower().strip())
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = re.sub(r'\b(jr|sr|ii|iii|iv)\b\.?', '', s)
    return re.sub(r"[^a-z ]", '', s).strip()


def read(name):
    path = os.path.join(CACHE, name)
    if not os.path.exists(path):
        # The raw datasets are ~43 MB and deliberately gitignored, so a fresh clone
        # has none of them. Without this the first thing a new contributor sees is a
        # FileNotFoundError traceback pointing at a path that was never supposed to
        # be in the repo, which reads like a broken checkout rather than a missing
        # download.
        sys.exit(f'missing dataset: {name}\n'
                 f'  The raw datasets are not committed (~43 MB). Download them with:\n'
                 f'    python3 handoff/pipeline/build_questions.py --fetch\n'
                 f'  then re-run this check.')
    with open(path, newline='', encoding='utf-8', errors='replace') as fh:
        return list(csv.DictReader(fh))


def mlb_table():
    """{normalized name: {stat: value}} — computed independently, keyed by playerID
    and only emitted when exactly one player of that name has a qualifying career."""
    bat, people, allstar = read('Batting.csv'), read('People.csv'), read('AllstarFull.csv')
    name_of = {p['playerID']: f"{p.get('nameFirst','')} {p.get('nameLast','')}".strip()
               for p in people}
    tot = defaultdict(Counter)
    for r in bat:
        for c in ('AB','H','HR','SB','2B','SO'):
            if r[c]:
                tot[r['playerID']][c] += int(r[c])
    asy = defaultdict(set)
    for r in allstar:
        asy[r['playerID']].add(int(r['yearID']))

    claims = defaultdict(list)
    for pid, c in tot.items():
        if c['AB'] < 3000:
            continue
        claims[norm(name_of.get(pid, ''))].append((pid, c))
    def row(pid, c):
        return {'AS': len(asy[pid]), 'HR': c['HR'], 'SB': c['SB'],
                '2B': c['2B'], 'SO': c['SO'], 'AVG': round(c['H'] / c['AB'], 3)}

    out = {}
    for key, cl in claims.items():
        cl.sort(key=lambda t: -t[1]['AB'])
        if len(cl) > 1 and cl[1][1]['AB'] / cl[0][1]['AB'] >= 0.5:
            continue                                  # ambiguous name, refuse to guess
        out[key] = row(*cl[0])
    for label, pid in MLB_ALIAS.items():
        if pid in tot:
            out['@' + label] = row(pid, tot[pid])
    return out


def nba_table():
    """{(normalized name, season): {stat: value}} from the compact NBA cache."""
    rows = read('nba_player_seasons.csv')
    names, career = {}, Counter()
    for r in rows:
        names[r['player_id']] = r['player_name']
        career[r['player_id']] += float(r['gp'] or 0)
    claims = defaultdict(list)
    for pid, nm in names.items():
        claims[norm(nm)].append(pid)
    keep = set()
    for key, pids in claims.items():
        pids.sort(key=lambda p: -career[p])
        if len(pids) > 1 and career[pids[0]] > 0 and career[pids[1]] / career[pids[0]] >= 0.5:
            continue
        keep.add(pids[0])

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    out = {}
    for r in rows:
        if r['player_id'] not in keep:
            continue
        st = {k: num(r.get(k)) for k in
              ('pts', 'reb', 'ast', 'stl', 'blk', 'fga', 'fg3a', 'fg3_pct', 'min',
               'usg_pct', 'ts_pct')}
        if None not in (st['reb'], st['ast']):
            st['ra'] = round(st['reb'] + st['ast'], 1)
        for k in ('ts_pct', 'fg3_pct', 'usg_pct'):
            if st[k] is not None:
                st[k] = round(st[k] * 100, 1)
        out[(norm(names[r['player_id']]), int(r['season']))] = st
    return out


def nfl_table():
    """{(normalized name, season): {stat: value}} — keyed by player_id throughout."""
    rows = [r for r in read('nfl_player_stats.csv') if r.get('season_type') == 'REG']
    agg, wk, names, career = defaultdict(Counter), defaultdict(set), {}, Counter()
    for r in rows:
        pid, yr = r['player_id'], int(r['season'])
        names[pid] = r['player_display_name']
        wk[(pid, yr)].add(r['week'])
        for c in ('rushing_yards','rushing_tds','receiving_yards','receptions',
                  'carries','passing_tds','interceptions'):
            if r.get(c):
                agg[(pid, yr)][c] += float(r[c])
        for c in ('rushing_yards','receiving_yards','passing_yards'):
            if r.get(c):
                career[pid] += float(r[c])

    claims = defaultdict(list)
    for pid in names:
        claims[norm(names[pid])].append(pid)
    keep = set()
    for key, pids in claims.items():
        pids.sort(key=lambda p: -career[p])
        if len(pids) > 1 and career[pids[0]] > 0 and career[pids[1]] / career[pids[0]] >= 0.5:
            continue
        keep.add(pids[0])

    out = {}
    for (pid, yr), c in agg.items():
        if pid not in keep:
            continue
        g = len(wk[(pid, yr)])
        out[(norm(names[pid]), yr)] = {
            'rush_yds': int(c['rushing_yards']), 'rush_td': int(c['rushing_tds']),
            'rec_yds': int(c['receiving_yards']), 'rec': int(c['receptions']),
            'pass_td': int(c['passing_tds']), 'int': int(c['interceptions']),
            'rush_ypg': round(c['rushing_yards'] / g, 1) if g else None,
            'ypc': round(c['rushing_yards'] / c['carries'], 1) if c['carries'] >= 100 else None,
        }
    return out


def split_season(label):
    # "Derrick Henry, 2020" and "Baron Davis, 2003-04" — the NBA form spans two
    # calendar years and is keyed on the start year.
    m = re.match(r'^(.*?),\s*(\d{4})(?:-\d{2})?$', label)
    return (m.group(1), int(m.group(2))) if m else (label, None)


def main():
    questions = json.load(open(QJSON))
    mlb, nfl, nba = mlb_table(), nfl_table(), nba_table()
    checked = mismatched = unverified = 0
    problems, skipped = [], []

    for q in questions:
        labels = ({'MLB': MLB_LABELS, 'NFL': NFL_LABELS, 'NBA': NBA_LABELS}
                  .get(q['league'], {}))
        xk, yk = labels.get(q['xLabel']), labels.get(q['yLabel'])
        if not xk or not yk:
            unverified += 1
            skipped.append(f"{q['id']} ({q['league']}: {q['xLabel']} / {q['yLabel']})")
            continue
        points = [(q['targetPlayer'], q['targetX'], q['targetY'], 'target')]
        points += [(r['name'], r['x'], r['y'], 'ref') for r in q['referencePlayers']]
        for who, gx, gy, kind in points:
            nm, season = split_season(who)
            if q['league'] == 'MLB':
                rec = mlb.get('@' + who) or mlb.get(norm(nm))
            elif q['league'] == 'NBA':
                rec = nba.get((norm(nm), season))
            else:
                rec = nfl.get((norm(nm), season))
            if rec is None:
                problems.append(f"{q['id']}: {kind} '{who}' not resolvable in the dataset")
                mismatched += 1
                continue
            for key, shipped, axis in ((xk, gx, 'x'), (yk, gy, 'y')):
                actual = rec.get(key)
                checked += 1
                if actual is None or abs(float(actual) - float(shipped)) > 1e-6:
                    mismatched += 1
                    problems.append(
                        f"{q['id']}: {kind} '{who}' {axis} ({key}) ships {shipped}, "
                        f"dataset says {actual}")

    print(f'questions: {len(questions)}   values re-derived: {checked}   '
          f'mismatches: {mismatched}   unverified questions: {unverified}')
    if skipped:
        print('\nUNVERIFIED (no open dataset wired up for these labels):')
        for s in skipped:
            print('  ' + s)
    if problems:
        print('\nPROBLEMS:')
        for p in problems:
            print('  ' + p)
    print('\nRESULT:', 'FAIL' if problems else 'all dataset-backed values reproduce exactly')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
