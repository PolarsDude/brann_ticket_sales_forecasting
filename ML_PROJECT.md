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
