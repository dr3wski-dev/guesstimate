# Content Backlog — Comp Archetypes
Unresearched. Every entry needs real, sourced numbers before it goes in questions.json
— same rule as everything else in this project. This doc exists so research sessions
have a concrete target instead of "find some more stats."

## The next batch, and the number that decides its size

The target is a **three-day league rotation**:

| | NBA | NFL | MLB |
|---|---|---|---|
| day 1 | 2 | 2 | 1 |
| day 2 | 1 | 2 | 2 |
| day 3 | 2 | 1 | 2 |
| **per cycle** | **5** | **5** | **5** |

It sums to dead even, which is what makes it worth doing — every league gets a third
of the questions without any single day feeling like a themed day.

It also means **the rotation is only as long as the smallest league × 3**, and that
changes the priority order. Against today's pool:

| | questions | days of rotation |
|---|---|---|
| NBA | 84 | 50.4 |
| NFL | 72 | 43.2 |
| MLB | 48 | **28.8** |

Turning the rotation on today would *shorten* the calendar from 41 days to 29, because
MLB runs dry first and 36 NBA questions never get used. So content comes first and the
rotation second — not the other way round.

**What each target costs, in new questions:**

| for | per league | NBA | NFL | MLB |
|---|---|---|---|---|
| 41 days (matches today) | 69 | — | — | **+21** |
| 60 days | 100 | +16 | +28 | **+52** |
| 90 days | 150 | +66 | +78 | **+102** |

MLB is the bottleneck at every size, which is why pitching is the next archetype work
rather than a nice-to-have: the batting-only dataset has been squeezed about as far as
recognisable names allow.

## Why archetypes, not just stat pairs
A stat pair is just two axes. A **comp archetype** is a pairing chosen because the
contrast means something to someone who actually follows the sport — that's the
difference between a data exercise and a question a real fan enjoys. Chase archetypes,
not just any two numbers that happen to both exist.

## NBA

**Efficiency vs. volume** — true shooting % vs. shot attempts per game. Separates
high-volume/high-efficiency legends from high-volume compilers from low-volume,
absurd-efficiency role players. Three genuinely different clusters, not a line.

**The stat-stuffer comp** — PPG vs. (RPG + APG combined). Shows *shape* of production,
not just quality. Westbrook, Jokic, and Magic should separate visibly from a
one-dimensional scorer at the same PPG level.

**Defensive identity** — steals/game vs. blocks/game. Strong candidate for the next
research pass. Rim-protecting bigs (Gobert, Mutombo-type) cluster one way, ball-hawking
guards (Iverson, CP3-type) cluster the other way, and rare two-way defenders (Hakeem,
Garnett, Duncan) should sit alone in a corner almost nobody else occupies. Verify that
last claim with real numbers before assuming it — that's the whole point of the comp.

**Size vs. skill** — height vs. 3P% (or height vs. APG). Shows how thoroughly small-ball
guards and skilled big men have scrambled the old assumption that size determines role.

**Peak vs. identity** — a player's single best season vs. their own career average, same
stat. Wilt's 50.4 PPG season (1961-62) against his own 30.1 career average is a wild
data point once it's plotted against normal-person career averages — shows how much of
an outlier a signature year really was, even for an all-time great. Note: this is a
player plotted against *themselves*, not against other players — different framing than
every question built so far, worth confirming the mechanic still reads clearly with a
single-player two-point comp before building more like it.

**Draft-slot revenge** — career stats of a famous late/undrafted pick (Draymond Green,
Rodman himself) against early lottery picks at the same stat. Built-in underdog
narrative, not just a data contrast.

## NFL

**Gunslinger vs. game manager** — INT rate vs. TD rate (season or career, passers).

**Workhorse vs. efficient back** — carries/game vs. yards/carry. Contrasts backs who
win through volume against backs who win through pure efficiency on fewer touches.

