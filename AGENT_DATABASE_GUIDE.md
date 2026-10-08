# Brann Football Analytics Agent - Database Guide

This guide provides all necessary information for the text-to-SQL agent to query the Brann football database.

## Database Connection

- **Type:** DuckDB
- **Location:** `data/brann.duckdb`
- **Schema:** `main` (default)

## Available Tables

### 1. dim_teams
**Description:** Canonical team names available in each Eliteserien season. Use this table to resolve an incomplete team name in a question before filtering match or standings tables.

**Columns:**
- `season` (INTEGER): Calendar year of the season
- `team_name` (VARCHAR): Exact team name used in the fact tables

**Example: Resolve "Rosenborg" to its exact name**
```sql
SELECT team_name
FROM dim_teams
WHERE season = 2026
    AND team_name ILIKE '%Rosenborg%'
```

This returns `Rosenborg BK`. Use that exact value when querying `fct_matches` or `fct_league_standings`.

**Known name resolution:** `Sarpsborg` resolves to `Sarpsborg 08`, not `Sarpsborg 08 FF`.

---

### 2. fct_matches
**Description:** One row per match per round. Contains all match results with parsed goals and winner information.

**Columns:**
- `season` (INTEGER): Calendar year of the Eliteserien season. Filter on this column when a question concerns a specific season.
- `date` (DATE): The date when the match was played. Use it to filter by period, for example to count how many matches Brann won in spring, summer, or autumn.
- `matchday` (INTEGER): The round number in the season
- `home_team` (VARCHAR): Name of the home team
- `away_team` (VARCHAR): Name of the away team
- `result` (VARCHAR): Match result as string in format 'X:Y' (e.g., '2:1')
- `home_goals` (INTEGER): Number of goals scored by the home team
- `away_goals` (INTEGER): Number of goals scored by the away team
- `winner` (VARCHAR): Match winner - 'home_team', 'away_team', or 'draw'
- `snapshot_at` (TIMESTAMP): When the data was fetched from the source
- `ingested_at` (TIMESTAMP): When the data was loaded into DuckDB

**Key Features:**
- Complete match history with parsed scoring information
- Winner column simplifies queries about who won each match
- Includes the seasons currently loaded into DuckDB

---

### 3. fct_league_standings
**Description:** League standings after each matchday. One row per team per round showing cumulative statistics.

**Columns:**
- `season` (INTEGER): Calendar year of the Eliteserien season. Points and league position reset for every season.
- `matchday` (INTEGER): The round number in the season
- `team` (VARCHAR): Team name
- `total_points` (INTEGER): Cumulative points earned up to and including this matchday
- `total_goals_for` (INTEGER): Cumulative goals scored up to and including this matchday
- `total_goals_against` (INTEGER): Cumulative goals conceded up to and including this matchday
- `goal_difference` (INTEGER): Cumulative goal difference (goals_for - goals_against)
- `position` (INTEGER): Team's position in the league table after this matchday (1 = first place)

**Key Features:**
- Shows historical league table progression through the season
- Position calculated based on points, then goal difference for ties, within each season
- Useful for tracking team performance over time

---

### 4. fct_goal_contributions
**Description:** One row per goal in a completed Eliteserien match, with the credited scorer, any recorded assist, and the score after the goal. The data comes from FotMob match details. Use this table for questions about scorers, assists, and own goals.

**Columns:**
- `season` (INTEGER): Calendar year of the Eliteserien season.
- `date` (DATE): Date of the match.
- `matchday` (INTEGER): Round number in the season.
- `home_team` / `away_team` (VARCHAR): Teams in the match.
- `result` (VARCHAR): Final score in `X:Y` format.
- `scorer_name` (VARCHAR): Player credited with the goal; for an own goal, this is the player who put the ball into their own net.
- `scorer_player_id` (INTEGER): FotMob player ID, when available.
- `is_own_goal` (BOOLEAN): `true` when FotMob marks the event as an own goal; `false` for a regular goal.
- `assist_name` (VARCHAR): Player credited with the assist, when available.
- `assist_player_id` (INTEGER): FotMob player ID of the assister, when available.
- `scorer_team` (VARCHAR): Team credited with the goal. For an own goal, this can differ from the player's team.
- `home_or_away` (VARCHAR): Whether the credited goal belongs to the home or away team.
- `score` (VARCHAR): Score immediately after the goal, in `X:Y` format.
- `report_url` (VARCHAR): FotMob match URL used as the source.
- `snapshot_at` / `ingested_at` (TIMESTAMP): When source data was fetched / loaded into DuckDB.

