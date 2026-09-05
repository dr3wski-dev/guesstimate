#!/usr/bin/env python3
"""
Add career spans — the years a player played — to career-stat questions.

WHY THIS IS A BACKFILL AND NOT A REGENERATION
The 565 questions in the pool were generated before spans existed. Re-running the
generator to pick them up would re-deal values and ids, and a question that has been
SERVED can never change: challenge links to a played day have to keep reproducing
what the sender saw. So this only ever ADDS a field. It never edits a stat, a name,
an id or a domain, and it asserts that at the end.

WHY ONLY MLB
Career spans have to come from the data like every other number here. Lahman covers
1871-2021, so every MLB career question resolves completely.

The NBA and NFL files do NOT, and this is the trap worth naming: nba_player_seasons
starts at 2000 and nfl_player_stats at 1999. Ask them for Dirk Nowitzki and they say
2000-2018 — he debuted in 1998. Allen Iverson comes back 2000-2009; he started in
1996. Wilt Chamberlain is not in the file at all. Those are truncation artifacts that
look exactly like facts, and shipping them would be fabricating data with a straight
face. The ten NBA/NFL career questions therefore get no span until a source that
covers their eras is wired up. `verify_questions.py` already lists those same ten as
unverified for the same underlying reason.

HOW A PLAYER IS IDENTIFIED
Not by name alone. The name narrows the field and the SHIPPED NUMBERS confirm it: a
candidate is only accepted if the career totals computed from Lahman reproduce both
values already in the question. That turns the backfill into a second verification
pass — if a name resolved to the wrong man, his stats would not match and the script
refuses rather than writing a plausible-looking span.

It is also how Ken Griffey Jr. is resolved. `norm()` strips the "Jr.", collapsing him
onto his father, and both men have the same given name in People.csv, so no amount of
string handling separates them. 630 home runs against 152 does.

  python3 pipeline/add_career_spans.py            # report only, writes nothing
  python3 pipeline/add_career_spans.py --write    # add the spans
"""
import csv, json, os, sys
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'cache')
QJSON = os.path.join(HERE, '..', 'data', 'questions.json')

# Imported, never re-typed. A span keyed to a different player than the stats were
# checked against would be worse than no span at all — and the first draft of this
# file proved the point by hand-copying the tables and getting two entries wrong:
# 'Career runs' for 'Career runs scored', and 'K' where the pitchers' table says
# 'SO'. Five questions silently fell out of the backfill. Sharing the definition
# makes that class of drift impossible rather than merely unlikely.
sys.path.insert(0, HERE)
from verify_questions import (                                     # noqa: E402
    MLB_LABELS, MLB_PITCH_LABELS, MLB_ALIAS, norm,
)


def read(name):
    with open(os.path.join(CACHE, name), newline='', encoding='utf-8-sig') as fh:
        return list(csv.DictReader(fh))


def load():
    """Per-playerID career totals, seasons played, and name — batting and pitching."""
    people = {p['playerID']: f"{p.get('nameFirst','')} {p.get('nameLast','')}".strip()
              for p in read('People.csv')}
    # Batting and pitching seasons are kept APART, not unioned. The span describes the
    # career the stat measures: a pitching question's years are the years he pitched.
    # A pitcher who took one late-career at-bat as a pinch hitter would otherwise get
    # a span a year longer than his pitching line, and verify_questions.py — which
    # reads each table separately — would rightly call it a mismatch.
    bat_years, pit_years = defaultdict(set), defaultdict(set)
    bat, pit = defaultdict(Counter), defaultdict(Counter)
    for r in read('Batting.csv'):
        bat_years[r['playerID']].add(int(r['yearID']))
        for c in ('AB', 'H', 'HR', 'SB', '2B', '3B', 'SO', 'BB', 'RBI', 'R', 'G'):
            if r[c]:
                bat[r['playerID']][c] += int(r[c])
    for r in read('Pitching.csv'):
        pit_years[r['playerID']].add(int(r['yearID']))
        for c in ('W', 'SO', 'SV', 'CG', 'IPouts', 'ER', 'BB', 'H'):
            if r[c]:
                pit[r['playerID']][c] += int(r[c])
    asy = defaultdict(set)
    for r in read('AllstarFull.csv'):
        asy[r['playerID']].add(int(r['yearID']))
    return people, bat_years, pit_years, bat, pit, asy


