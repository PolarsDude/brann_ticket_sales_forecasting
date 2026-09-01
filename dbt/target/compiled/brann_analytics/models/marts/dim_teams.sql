

-- Canonical team names available in each Eliteserien season.
with teams as (
    select
        extract(year from date)::integer as season_year,
        home_team as team_name
    from "brann"."main"."fct_matches"

    union

    select
        extract(year from date)::integer as season_year,
        away_team as team_name
    from "brann"."main"."fct_matches"
)

select
    season_year,
    team_name
from teams
order by season_year, team_name