**Key Features:**
- Each goal is a separate row. Do not deduplicate by scorer or match; a player can score both regular goals and own goals in the same match.
- On own goals, `scorer_name` identifies the player who scored into their own net, while `scorer_team` and `home_or_away` identify the team credited with the goal.
- `is_own_goal` is a boolean. Filter with `is_own_goal = true` for own goals; do not infer own goals by comparing the player and credited team.

---

### 5. fct_lineups
**Description:** One row per player listed in a FotMob match lineup, including starters and substitutes. Use this table for lineups, formations, positions, and substitution participation.

**Columns:**
- `season` (INTEGER): Calendar year of the Eliteserien season.
- `date` (DATE): Date of the match.
- `matchday` (INTEGER): Round number in the season.
- `home_team` / `away_team` (VARCHAR): Teams in the match.
- `report_url` (VARCHAR): FotMob match URL used as the source.
- `team_name` (VARCHAR): Team the player represented in the match.
- `home_or_away` (VARCHAR): Whether the player's team played at home or away.
- `formation` (VARCHAR): Team formation, when available.
- `player_name` (VARCHAR): Player's name.
- `player_id` (INTEGER): FotMob player ID, when available.
- `shirt_number` (INTEGER): Shirt number, when available.
- `player_status` (VARCHAR): `starter` or `substitute`.
- `position` (VARCHAR): FotMob's usual position category, when available.
- `position_source` (VARCHAR): Source used to determine the position.
- `formation_top` / `formation_left` (DOUBLE): Formation graphic coordinates as percentages, when available.
- `substitute_used` (BOOLEAN): Whether a listed substitute played; NULL for starters.
- `substitution_type` (VARCHAR): `in` or `out` when a substitution event is available.
- `substitution_time` (VARCHAR): Substitution time, including added time when provided.
- `substitution_partner_name` / `substitution_partner_id`: Player entering or leaving in the same substitution.
- `result` (VARCHAR): Final score in `X-Y` format from FotMob.
- `snapshot_at` / `ingested_at` (TIMESTAMP): When source data was fetched / loaded into DuckDB.

**Key Features:**
- A substitute may appear in the lineup without playing; use `substitute_used` to distinguish this where it is populated.
- Match and team filters should include `season` because team lineups recur across seasons.

---

## Sample Queries

### Get Last 5 Brann Matches
```sql
SELECT 
    season,
    date,
    matchday,
    home_team,
    away_team,
    result,
    winner
FROM fct_matches
WHERE season = (SELECT MAX(season) FROM fct_matches)
    AND (home_team = 'SK Brann' OR away_team = 'SK Brann')
ORDER BY date DESC
LIMIT 5
```

### Get Brann's Current Position (Latest Matchday)
```sql
SELECT 
    season,
    team,
    position,
    total_points,
    total_goals_for,
    total_goals_against,
    goal_difference,
    matchday
FROM fct_league_standings
WHERE team = 'SK Brann'
ORDER BY season DESC, matchday DESC
LIMIT 1
```

### Get Latest League Table
```sql
SELECT 
    season,
    position,
    team,
    total_points,
    total_goals_for,
    total_goals_against,
    goal_difference
FROM fct_league_standings
WHERE season = (SELECT MAX(season) FROM fct_league_standings)
    AND matchday = (
            SELECT MAX(matchday)
            FROM fct_league_standings
            WHERE season = (SELECT MAX(season) FROM fct_league_standings)
    )
ORDER BY position
```

### Count Brann's Wins
```sql
SELECT 
    COUNT(*) as total_wins,
    COUNT(CASE WHEN home_team = 'SK Brann' THEN 1 END) as home_wins,
    COUNT(CASE WHEN away_team = 'SK Brann' THEN 1 END) as away_wins
FROM fct_matches
WHERE season = 2026
    AND ((home_team = 'SK Brann' AND winner = 'home_team')
   OR (away_team = 'SK Brann' AND winner = 'away_team')
    )
```

