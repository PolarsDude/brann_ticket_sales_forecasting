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

Each feature comes with a confidence level. Features are aggregated per match up to the prediction minute (for example, counts per team).

**Handling of missing and uncertain values** (the model is tree-based, so nulls are supported):

- `"unknown"` is converted to `null` (information is missing).
- `"none"` is kept as its own value (the event did not happen).
- Values with confidence below a threshold (for example 0.75) are set to `null`. The threshold is a hyperparameter to tune on validation data.

#### Aggregation design

One row per `(match_id, T)` where `T` is the cutoff minute (for example every 5 minutes: 5, 10, ..., 90). All features use only comments with `event_time <= T` to avoid leakage. A single model is trained with `T` as a feature. "Team" means home (`H`) or away (`B`); every feature is built for both teams and as a difference `H - B`.

Helper columns per comment (before aggregation):

- `is_gp = (mr_has_gameplay_information == "yes")`
- `is_home_att = (mr_attacking_team == "home")`, `is_away_att = (mr_attacking_team == "away")`
- `chance_w = mr_chance_quality` mapped to `big=3, normal=2, low=1, none/null=0`

Overview of aggregations:

**1. Activity and coverage**

| Feature | How |
|---|---|
| `n_comments` | count of comments <= T |
| `n_gp` | `sum(is_gp)` |
| `gp_share` | `n_gp / n_comments` |

**2. Attacks and chances (per team)**

| Feature | How |
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

| Feature | How |
|---|---|
| `shots` | count where `mr_shot_outcome` is not null and not `"none"` |
| `shots_on_target` | `saved + goal + woodwork` |
| `saved`, `off_target`, `blocked`, `woodwork` | count per outcome |
| `goals_text` | `sum(mr_shot_outcome == "goal")` |
| `shot_accuracy` | `shots_on_target / shots` (null if `shots == 0`) |

Shots and outcomes come from text and are less reliable than structured match data. Use `goals_text` only as a sanity check against the real score.

**4. Match picture (per team)**

| Feature | How |
|---|---|
| `pressure` | `sum(mr_attacking_pressure in (team, "both"))` |
| `dominance` | `sum(mr_territorial_dominance == team)` |
| `balanced` | `sum(mr_territorial_dominance == "balanced")` (not team-specific) |
| `counters` | `sum(mr_counter_attack == team)` |
| `low_block` | `sum(mr_defensive_low_block == team)` |
| `def_errors` | `sum(mr_defensive_error == team)` (also `opp_def_errors` for the opponent's errors) |

**5. Time windows (momentum)**

Repeat the most important features (`chance_score`, `threat_sum`, `pressure`, `shots_on_target`) for the window `(T - W, T]` with `W = 10` or `15`. This captures who is on top right now and not only the total since kick-off.

**6. Differences and ratios**

- `diff_X = home_X - away_X` for all features above.
- `share_X = home_X / (home_X + away_X)` for event counts; null if the denominator is 0.

**7. Not from `mr_*`, but required**

- `score_diff` at `T` (from structured data, not from text)
- `minutes_left = 90 - T` (and optionally added time)
- `T` itself
- Pre-match features (see static features below)

**Recommended order**

1. Build sections 2 and 4 first (chances, threat, pressure).
2. Add differences, `score_diff` and `minutes_left`.
3. Add time windows (section 5).
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
| `home_attacks_last10`, `away_attacks_last10` | same counts in the window `(T - 10, T]` |
| `attacks_diff_last10` | difference in the window |
| `mins_since_home_attack`, `mins_since_away_attack` | `T - last event_time` for the team, null if none yet |
| `n_comments_cum` | all comments <= T (coverage, used for normalization) |
| `attack_density` | `(home + away) / n_comments_cum` |

Start with seven: `home_attacks_cum`, `away_attacks_cum`, `attacks_diff_cum`, `attacks_diff_last10`, `home_attacks_last10`, `away_attacks_last10`, `n_comments_cum`. Add `share`, `mins_since_*` and `attack_density` only after a baseline exists.

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
