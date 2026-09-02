
    

    create  table
      "brann"."main"."dim_teams__dbt_tmp"
  
    
    as (
      

-- Canonical team names available in each Eliteserien season.
with teams as (
    select
        season,
        home_team as team_name
    from "brann"."main"."fct_matches"

    union

    select
        season,
        away_team as team_name
    from "brann"."main"."fct_matches"
)

select
    season,
    team_name
from teams
order by season, team_name
    );
    
  