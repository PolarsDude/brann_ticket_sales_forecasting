"""Configuration for the Brann data pipeline."""
from pathlib import Path

# Database configuration
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "brann.duckdb"

# Ensure data directory exists
DATA_DIR.mkdir(exist_ok=True)

# Scraping configuration
ELITESERIEN_SEASONS = [
	(season_id, season_id + 1)
	for season_id in range(2014, 2026)
]
SCRAPE_DELAY_SECONDS = 5.0
