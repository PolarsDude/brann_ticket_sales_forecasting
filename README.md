# Brann Football Analytics

A data pipeline for collecting Eliteserien match results, goal contributions, and lineups, storing them in DuckDB, and transforming them with dbt for football analysis.

## Architecture

```
src/
├── utils.py           # Web scraping functions
├── config.py          # Configuration and paths
└── ingest_data.py     # Data ingestion pipeline → DuckDB

dbt/                   # Data transformation layer
├── models/
│   ├── staging/       # Raw data cleaning
│   └── marts/         # Analytics-ready tables
└── profiles.yml       # DuckDB connection

data/
└── brann.duckdb       # DuckDB database
```

## Quick Start

### 1. Install Dependencies
```bash
uv sync
```

### 2. Create the Data Directory and Database
Run these commands from the repository root. Create both the directory and the DuckDB file before starting ingestion:
```bash
uv run python -c "from pathlib import Path; Path('data').mkdir(exist_ok=True)"
uv run python -c "import duckdb; duckdb.connect('data/brann.duckdb').close()"
```

### 3. Run Data Ingestion
Run the ingestion script yourself from the repository root:
```bash
uv run python src/ingest_data.py
```

The script fetches and loads match results and goal-scorer rows for the configured current Eliteserien season. It requires the `data/brann.duckdb` file created in the previous step. Other datasets, including FotMob goal contributions and lineups, are ingested from their corresponding cells in `ingest_data.ipynb`.

### 4. Run dbt Transformations
```bash
cd dbt
uv run dbt run
```

This builds the available analytics tables:
- `dim_teams` - Canonical team names by season
- `fct_goal_contributions` - FotMob goal events, including the `is_own_goal` flag
- `fct_league_standings` - Cumulative league table by matchday
- `fct_lineups` - FotMob player lineups and substitution details
- `fct_matches` - Match results, parsed scores, and winner

## Data Pipeline Flow

```
Web Sources (FotMob, Transfermarkt)
         ↓
   src/utils.py scraping
         ↓
 ingest_data.py and ingest_data.ipynb (DuckDB raw tables)
         ↓
   dbt models
         ↓
  dbt analytics marts
         ↓
  Agent queries analytics
```

## Notebooks

- `notebook.ipynb` - Exploration and analysis notebooks