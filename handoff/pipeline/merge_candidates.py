#!/usr/bin/env python3
"""
Append screened candidates to data/questions.json.

WHY THIS EXISTS AS A TOOL
The documented authoring path is export to a spreadsheet, edit, import back. That is
the right shape for editing a question and the wrong shape for adding two hundred:
it means pasting generated rows into a 600-row sheet and re-importing the whole
thing, where a single mis-aligned column rewrites existing content. Appending is a
different operation from editing and deserves its own door — one that cannot touch a
question that is already in the pool.

WHAT IT REFUSES
  - an id that already exists (never reuse an id: a question's history is keyed on it)
  - a field the schema does not know about, or a missing required field
  - anything that fails the same shape validation as an import

WHAT IT DOES NOT DO
It does not check whether the numbers are true. Run verify_questions.py after, every
time; it is the only gate that reads the source datasets.

    python3 pipeline/build_questions.py --league nbac --top 400 --json cand.json
    node pipeline/screen_candidates.mjs cand.json -o passing.json
    python3 pipeline/merge_candidates.py passing.json
    python3 pipeline/verify_questions.py
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from import_questions import validate, roundtrip_errors   # noqa: E402

DATA = os.path.join(HERE, '..', 'data')
QJSON = os.path.join(DATA, 'questions.json')

# The order every record is written in, so a 200-question append is a clean block at
# the end of the file rather than a diff that also reshuffles the keys of everything
# already there.
ORDER = ['id', 'league', 'game', 'xLabel', 'xUnit', 'yLabel', 'yUnit', 'xStep',
         'yStep', 'xDomain', 'yDomain', 'targetPlayer', 'targetX', 'targetY',
         'referencePlayers', 'fact', 'source', 'span']
REF_ORDER = ['name', 'x', 'y', 'span']
# Produced by the generator for ranking and screening, and meaningless afterwards.
# `_fair` is the fairness audit's own reading, attached by screen_candidates.mjs.
DROP = {'score', 'target_who', '_arch', '_fair'}


def tidy(q):
    q = {k: v for k, v in q.items() if k not in DROP}
    unknown = [k for k in q if k not in ORDER]
    if unknown:
        raise SystemExit(f"{q.get('id')}: unknown field(s) {unknown} — add them to the "
                         f"schema and to import_questions.py's columns first, or the "
                         f"next spreadsheet round trip will delete them")
    out = {k: q[k] for k in ORDER if k in q}
    out['referencePlayers'] = [{k: r[k] for k in REF_ORDER if k in r}
                               for r in q['referencePlayers']]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+', help='screened candidate .json files')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    pool = json.load(open(QJSON))
    have = {q['id'] for q in pool}
    adding, skipped = [], []
    for path in a.files:
        for c in json.load(open(path)):
            if c['id'] in have:
                skipped.append(c['id'])
                continue
            have.add(c['id'])
            adding.append(tidy(c))

    merged = pool + adding
    errors = validate(merged) + roundtrip_errors(merged)
    print(f'{len(pool)} in the pool, {len(adding)} to add, {len(skipped)} already present')
    for e in errors[:40]:
        print('  -', e)
    if errors:
        print(f'\nREFUSED — nothing written ({len(errors)} problem(s)).')
        return 1
    if a.dry_run:
        print('dry run — nothing written')
        return 0
    with open(QJSON, 'w', encoding='utf-8') as fh:
        json.dump(merged, fh, indent=2, ensure_ascii=False)
        fh.write('\n')
    print(f'wrote {len(merged)} questions to data/questions.json')
    print('NOW RUN:  python3 pipeline/verify_questions.py   '
          '(nothing above checked whether a single number is true)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
