# Authoring content

This folder is the **authoring surface**. `data/questions.json` is the build artifact —
edit here, import, verify, then build.

```bash
# 1. pull the current pool into a spreadsheet
python3 pipeline/import_questions.py --export content/questions.xlsx   # or .csv

# 2. edit it (Excel, Numbers, or Google Sheets -> export CSV)

# 3. import — validates shape and REFUSES to write if anything is wrong
python3 pipeline/import_questions.py --import content/questions.xlsx

# 4. verify — re-derives every number from the source datasets. Schema validity is
#    not truth; this is the gate that catches a wrong stat.
python3 pipeline/verify_questions.py

# 5. fairness — does each question actually reward knowing the answer?
node pipeline/audit_fairness.mjs            # --suggest to see repaired axes
                                            # --apply  to write them

# 6. build (runs the fairness audit again and refuses to build if it fails)
python3 pipeline/build_site.py --url https://your-domain.com
```

`--dry-run` on step 3 validates without writing.

## Why there's no database

Everything above is build-time. The player's browser never talks to a server, so a
database would add cost, latency, an attack surface, and a second place for content to
live — while solving none of these problems. Keeping content in git means every change
is reviewable in a pull request and revertible, which matters for a game whose whole
credibility rests on the numbers being checkable.

The two gates do different jobs and you need both:

- **`import_questions.py`** checks the *shape* — required fields, types, unique ids,
  domains that actually contain their points, no player appearing twice on one chart.
  It cannot tell you whether a stat is true.
- **`verify_questions.py`** checks the *numbers*, by re-deriving every one of them from
  the source datasets on a separate code path from the generator. This is the gate that
  matters. A bulk import is the fastest way to ship a wrong number, and this is what
  stops it.
- **`audit_fairness.mjs`** checks whether the question is *worth asking*. True and
  well-formed is not the same as playable: score is distance normalised by the plotted
  axis, so a domain drawn tightly around the four points makes the whole chart the
  answer's neighbourhood and a blind middle click scores near-perfect. Five shipped
  questions had drifted that way and one of them paid better for guessing than for
  knowing. Neither gate above can see this — the stats are all correct.

## What makes a good question

The audit measures two things, and they are worth understanding before writing content
rather than after failing on it:

- **centre** — what a player scores clicking the middle of the chart knowing nothing.
  This is the floor you are giving away. Gate: ≤ 35.
- **lift** — how much an informed guess beats that. This is the question's entire
  reason to exist. Gate: ≥ 30.

The single strongest predictor of good lift is that **the target is an outlier
relative to its three reference players.** A question where the answer sits comfortably
between the anchors is one the anchors have already answered. Reach for players who
break the pattern the anchors establish — the 7-footer who shot 38% from three, the
6th man with starter scoring on bench minutes — and the fairness numbers take care of
themselves.

Stats with a narrow real-world spread (true shooting %, yards per reception, career
BB/9) make weak axes for the same reason: if every player in the league falls within a
few units, every guess is close once normalised, and the axis carries no signal. They
work as the *second* stat against a wide-range first one, not as both.

## Growing the pool

The expensive step is writing fact copy against real sources, so don't spend it on
candidates that will fail the gate anyway. Screen first:

```bash
python3 pipeline/build_questions.py --league nba --top 60 --json cand-nba.json
python3 pipeline/build_questions.py --league nfl --top 60 --json cand-nfl.json
node pipeline/screen_candidates.mjs cand-*.json -o passing.json
```

`screen_candidates.mjs` drops candidates that don't reward knowing the answer and
ranks the survivors by lift, so the list is already in the order worth working
through. What comes out is **not questions yet** — each still needs fact copy naming
its source, and still has to clear `verify_questions.py`. Neither gate is bypassed by
having been screened.

## Scheduling specific days

Optional. Pin questions to dates; every unpinned date keeps using the deterministic
shuffled bag.

```bash
cp content/schedule.example.csv content/schedule.csv   # edit it: date,question_id
python3 pipeline/import_questions.py --schedule content/schedule.csv
```

Five rows per date (a day serves five questions). The importer rejects unknown ids,
duplicate pins, and days that don't have exactly five.

**A scheduled question is removed from the shuffled bag entirely** — otherwise the bag
could serve one of a themed day's questions the week before and spoil it. The exclusion
is date-independent on purpose, so replaying an old challenge link still reproduces
that day's puzzle exactly.

`schedule.example.csv` is an example only. It isn't compiled unless you copy it to
`schedule.csv` and run the command above, so nothing is scheduled by default.

## Columns

One row per question. `ref1..ref5` — leave unused reference slots blank; two to five
are allowed, three is the house standard.

| column | notes |
|---|---|
| `id` | stable, unique, kebab-case. Never reuse an id for different content |
| `league` | `NBA`, `NFL`, or `MLB` |
| `x_label` / `x_unit` | axis name and short unit (`PPG`, `HR`, `TS%`) |
| `x_step` | guess snapping: `1` whole numbers, `0.1` per-game rates, `0.001` batting average. Blank means `0.1` |
| `x_min` / `x_max` | plotted range. **Must not be derived from the answer** — that leaks it, and it was a real shipped bug |
| `target_player` | full name; add a season for season questions (`Derrick Henry, 2020`, `Baron Davis, 2003-04`) |
| `fact` | the reveal payload, and the actual product. Explain *why* it's counterintuitive rather than restating the numbers |
| `source` | named source for every number in the row |

The same applies on the `y_` columns.
