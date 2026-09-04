{{ config(materialized='table') }}

-- One row per recorded goal in an Eliteserien match report.
select
    season,
    date,
    matchday,
    home_team,
    away_team,
    result,
    scorer_team,
    scorer_name,
    ingested_at
from {{ source('raw', 'raw_eliteserien_goal_scorers') }}
order by season, date, matchday, scorer_team, scorer_name