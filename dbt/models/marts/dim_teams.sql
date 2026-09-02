{{ config(materialized='table') }}

-- Canonical team names available in each Eliteserien season.
with teams as (
    select
        season,
        home_team as team_name
    from {{ ref('fct_matches') }}

    union

    select
        season,
        away_team as team_name
    from {{ ref('fct_matches') }}
)

select
    season,
    team_name
from teams
order by season, team_name