### Get Matches Between Two Teams
```sql
SELECT 
    season,
    date,
    matchday,
    home_team,
    away_team,
    result,
    winner
FROM fct_matches
WHERE season = 2026
    AND ((home_team = 'SK Brann' AND away_team = 'Molde FK')
   OR (home_team = 'Molde FK' AND away_team = 'SK Brann')
    )
ORDER BY date
```

### Count Brann Wins in a Month
```sql
-- Replace 4 with the requested month number (4 = April).
SELECT
        COUNT(*) AS wins
FROM fct_matches
WHERE season = 2026
    AND EXTRACT(MONTH FROM date) = 4
    AND (
            (home_team = 'SK Brann' AND winner = 'home_team')
            OR (away_team = 'SK Brann' AND winner = 'away_team')
    )
```
---

## Important Rules for the Agent

1. **Team Name:** Always use `'SK Brann'` as the exact team name (case-sensitive)

    For every other team, always use `dim_teams` to find the exact `team_name` for the requested season before filtering matches or standings. Do not guess a team name from general knowledge. For example, resolve `Rosenborg` to `Rosenborg BK` and `Sarpsborg` to `Sarpsborg 08`.

2. **Winner Values:** Use exact values:
   - `'home_team'` - home team won
   - `'away_team'` - away team won  
   - `'draw'` - match ended in a draw

3. **Result Format:** Results are stored as strings like `'2:1'`, `'0:0'`, etc.
   - Use `home_goals` and `away_goals` columns for numeric comparisons
   - Use `result` column when displaying the score to the user

4. **Season and Matchday:** `season` is the calendar year of the Eliteserien season. Matchday 1 starts again every season, so always filter or partition by `season` when using `matchday`, league position, or cumulative standings. For current-season questions, use `season = (SELECT MAX(season) FROM fct_matches)`.

5. **Dates:** Dates are stored in DATE format. Use appropriate date filtering if needed

6. **Qualify Ambiguous Columns:** When joining tables or CTEs that share column names, always use table names or aliases to qualify those columns in both `SELECT` and `WHERE` clauses. For example, use `matches.season` instead of `season` when joining `fct_matches` with a CTE that also contains `season`.

7. **DuckDB Syntax:**
   - Use standard SQL syntax
   - `LIMIT` clause for limiting results
   - Use `DESC` for descending order, `ASC` for ascending (default)
   - Subqueries are fully supported

8. **Always Order Results:**
   - For match queries: use `ORDER BY date DESC` (most recent first)
    - For standings: use `ORDER BY season DESC, matchday DESC` or `ORDER BY position`

---

## Common Questions and Query Patterns

### Q: How many matches has Brann won/lost/drawn?
```sql
-- Wins
SELECT COUNT(*) FROM fct_matches 
WHERE ((home_team = 'SK Brann' AND winner = 'home_team') 
    OR (away_team = 'SK Brann' AND winner = 'away_team'))

-- Losses
SELECT COUNT(*) FROM fct_matches 
WHERE ((home_team = 'SK Brann' AND winner = 'away_team') 
    OR (away_team = 'SK Brann' AND winner = 'home_team'))

-- Draws
SELECT COUNT(*) FROM fct_matches 
WHERE (home_team = 'SK Brann' OR away_team = 'SK Brann')
  AND winner = 'draw'
```

### Q: What is Brann's current record?
Use `fct_league_standings` for the maximum `season`, then the maximum `matchday` within that season.

### Q: How does Brann compare to another team?
Query `fct_league_standings` for both teams in the same `season` and matchday.

### Q: Show me Brann's results this season
Query `fct_matches` for the maximum `season`, where home_team or away_team is 'SK Brann', ordered by date.

---

## Data Freshness

- **Data last ingested:** Check the `ingested_at` timestamp in the tables
- **Snapshot time:** The `snapshot_at` field indicates when data was fetched from the web
- To refresh data, run: `uv run python src/ingest_data.py`
- To refresh SofaScore xG data, run: `uv run python src/ingest_data_sofascore.py`

---

## Troubleshooting

- **No results returned:** Check that team names match exactly (e.g., 'SK Brann' with proper casing)
- **Wrong winner:** Remember `winner` is from the match perspective ('home_team' or 'away_team')
- **Standings not available:** Make sure you're querying the correct matchday
