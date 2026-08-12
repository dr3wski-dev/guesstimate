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

# 5. build
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
