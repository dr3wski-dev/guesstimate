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
    'Career times struck out': 'SO',
    'Career triples': '3B',
    'Career walks': 'BB',
    'Career runs batted in': 'RBI',
    'Career runs scored': 'R',
    'Career games played': 'G',
    'Career hits': 'H',
}
# Pitchers are a separate table, keyed the same way. Kept apart from MLB_LABELS
# because 'H' means hits-by-a-batter in one and hits-allowed in the other — one
# shared table would silently check a pitcher's hits allowed against a hitter's hits.
MLB_PITCH_LABELS = {
    'Career strikeouts': 'SO',
    'Career earned run average': 'ERA',
    'Career wins': 'W',
    'Career saves': 'SV',
    'Career complete games': 'CG',
    'Career innings pitched': 'IP',
    'Career WHIP': 'WHIP',
    'Career strikeouts per nine innings': 'K9',
    'Career walks per nine innings': 'BB9',
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
    'Rebounds per game (season)': 'reb',
    'Assists per game (season)': 'ast',
    'Turnovers per game (season)': 'tov',
}
# Sacrifice flies enter the record in 1954. Before that the column is blank, which
# read as zero shrinks an on-base denominator and nudges the figure up — invisibly,
# and in the direction that looks right. Independent of the generator's own constant
# by design; if the two ever disagree the gate is what notices.
MLB_SF_RECORDED_FROM = 1954
# The MLB minigame's axes: career rate lines. 'Career games played' is deliberately
# NOT here — it already means 'G' in MLB_LABELS and resolves identically, so adding
# a second entry for it would be two names for one lookup.
MLB_CAREER_LABELS = {
    'Career batting average': 'AVG',
    'Career on-base percentage': 'OBP',
    'Career slugging percentage': 'SLG',
    'Career OPS (on-base plus slugging)': 'OPS',
    'Career isolated power (slugging minus average)': 'ISO',
    'Career walk rate (share of plate appearances)': 'BBPCT',
    'Career strikeout rate (share of plate appearances)': 'SOPCT',
    'Career home runs per 600 plate appearances': 'HR600',
    'Career stolen bases per 600 plate appearances': 'SB600',
    'Career runs scored per game': 'RG',
    'Career runs batted in per game': 'RBIG',
    'Career games played': 'G',
}
MLB_PITCH_CAREER_LABELS = {
    'Career earned run average': 'ERA',
    'Career WHIP (walks + hits per inning)': 'WHIP',
    'Career strikeouts per nine innings': 'K9',
    'Career walks per nine innings': 'BB9',
    'Career hits allowed per nine innings': 'H9',
    'Career strikeout-to-walk ratio': 'KBB',
    'Career win percentage': 'WPCT',
    'Career innings pitched': 'IP',
}
# The NBA minigame's axes. Kept apart from NBA_LABELS, which is all season figures
# and says so in every label, because these are whole-career averages: one shared
# table would let a career question be checked against a season row and pass.
NBA_CAREER_LABELS = {
    'Career games played': 'G',
    'Career points per game': 'ppg',
    'Career rebounds per game': 'rpg',
    'Career assists per game': 'apg',
    'Career steals per game': 'spg',
    'Career blocks per game': 'bpg',
    'Career minutes per game': 'mpg',
    'Career turnovers per game': 'topg',
    'Career shot attempts per game': 'fgapg',
    'Career 3-point attempts per game': 'tpapg',
    'Career rebounds + assists per game': 'rapg',
    'Career 3-point percentage': 'tppct',
    'Career assists per turnover': 'astto',
}
# Published career points per game for the players whose first season in the cache IS
# the first season the cache covers.
#
# WHY THIS IS HERE AND NOT IMPORTED FROM THE GENERATOR
# For the same reason this whole file re-derives rather than re-reads. The cache
# cannot tell "debuted that year" from "was already playing when coverage began", so
# a career average for anyone at the boundary is either a complete career or a
# truncated one wearing the same clothes — and a truncated one is the dangerous case,
# because both sides would compute it identically and agree. Karl Malone comes out of
# this cache at 23.5 points a game against a published 25.0.
#
# So the rule below is independent of the generator's: a boundary player not named
# here is refused outright, and a boundary player named here must also reproduce the
# published figure. The generator keeps its own copy of these numbers; if the two
# lists ever disagree about who is complete, the gate fails, which is the point of
# not sharing them.
#
# Source: Basketball-Reference career regular-season averages.
NBA_CAREER_BOUNDARY_OK = {
    'allen iverson': 26.7,
    'kobe bryant': 25.0,
    'stephon marbury': 19.3,
    'ray allen': 18.9,
    'steve nash': 14.3,
    'jermaine oneal': 13.2,
    'marcus camby': 9.5,
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
    'Carries (season)': 'carries',
    'Receiving touchdowns (season)': 'rec_td',
    'Yards per catch (season)': 'ypr',
    'Targets (season)': 'tgt',
    'Completions (season)': 'comp',
    'Air yards on all targets (season)': 'air_yds',
    'Yards after catch (season)': 'yac',
    'Receiving first downs (season)': 'rec_fd',
    'Yards per target (season)': 'ypt',
    'Catch rate (season)': 'catch_pct',
}
# Seasons where a column exists but is not a measurement. Targets echo receptions in
# 2003-2008, and air yards are flat zero before 2006. Four values shipped from the
# first window before anyone checked, and THIS FILE PASSED THEM — it re-derived from
# the same broken column and agreed with the generator. Two readings of one bad
# source agreeing is not verification, so the windows are named here as well: a
# question that plots one now fails rather than reproduces.
NFL_TARGETS_BROKEN = range(2003, 2009)
NFL_AIRYARDS_FROM = 2006
NFL_SEASON_GATED = {
    'tgt': lambda yr: yr not in NFL_TARGETS_BROKEN,
    'ypt': lambda yr: yr not in NFL_TARGETS_BROKEN,
    'catch_pct': lambda yr: yr not in NFL_TARGETS_BROKEN,
    'air_yds': lambda yr: yr >= NFL_AIRYARDS_FROM,
    'yac': lambda yr: yr >= NFL_AIRYARDS_FROM,
    'rec_fd': lambda yr: yr >= NFL_AIRYARDS_FROM,
}


