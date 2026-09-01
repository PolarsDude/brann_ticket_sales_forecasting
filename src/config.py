"""Configuration for the Brann data pipeline."""
from pathlib import Path

# Database configuration
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "brann.duckdb"

# Ensure data directory exists
DATA_DIR.mkdir(exist_ok=True)

# Scraping configuration
ELITESERIEN_SEASON_ID = 2025
ELITESERIEN_YEAR = 2026