**Possession vs. big-play receiver** — receptions/game vs. yards/reception. Slot/
possession receivers vs. deep threats — a real, visible archetype split in real data.

### Receivers — next up, and the data is already downloaded
The shipped NFL pool leans on running backs, because rushing archetypes were the first
ones written. Every column these need is already in the nflverse `player_stats` cache,
so this is generation work, not research:

- **Target share vs. yards per target** — the volume-vs-efficiency split, receiver
  edition. A WR1 soaking up a third of the targets against a deep threat doing more
  with a quarter of them.
- **Air yards vs. yards after catch** — separates the receiver whose yards arrive in
  the air from the one who creates them on the ground. `receiving_air_yards` and
  `receiving_yards_after_catch` are both in the cache and neither is used yet.
- **Receptions vs. first downs** — catches that move the chains against catches that
  do not. `receiving_first_downs` is in the cache, unused.

### Defensive players — wanted, but check the data first
This is the one item on this page that is **not** a turn of the existing crank. The
nflverse `player_stats` release the pipeline downloads is offensive stats: passing,
rushing, receiving. Tackles, sacks, interceptions-by-defenders and pass breakups are
not in it. nflverse publishes defensive data separately, so step one is confirming
which release carries it, what it covers, and how far back — before any archetype gets
designed against numbers nobody has verified exist.

Archetypes worth having once the data is confirmed:
- **Sacks vs. tackles** — the edge rusher against the every-down linebacker.
- **Interceptions vs. pass breakups** — ball-hawking corners against the ones nobody
  throws at, where the interesting answer is the corner with few of both because
  quarterbacks avoided him entirely.

## MLB

**Slugger vs. contact hitter** — batting average vs. home runs. The classic power/
contact trade-off, though check whether modern hitters have collapsed this distinction
before assuming the old cluster shape still holds.

### Pitching — the bottleneck, so this is next
MLB is 48 against NBA's 84, and it is the league that caps the rotation. The ceiling is
not the archetypes, it is the dataset: `Batting.csv` only describes hitters, and the
recognisable-name shortlist has been squeezed about as far as it goes.

`Pitching.csv` is part of the same Lahman / Chadwick databank the pipeline already
downloads and pins — it is simply not in `MLB_FILES` yet. Adding it is a one-line
change to the fetch list plus a loader, and it roughly doubles the eligible MLB
population, because pitchers are currently excluded from the pool entirely.

Archetypes it opens, all pairing something unusual against something instantly
readable:

- **Power vs. control** — K/9 vs. BB/9. The classic, and it should separate cleanly.
- **Wins vs. ERA** — the one every baseball argument is actually about. A pitcher with
  a great ERA and a mediocre win total is the whole case against the win as a stat, and
  it plots in one chart.
- **Complete games vs. strikeouts** — an era question disguised as a player question.
  A 1970s workhorse and a modern strikeout artist occupy opposite corners.
- **Saves vs. ERA** — closers, where the counting stat and the quality stat diverge
  hard.
- **Innings pitched vs. career WAR-ish volume stats** — the compiler against the peak
  arm.

Note the same staleness rule applies as everywhere else: career questions only for
pitchers whose final season is at least two years before the data ends.

## Process for turning an archetype into a real question
1. Pick the archetype and the two stats.
2. Research 3-4 reference players who actually span the archetype's range — not just
   any players with the stats, players whose numbers *tell the contrast's story*.
3. Verify every number against a named source (Basketball-Reference, StatMuse,
   Pro-Football-Reference, Stathead — see 0_TO_1_ACTION_PLAN.md section 1 for the
   curation-tool recommendation).
4. Pick a target player whose position in the 2D space is genuinely interesting relative
   to the references — ideally counterintuitive in some way, the way Jonathan Taylor's
   2021 season (lowest YPG, highest TDs of the set) was.
5. Write the reveal-screen fact — this is the craft, not an afterthought. It should
   explain *why* the position is interesting, not just restate the numbers.
6. Add to questions.json following the existing schema exactly.