# Curator-confirmed disambiguations. The tables below deliberately refuse to guess
# between two players sharing a normalized name, which means a legitimately-authored
# question naming one of them can't be checked automatically. Pinning the exact
# dataset ID here keeps the question verifiable without weakening the general rule.
# Add an entry only when you have confirmed which player is meant.
MLB_ALIAS = {
    'Ken Griffey Jr.': 'griffke02',   # not griffke01, his father, debut 1973
}

NBA_ALIAS = {
    # not 1114, Jaren Jackson Sr., whose 1996-2001 seasons entered the cache when
    # coverage was extended back to 1996-97. The son's id is the one carrying the
    # 2018-19 debut and the 1.4-3.0 blocks per game; the father never blocked 0.2.
    'Jaren Jackson Jr.': '1628991',
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
    # Seasons come off the SAME rows the totals do, so a career span can never
    # describe a different player than the numbers beside it.
    seasons = defaultdict(set)
    for r in bat:
        seasons[r['playerID']].add(int(r['yearID']))
        for c in ('AB','H','HR','SB','2B','3B','SO','BB','RBI','R','G',
                  'HBP','SF','SH'):
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
        # Career rate line for the MLB minigame, recomputed from career totals.
        # Total bases counts a double as one hit plus one extra base; OBP's
        # denominator takes sacrifice flies and not sacrifice hits. Both are the
        # official definitions, and both have a plausible wrong version that would
        # move every number here by a believable amount.
        ab, bb, hbp, sf, sh = c['AB'], c['BB'], c['HBP'], c['SF'], c['SH']
        tb = c['H'] + c['2B'] + 2 * c['3B'] + 3 * c['HR']
        pa = ab + bb + hbp + sf + sh
        obp_den = ab + bb + hbp + sf
        slg = tb / ab
        # Every rate with a plate-appearance denominator is withheld for a career
        # that began before sacrifice flies were recorded, because the column is
        # BLANK rather than zero in those seasons and a blank read as nothing
        # inflates on-base percentage slightly for everyone who played then. The
        # generator declines to author those questions; this declines to confirm
        # them, which is the half that matters if the generator's gate ever slips.
        pa_ok = pa and min(seasons[pid]) >= MLB_SF_RECORDED_FROM
        obp = (c['H'] + bb + hbp) / obp_den if (obp_den and pa_ok) else None
        rate = lambda v, d: round(v / d, 1) if pa_ok else None
        return {'AS': len(asy[pid]), 'HR': c['HR'], 'SB': c['SB'],
                '2B': c['2B'], '3B': c['3B'], 'SO': c['SO'], 'BB': c['BB'],
                'RBI': c['RBI'], 'R': c['R'], 'G': c['G'], 'H': c['H'],
                'AVG': round(c['H'] / c['AB'], 3),
                'SLG': round(slg, 3),
                'ISO': round(slg - c['H'] / ab, 3),
                'OBP': round(obp, 3) if obp is not None else None,
                'OPS': round(obp + slg, 3) if obp is not None else None,
                'BBPCT': rate(100 * bb, pa),
                'SOPCT': rate(100 * c['SO'], pa),
                'HR600': rate(600 * c['HR'], pa),
                'SB600': rate(600 * c['SB'], pa),
                'RG': round(c['R'] / c['G'], 2) if c['G'] else None,
                'RBIG': round(c['RBI'] / c['G'], 2) if c['G'] else None,
                '_span': [min(seasons[pid]), max(seasons[pid])]}

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


def mlb_pitch_table():
    """{normalized name: {stat: value}} for pitchers, re-derived independently.

    Rates are recomputed from career totals rather than averaged over seasons, for the
    same reason the generator does it: averaging season ERAs weights a two-inning
    September the same as a 250-inning year and produces a number in no record book.
    Being a separate code path is the point — if both sides made the same mistake here
    they would agree with each other and both be wrong."""
    pitch, people = read('Pitching.csv'), read('People.csv')
    name_of = {p['playerID']: f"{p.get('nameFirst','')} {p.get('nameLast','')}".strip()
               for p in people}
    tot = defaultdict(Counter)
    seasons = defaultdict(set)
    for r in pitch:
        seasons[r['playerID']].add(int(r['yearID']))
        for c in ('W','L','G','GS','CG','SHO','SV','IPouts','H','ER','HR','BB','SO'):
            if r[c]:
                tot[r['playerID']][c] += int(r[c])

    claims = defaultdict(list)
    for pid, c in tot.items():
        if c['IPouts'] < 900:
            continue
        claims[norm(name_of.get(pid, ''))].append((pid, c))

    def row(pid, c):
        outs = c['IPouts']
        return {'SO': c['SO'], 'W': c['W'], 'SV': c['SV'], 'CG': c['CG'],
                'IP': round(outs / 3, 1),
                'ERA': round(c['ER'] * 27 / outs, 2),
                'K9': round(c['SO'] * 27 / outs, 1),
                'BB9': round(c['BB'] * 27 / outs, 1),
                'WHIP': round((c['H'] + c['BB']) * 3 / outs, 2),
                'H9': round(c['H'] * 27 / outs, 1),
                'KBB': round(c['SO'] / c['BB'], 2) if c['BB'] else None,
                'WPCT': (round(100 * c['W'] / (c['W'] + c['L']), 1)
                         if c['W'] + c['L'] else None),
                # Pitching rows only, so a pitcher's span is the years he pitched.
                '_span': [min(seasons[pid]), max(seasons[pid])]}

    out = {}
    for key, cl in claims.items():
        cl.sort(key=lambda t: -t[1]['IPouts'])
        if len(cl) > 1 and cl[1][1]['IPouts'] / cl[0][1]['IPouts'] >= 0.5:
            continue                                  # ambiguous name, refuse to guess
        out[key] = row(*cl[0])
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

    alias_of = {pid: '@' + label for label, pid in NBA_ALIAS.items() if pid in names}

    out = {}
    for r in rows:
        pid = r['player_id']
        keys = [norm(names[pid])] if pid in keep else []
        if pid in alias_of:
            keys.append(alias_of[pid])
        if not keys:
            continue
        st = {k: num(r.get(k)) for k in
              ('pts', 'reb', 'ast', 'stl', 'blk', 'fga', 'fg3a', 'fg3_pct', 'min',
               'tov', 'usg_pct', 'ts_pct')}
        if None not in (st['reb'], st['ast']):
            st['ra'] = round(st['reb'] + st['ast'], 1)
        for k in ('ts_pct', 'fg3_pct', 'usg_pct'):
            if st[k] is not None:
                st[k] = round(st[k] * 100, 1)
        for key in keys:
            out[(key, int(r['season']))] = st
    return out


def nba_career_table():
    """{normalized name: {stat: value}} — career averages, re-derived.

    FROM TOTALS, NOT FROM THE PER-GAME COLUMNS
    A career average is career totals over career games. Weighting the per-game
    season figures by games instead looks equivalent and is not: those figures are
    rounded to a tenth, and twenty of them accumulate enough error to move an answer
    by a whole scoring band — measured on Ray Allen, who comes out at 18.8 that way
    against an actual 18.9. The rates are rebuilt from components for the same
    reason: career 3-point percentage is career makes over career attempts, never an
    average of season percentages.

    It refuses in two situations rather than guessing, and both are failures worth
    having: a name two players share (same rule as every other table here), and a
    career that may be cut off at the front by where coverage begins (see
    NBA_CAREER_BOUNDARY_OK).
    """
    rows = read('nba_player_seasons.csv')
    names, games, years = {}, Counter(), defaultdict(set)
    tot = defaultdict(Counter)
    for r in rows:
        pid = r['player_id']
        names[pid] = r['player_name']
        games[pid] += float(r['gp'] or 0)
        years[pid].add(int(r['season']))
        for c in ('pts', 'reb', 'ast', 'stl', 'blk', 'fga', 'fg3a', 'fg3m', 'min', 'tov'):
            v = r.get('tot_' + c)
            if v not in ('', None):
                tot[pid][c] += float(v)
    coverage_start = min(int(r['season']) for r in rows)

    claims = defaultdict(list)
    for pid, nm in names.items():
        claims[norm(nm)].append(pid)
    alias = {pid: '@' + label for label, pid in NBA_ALIAS.items() if pid in names}

    out = {}
    for key, pids in claims.items():
        pids.sort(key=lambda p: -games[p])
        keys = []
        if not (len(pids) > 1 and games[pids[0]] > 0
                and games[pids[1]] / games[pids[0]] >= 0.5):
            keys.append(key)
        pid = pids[0]
        if pid in alias:
            keys.append(alias[pid])
        if not keys or not games[pid]:
            continue
        g = games[pid]
        per = lambda c: round(tot[pid][c] / g, 1)
        ppg = per('pts')
        if min(years[pid]) <= coverage_start:
            want = NBA_CAREER_BOUNDARY_OK.get(key)
            # Not on the confirmed list: this career may begin before the data does,
            # so no number derived from it can be trusted. Emitting nothing makes any
            # question about the player fail as unresolvable, which is the correct
            # outcome — it is exactly how a truncated career would otherwise ship.
            if want is None:
                continue
            if abs(ppg - want) > 0.05:
                continue
        st = {
            'G': int(g), 'ppg': ppg, 'rpg': per('reb'), 'apg': per('ast'),
            'spg': per('stl'), 'bpg': per('blk'), 'mpg': per('min'),
            'topg': per('tov'), 'fgapg': per('fga'), 'tpapg': per('fg3a'),
            'rapg': round((tot[pid]['reb'] + tot[pid]['ast']) / g, 1),
            'tppct': (round(100 * tot[pid]['fg3m'] / tot[pid]['fg3a'], 1)
                      if tot[pid]['fg3a'] else None),
            'astto': (round(tot[pid]['ast'] / tot[pid]['tov'], 2)
                      if tot[pid]['tov'] else None),
            '_span': [min(years[pid]), max(years[pid])],
        }
        for k in keys:
            out[k] = st
    return out


def nfl_table():
    """{(normalized name, season): {stat: value}} — keyed by player_id throughout."""
    rows = [r for r in read('nfl_player_stats.csv') if r.get('season_type') == 'REG']
    agg, wk, names, career = defaultdict(Counter), defaultdict(set), {}, Counter()
    for r in rows:
        pid, yr = r['player_id'], int(r['season'])
        names[pid] = r['player_display_name']
        wk[(pid, yr)].add(r['week'])
        for c in ('rushing_yards','rushing_tds','receiving_yards','receiving_tds',
                  'receptions','targets','completions','carries','passing_tds',
                  'interceptions','receiving_air_yards',
                  'receiving_yards_after_catch','receiving_first_downs'):
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
            'rec_td': int(c['receiving_tds']), 'tgt': int(c['targets']),
            'comp': int(c['completions']), 'carries': int(c['carries']),
            'pass_td': int(c['passing_tds']), 'int': int(c['interceptions']),
            'rush_ypg': round(c['rushing_yards'] / g, 1) if g else None,
            'ypc': round(c['rushing_yards'] / c['carries'], 1) if c['carries'] >= 100 else None,
            'ypr': round(c['receiving_yards'] / c['receptions'], 1) if c['receptions'] >= 30 else None,
            'air_yds': int(c['receiving_air_yards']),
            'yac': int(c['receiving_yards_after_catch']),
            'rec_fd': int(c['receiving_first_downs']),
            'ypt': (round(c['receiving_yards'] / c['targets'], 1)
                    if c['targets'] >= 50 else None),
            'catch_pct': (round(c['receptions'] / c['targets'] * 100, 1)
                          if c['targets'] >= 50 else None),
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
    mlbp = mlb_pitch_table()
    nba_career = nba_career_table()
    checked = mismatched = unverified = 0
    problems, skipped = [], []

    for q in questions:
        # Dispatch on the GAME first where one exists, then on the league. A career
        # question and a season question can carry the same league and completely
        # different axes, and resolving one against the other's table is a mismatch
        # this file would otherwise have to catch by luck.
        game = q.get('game')
        # Which pair of label tables this question is read through. Dispatch on the
        # GAME first where one exists: a career question and a season question can
        # carry the same league and completely different axes, and resolving one
        # against the other's table is a mismatch this file would otherwise catch
        # only by luck.
        hitting_labels, pitching_labels = {
            'nba': (NBA_CAREER_LABELS, {}),
            'mlb': (MLB_CAREER_LABELS, MLB_PITCH_CAREER_LABELS),
        }.get(game) or (
            {'MLB': MLB_LABELS, 'NFL': NFL_LABELS, 'NBA': NBA_LABELS}
            .get(q['league'], {}),
            MLB_PITCH_LABELS if q['league'] == 'MLB' else {},
        )
        xk, yk = hitting_labels.get(q['xLabel']), hitting_labels.get(q['yLabel'])
        # A pitching question is an MLB question whose labels are not in the hitters'
        # table. Resolve against the pitchers' table instead, and only if BOTH axes
        # are pitching stats — a chart mixing the two would be a bug worth catching,
        # not something to paper over by looking in two tables.
        pitching = (not (xk and yk)
                    and pitching_labels.get(q['xLabel'])
                    and pitching_labels.get(q['yLabel']))
        if pitching:
            xk = pitching_labels[q['xLabel']]
            yk = pitching_labels[q['yLabel']]
        if not xk or not yk:
            unverified += 1
            skipped.append(f"{q['id']} ({q['league']}: {q['xLabel']} / {q['yLabel']})")
            continue
        points = [(q['targetPlayer'], q['targetX'], q['targetY'], 'target', q)]
        points += [(r['name'], r['x'], r['y'], 'ref', r) for r in q['referencePlayers']]
        for who, gx, gy, kind, holder in points:
            nm, season = split_season(who)
            if game == 'nba':
                # No season: a career is the whole thing. A label that carries one
                # anyway is a question authored against the wrong table, so it is left
                # to fail on the lookup rather than quietly ignored.
                rec = None if season is not None else nba_career.get(norm(nm))
            elif q['league'] == 'MLB':
                rec = (mlbp.get(norm(nm)) if pitching
                       else (mlb.get('@' + who) or mlb.get(norm(nm))))
                if game == 'mlb' and season is not None:
                    rec = None
            elif q['league'] == 'NBA':
                rec = nba.get(('@' + nm, season)) or nba.get((norm(nm), season))
            else:
                rec = nfl.get((norm(nm), season))
            if rec is None:
                problems.append(f"{q['id']}: {kind} '{who}' not resolvable in the dataset")
                mismatched += 1
                continue
            # A career span is a claim about a person, so it gets re-derived like any
            # other number rather than trusted from the script that wrote it. It comes
            # off the same rows as the totals above, so a span that disagrees means the
            # name resolved to a different player than the stats did — which is the
            # failure this whole file exists to catch.
            span = holder.get('span')
            if span is not None:
                checked += 1
                actual = rec.get('_span')
                if actual is None or list(span) != list(actual):
                    mismatched += 1
                    problems.append(
                        f"{q['id']}: {kind} '{who}' span ships {span}, "
                        f"dataset says {actual}")

            for key, shipped, axis in ((xk, gx, 'x'), (yk, gy, 'y')):
                # A value from a season where this column is not a measurement is a
                # failure however well the two sides agree about it.
                gate = NFL_SEASON_GATED.get(key) if q['league'] == 'NFL' else None
                if gate and season is not None and not gate(season):
                    mismatched += 1
                    problems.append(
                        f"{q['id']}: {kind} '{who}' {axis} ({key}) comes from a season "
                        f"where that column carries no measurement")
                    continue
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
