# Match Outcome Classification

## Goal

Build a machine learning model that classifies the outcome of a football match as one of three classes:

- **Home win**
- **Away win**
- **Draw**

The prediction is made **in-play**: given everything that has happened in the match so far (up to a given minute), the model predicts the final result.

## Data basis

The primary data source is **match reports** (minute-by-minute commentary and events from FotMob), stored in DuckDB (`data/brann.duckdb`, `raw_fotmob_events_*` tables).

## Features

### 1. Features extracted from match reports (Jev)

[Jev](https://pypi.org/project/polar-llama/) (LLM-based classification) is used to extract structured features from the free-text match reports, describing *how* the teams are playing and not just the score. Examples:

- Chance quality, shot outcome, shot distance
- One-on-one situations, chance creation type
- Attacking pressure, territorial dominance
- Counter attacks, low defensive block, defensive errors
- Attacking threat (score)

Each feature comes with a confidence level. Features are aggregated per match up to the prediction minute, either cumulatively from kick-off or over recent time windows.

**Handling of missing and uncertain values** (the model is tree-based, so nulls are supported):

- `"unknown"` is converted to `null` (information is missing).
- `"none"` is kept as its own value (the event did not happen).
- Values with confidence below a threshold (for example 0.75) are set to `null`. The threshold is a hyperparameter to tune on validation data.

#### Aggregation design

One row per `(match_id, T)` where `T` is the cutoff minute (for example every 5 minutes: 5, 10, ..., 90). All features use only comments with `event_time <= T` to avoid leakage. A single model is trained with `T` as a feature. "Team" means home (`H`) or away (`B`); team-specific features are built for both teams, with home-away differences where applicable.

Helper columns per comment (before aggregation):

- `is_gp = (mr_has_gameplay_information == "yes")`
- `is_home_att = (mr_attacking_team == "home")`, `is_away_att = (mr_attacking_team == "away")`
- `chance_w = mr_chance_quality` mapped to `big=3, normal=2, low=1, none/null=0`

Overview of aggregations:

**Cumulative vs. rolling:** Sections 1-4 below are cumulative snapshots from kick-off through `T`: at each cutoff, aggregate all eligible comments satisfying `event_time <= T`. Counts and sums therefore represent running totals (equivalent to a `cum_sum` over events ordered by match time); means, maxima, shares and ratios are recalculated from that same cumulative set. These are **not** rolling-window values. Only features in section 5 use the trailing rolling windows `(T - W, T]`. The names in sections 1-4 omit a `_cum` suffix for readability, but their cumulative behavior is explicit here. In the specialized `mr_attacking_team` feature set below, cumulative features are marked with `_cum`.

**1. Activity and coverage**

| Cumulative feature | How |
|---|---|
| `n_comments` | count of comments <= T |
| `n_gp` | `sum(is_gp)` |
| `gp_share` | `n_gp / n_comments` |

**2. Attacks and chances (per team)**

| Cumulative feature | How |
|---|---|
| `attacks` | `sum(mr_attacking_team == team)` |
| `chance_score` | `sum(chance_w)` where the team attacks |
| `big_chances` | `sum(mr_chance_quality == "big")` for the team |
| `threat_sum` / `threat_mean` / `threat_max` | sum, mean and max of `mr_attacking_threat` for the team |
| `one_on_ones` | `sum(mr_one_on_one == "yes")` for the team |
| `box_shots` | `sum(mr_shot_distance in ("close", "inside_box"))` for the team |
| `long_shots` | `sum(mr_shot_distance == "outside_box")` for the team |
| `set_piece_chances` | `sum(mr_chance_creation_type in ("corner", "free_kick", "penalty"))` |
| `open_play_chances` | `sum(mr_chance_creation_type == "open_play")` |

**3. Shot outcomes (per team)**

`mr_shot_outcome` is the text-derived outcome and does not include `"goal"` or
`"disallowed"`. Create `mr_shot_outcome_final` by overriding the text outcome
with the structured goal event:

```text
mr_shot_outcome_final =
    "goal" when event_type == "G"
    mr_shot_outcome otherwise
```

`mr_shot_outcome_final` therefore contains `"goal"` together with the
text-derived outcomes `"saved"`, `"off_target"`, `"blocked"`, `"woodwork"`,
`"none"` and `"unknown"`. The structured event type is authoritative for
goals; the LLM must not infer goals from prose.

| Cumulative feature | How |
|---|---|
| `shots` | count where `mr_shot_outcome_final` is not null and not `"none"` |
| `shots_on_target` | `saved + goal + woodwork` from `mr_shot_outcome_final` |
| `saved`, `off_target`, `blocked`, `goal`, `woodwork` | count per final outcome |
| `goals` | `sum(mr_shot_outcome_final == "goal")` |
| `shot_accuracy` | `shots_on_target / shots` (null if `shots == 0`) |

Shots and non-goal outcomes from text are less reliable than structured match
data. Use the final outcome for features and use the raw text-derived outcome
only for diagnostics.

**4. Match picture (per team)**

| Cumulative feature | How |
|---|---|
| `pressure` | `sum(mr_attacking_pressure in (team, "both"))` |
| `dominance` | `sum(mr_territorial_dominance == team)` |
| `balanced` | `sum(mr_territorial_dominance == "balanced")` (not team-specific) |
| `counters` | `sum(mr_counter_attack == team)` |
| `low_block` | `sum(mr_defensive_low_block == team)` |
| `def_errors` | `sum(mr_defensive_error == team)` (also `opp_def_errors` for the opponent's errors) |

**5. Rolling time windows (momentum)**

For each prediction cutoff `T`, calculate the selected features separately from the comments in each trailing window `(T - W, T]`, using `W = 5`, `10` and `15` minutes. The lower boundary is exclusive and the cutoff is inclusive: an event exactly at `T - W` is excluded, while an event at `T` is included. For example, `chance_score_home_last10` at minute 30 sums the home team's chance weights for comments with `20 < event_time <= 30`.

| Rolling feature | How |
|---|---|
| `chance_score_{team}_last{W}` | Sum `chance_w` where `mr_attacking_team` is the team and `T - W < event_time <= T` |
| `threat_sum_{team}_last{W}` | Sum `mr_attacking_threat` where `mr_attacking_team` is the team in the window |
| `pressure_{team}_last{W}` | Count comments where `mr_attacking_pressure` is the team or `"both"` in the window |
| `shots_on_target_{team}_last{W}` | Count `"saved"`, `"goal"` and `"woodwork"` in `mr_shot_outcome_final` where `mr_attacking_team` is the team in the window |
| `attacks_{team}_last{W}` | Count comments where `mr_attacking_team` is the team in the window |
| `attacks_diff_last{W}` | `home_attacks_last{W} - away_attacks_last{W}` |

Here `{team}` is `home` or `away`, and `{W}` is `5`, `10` or `15`. Apply the same window and cutoff to every feature; do not include comments after `T`. Rolling features complement, rather than replace, cumulative features: cumulative values describe the whole match so far, while rolling values describe recent momentum.

**6. Differences and ratios**

- `diff_X = home_X - away_X` for team-specific features, including rolling features (`diff_X_last{W}` or the named `attacks_diff_last{W}`).
- `share_X = home_X / (home_X + away_X)` for event counts; null if the denominator is 0.

**7. Not from `mr_*`, but required**

- `score_diff` at `T` (from structured data, not from text)
- `minutes_left = 90 - T` (and optionally added time)
- `T` itself
- Pre-match features (see static features below)

**Recommended order**

1. Build sections 2 and 4 first (chances, threat, pressure).
2. Add differences, `score_diff` and `minutes_left`.
3. Add rolling 5-, 10- and 15-minute windows (section 5).
4. Add the rest (section 3) and check what matters with feature importance.

**Pitfalls**

- **Null handling:** counts and sums give 0 when nothing matches. Use `fill_null(0)` only after aggregation. Means and maxima are null when a team has no values, which is often more correct than 0.
- **Leakage:** `event_time` is the boundary. Do not use comments after `T` and do not use the final result in any feature.
- **Added time:** define consistently how `event_time` and `added_time` combine (for example `event_time + added_time` for ordering).
- **Correlation:** many features measure the same thing (`chance_score`, `threat_sum`, `big_chances`). Gradient boosting tolerates this, but start with a small set.
- **Little data early in the match:** consider starting the cutoffs at 10 or 15 minutes.

#### Feature set: `mr_attacking_team`

Values are `home`, `away` or null (no concrete offensive action, or team cannot be identified).

| Feature | Definition |
|---|---|
| `home_attacks_cum` | count of comments <= T with `mr_attacking_team == "home"` |
| `away_attacks_cum` | count of comments <= T with `mr_attacking_team == "away"` |
| `attacks_diff_cum` | `home_attacks_cum - away_attacks_cum` |
| `attacks_share_home_cum` | `home / (home + away)`, null if both are 0 |
| `home_attacks_last5`, `away_attacks_last5` | same counts in the window `(T - 5, T]` |
| `attacks_diff_last5` | `home_attacks_last5 - away_attacks_last5` |
| `home_attacks_last10`, `away_attacks_last10` | same counts in the window `(T - 10, T]` |
| `attacks_diff_last10` | `home_attacks_last10 - away_attacks_last10` |
| `home_attacks_last15`, `away_attacks_last15` | same counts in the window `(T - 15, T]` |
| `attacks_diff_last15` | `home_attacks_last15 - away_attacks_last15` |
| `mins_since_home_attack`, `mins_since_away_attack` | `T - last event_time` for the team, null if none yet |
| `n_comments_cum` | all comments <= T (coverage, used for normalization) |
| `attack_density` | `(home + away) / n_comments_cum` |

Start with the cumulative attack counts and their difference, plus home/away attack counts and attack differences for each of the 5-, 10- and 15-minute windows, and `n_comments_cum`. Add `share`, `mins_since_*` and `attack_density` only after a baseline exists.

Notes:

- Null means both "no attack" and "unclear team". To separate them, count `has_gameplay == "yes"` with null `mr_attacking_team` as `unattributed_attacks`.
- Counts reflect relative attention from the journalist, not actual attack counts.

Example (Polars) for `home_attacks_cum` and `away_attacks_cum`:

```python
cutoffs = pl.DataFrame({"T": list(range(5, 95, 5))})
grid = df.select("match_id").unique().join(cutoffs, how="cross")

attacks_cum = (
    grid.join(df.select("match_id", "event_time", "mr_attacking_team"), on="match_id")
    .filter(pl.col("event_time") <= pl.col("T"))
    .group_by("match_id", "T")
    .agg(
        (pl.col("mr_attacking_team") == "home").sum().alias("home_attacks_cum"),
        (pl.col("mr_attacking_team") == "away").sum().alias("away_attacks_cum"),
    )
)

attacks_cum = (
    grid.join(attacks_cum, on=["match_id", "T"], how="left")
    .with_columns(pl.col("home_attacks_cum", "away_attacks_cum").fill_null(0))
)
```

#### Validation

- Split by match, not by row: all cutoff rows from the same match must end up in the same fold.
- Prefer a time-based split (season).
- Compare against a baseline with only pre-match features and score.
- Check calibration per `T`; the model should become more confident later in the match.

### 2. Static features

Pre-match context that does not change during the match, for example:

- Form: results over the last 5-10 matches
- League position / standings
- Other team strength indicators

## Model

A tree-based model (for example gradient boosting), chosen because it handles `null` values natively.

## Evaluation

- Time-based train/validation/test split (avoid leaking future matches into training).
- Metrics for three-class classification, such as log loss and accuracy.
- Evaluate performance as a function of match minute.
