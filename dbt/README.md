# Brann Analytics dbt Project

This dbt project transforms raw Eliteserien and match data into analytics-ready tables for the Brann ticket sales forecasting agent.

## Project Structure

- `models/staging/` - Staging models that clean and standardize raw data
- `models/marts/` - Analytics models optimized for specific use cases
- `models/schema.yml` - Source and model definitions

## Models

### Staging
- **stg_eliteserien_results** - Parsed Eliteserien match results with individual goal counts
- **stg_match_results** - Standardized match results

### Marts
- **fct_league_standings** - League table with cumulative stats after each matchday

## Running dbt

```bash
# Run all models
dbt run

# Run and test
dbt run --select tag:daily

# Generate documentation
dbt docs generate
dbt docs serve
```

## Setting Up

1. Install dbt-duckdb:
   ```bash
   pip install dbt-duckdb
   ```

2. Configure profiles.yml with your DuckDB path

3. Run dbt:
   ```bash
   dbt run
   ```
