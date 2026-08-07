# Content Backlog — Comp Archetypes
Unresearched. Every entry needs real, sourced numbers before it goes in questions.json
— same rule as everything else in this project. This doc exists so research sessions
have a concrete target instead of "find some more stats."

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

## MLB

**Slugger vs. contact hitter** — batting average vs. home runs. The classic power/
contact trade-off, though check whether modern hitters have collapsed this distinction
before assuming the old cluster shape still holds.

**Power vs. control pitcher** — K/9 vs. BB/9.

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
