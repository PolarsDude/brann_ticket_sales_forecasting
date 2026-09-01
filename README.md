# Brann Ticket Sales Forecasting

An intelligent data pipeline for scraping Eliteserien match results and Brann ticket data, storing in DuckDB, and transforming with dbt for advanced analytics.

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
pip install dbt-duckdb
```

### 2. Run Data Ingestion
```bash
cd src
python ingest_data.py
```

This fetches and loads:
- Eliteserien match results
- Match details
- Available events
- Ticket section data

### 3. Run dbt Transformations
```bash
cd dbt
dbt run
```

Generates:
- `stg_eliteserien_results` - Cleaned match data with parsed scores
- `fct_league_standings` - League table with cumulative stats per matchday

## Data Pipeline Flow

```
Web Sources (Transfermarkt, Ticketco)
         ↓
   utils.py scraping
         ↓
 ingest_data.py (DuckDB raw tables)
         ↓
   dbt staging models
         ↓
  dbt analytics marts
         ↓
  Agent queries analytics
```

## Notebooks

- `notebook.ipynb` - Exploration and analysis notebooks