def bat_row(pid, c, asy):
    if not c['AB']:
        return {}
    return {'AS': len(asy[pid]), 'HR': c['HR'], 'SB': c['SB'], '2B': c['2B'],
            '3B': c['3B'], 'SO': c['SO'], 'BB': c['BB'], 'RBI': c['RBI'],
            'R': c['R'], 'G': c['G'], 'H': c['H'],
            'AVG': round(c['H'] / c['AB'], 3)}


def pit_row(pid, c):
    outs = c['IPouts']
    if not outs:
        return {}
    ip = outs / 3
    return {'W': c['W'], 'SO': c['SO'], 'SV': c['SV'], 'CG': c['CG'],
            'IP': round(ip, 1),
            'ERA': round(c['ER'] * 27 / outs, 2),
            'WHIP': round((c['BB'] + c['H']) / ip, 2),
            'K9': round(c['SO'] * 9 / ip, 1),
            'BB9': round(c['BB'] * 9 / ip, 1)}


def main(write):
    people, bat_years, pit_years, bat, pit, asy = load()
    by_name = defaultdict(list)
    for pid in set(bat_years) | set(pit_years):
        by_name[norm(people.get(pid, ''))].append(pid)

    questions = json.load(open(QJSON, encoding='utf-8'))
    before = json.dumps(questions, sort_keys=True)

    added = skipped_league = 0
    unresolved, mismatched = [], []

    for q in questions:
        career = 'Career' in q['xLabel'] or 'Career' in q['yLabel']
        if not career:
            continue
        if q['league'] != 'MLB':
            skipped_league += 1
            continue

        xk, yk = MLB_LABELS.get(q['xLabel']), MLB_LABELS.get(q['yLabel'])
        pitching = not (xk and yk)
        if pitching:
            xk = MLB_PITCH_LABELS.get(q['xLabel'])
            yk = MLB_PITCH_LABELS.get(q['yLabel'])
        if not xk or not yk:
            unresolved.append(f"{q['id']}: labels not in either MLB table")
            continue

        points = [(q, 'targetPlayer', q['targetPlayer'], q['targetX'], q['targetY'])]
        points += [(r, 'name', r['name'], r['x'], r['y']) for r in q['referencePlayers']]

        for holder, _key, who, gx, gy in points:
            cands = [MLB_ALIAS[who]] if who in MLB_ALIAS else by_name.get(norm(who), [])
            # The numbers decide, not the name. A candidate is accepted only if the
            # totals computed here reproduce BOTH values the question already ships.
            hits = []
            for pid in cands:
                row = pit_row(pid, pit[pid]) if pitching else bat_row(pid, bat[pid], asy)
                a, b = row.get(xk), row.get(yk)
                if a is None or b is None:
                    continue
                if abs(float(a) - float(gx)) < 1e-6 and abs(float(b) - float(gy)) < 1e-6:
                    hits.append(pid)
            if len(hits) == 1:
                pid = hits[0]
                ys = pit_years[pid] if pitching else bat_years[pid]
                holder['span'] = [min(ys), max(ys)]
                added += 1
            elif not hits:
                mismatched.append(f"{q['id']}: '{who}' — no candidate reproduces "
                                  f"{xk}={gx}, {yk}={gy}")
            else:
                unresolved.append(f"{q['id']}: '{who}' — {len(hits)} candidates match "
                                  f"identically, refusing to guess")

    print(f'career spans added: {added}')
    print(f'NBA/NFL career questions skipped (no era-complete source): {skipped_league}')
    if mismatched:
        print(f'\nCOULD NOT CONFIRM ({len(mismatched)}):')
        for m in mismatched:
            print('  ' + m)
    if unresolved:
        print(f'\nAMBIGUOUS ({len(unresolved)}):')
        for u in unresolved:
            print('  ' + u)

    if mismatched or unresolved:
        print('\nRefusing to write — resolve the above first.')
        return 1

    # Nothing but `span` may have changed. Cheap to assert, and the alternative is a
    # silent edit to a stat inside a question somebody has already played.
    check = json.loads(json.dumps(questions))
    for q in check:
        q.pop('span', None)
        for r in q['referencePlayers']:
            r.pop('span', None)
    if json.dumps(check, sort_keys=True) != before:
        print('\nABORT: something other than `span` changed. Nothing written.')
        return 1

    if write:
        with open(QJSON, 'w', encoding='utf-8') as fh:
            json.dump(questions, fh, indent=2, ensure_ascii=False)
            fh.write('\n')
        print(f'\nwrote {os.path.relpath(QJSON, os.path.join(HERE, ".."))}')
    else:
        print('\n(report only — pass --write to apply)')
    return 0


if __name__ == '__main__':
    sys.exit(main('--write' in sys.argv))
