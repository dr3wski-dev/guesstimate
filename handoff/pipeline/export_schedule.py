#!/usr/bin/env python3
"""
Export the calendar as one flat table: every scheduled day, every question on it.

WHY THIS IS A SCRIPT AND NOT A COMMITTED FILE
The output is derived — schedule.json crossed with questions.json — and future days
are re-dealt on every content run, so a copy committed to the repo is stale within a
day. `content/questions.csv` is gitignored for the same reason, with the same note:
a stale export is a silent revert waiting to happen.

WHAT IT IS FOR
Reading the pool the way a person thinks about it, which is by date rather than by
id. Sort by league to see the rotation working, filter `status` to see what has
already gone out, filter `themed` to find the hand-authored days.

CAUTION: the output contains every answer for the whole calendar. It is the same
material as the demo build — fine on your machine, never anywhere public.

  python3 pipeline/export_schedule.py                 # -> content/schedule-master.csv
  python3 pipeline/export_schedule.py --xlsx          # also an .xlsx, if openpyxl is present
"""
import csv, datetime, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
OUT = os.path.join(HERE, '..', 'content', 'schedule-master.csv')

COLUMNS = ['date', 'puzzle', 'weekday', 'status', 'themed', 'slot', 'league',
           'question_id', 'answer', 'x_stat', 'x_value', 'y_stat', 'y_value',
           'reference_players', 'source']


def read(name):
    with open(os.path.join(DATA, name), encoding='utf-8') as fh:
        return json.load(fh)


def rows():
    pool = {q['id']: q for q in read('questions.json')}
    schedule = read('schedule.json')
    themed = read('themed_days.json') if os.path.exists(os.path.join(DATA, 'themed_days.json')) else {}

    # Same epoch and timezone the game uses, so the puzzle numbers in this file are
    # the numbers a player sees rather than a second opinion about them.
    epoch = datetime.date.fromisoformat(BAG_EPOCH)
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-4))).date()

    out = []
    for date in sorted(schedule):
        d = datetime.date.fromisoformat(date)
        for slot, qid in enumerate(schedule[date], 1):
            q = pool.get(qid)
            if q is None:
                # A pinned id with no question is exactly what schedule_days.mjs
                # --check exists to catch; say so here rather than emitting a row
                # that looks fine and is missing its numbers.
                sys.exit(f'{date} slot {slot}: id {qid!r} is not in the pool. '
                         f'Run `node pipeline/schedule_days.mjs --check`.')
            out.append({
                'date': date,
                'puzzle': (d - epoch).days + 1,
                'weekday': d.strftime('%a'),
                'status': 'played' if d <= today else 'upcoming',
                'themed': 'themed day' if date in themed else '',
                'slot': slot,
                'league': q['league'],
                'question_id': qid,
                'answer': q['targetPlayer'],
                'x_stat': q['xLabel'], 'x_value': q['targetX'],
                'y_stat': q['yLabel'], 'y_value': q['targetY'],
                'reference_players': ' | '.join(
                    f"{r['name']} ({r['x']}, {r['y']})" for r in q['referencePlayers']),
                'source': q['source'],
            })
    return out


# Read from the Worker's own selection module rather than restating it, so this file
# cannot drift into numbering the puzzles differently from the game.
def _bag_epoch():
    src = open(os.path.join(HERE, '..', 'worker', 'src', 'selection.js'), encoding='utf-8').read()
    import re
    m = re.search(r"BAG_EPOCH\s*=\s*'(\d{4}-\d{2}-\d{2})'", src)
    if not m:
        sys.exit('could not read BAG_EPOCH out of worker/src/selection.js')
    return m.group(1)


BAG_EPOCH = _bag_epoch()

if __name__ == '__main__':
    data = rows()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(data)
    days = len({r['date'] for r in data})
    print(f'{os.path.relpath(OUT, os.path.join(HERE, ".."))} — {len(data)} rows, {days} days')
    print(f'  {data[0]["date"]} (#{data[0]["puzzle"]}) through '
          f'{data[-1]["date"]} (#{data[-1]["puzzle"]})')

    if '--xlsx' in sys.argv:
        try:
            from openpyxl import Workbook
        except ImportError:
            sys.exit('  --xlsx needs openpyxl (pip install openpyxl); the CSV is written')
        wb = Workbook(); ws = wb.active; ws.title = 'schedule'
        ws.append(COLUMNS)
        for r in data:
            ws.append([r[c] for c in COLUMNS])
        ws.freeze_panes = 'A2'
        path = OUT.replace('.csv', '.xlsx')
        wb.save(path)
        print(f'  {os.path.relpath(path, os.path.join(HERE, ".."))}')

    print('\n  Contains every answer for the whole calendar. Keep it off anything public.')
