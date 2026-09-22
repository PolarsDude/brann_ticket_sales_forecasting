
    

    create  table
      "brann"."main"."fct_matches__dbt_tmp"
  
    
    as (
      

-- Match results with parsed goals and winner information
-- Each row is one match with home and away team stats
-- Raw results live in one table per season (raw_eliteserien_results_<season>)

with raw_eliteserien_results as (
   





    
    





select * from "raw_eliteserien_results_2021"
union all

select * from "raw_eliteserien_results_2022"
union all

select * from "raw_eliteserien_results_2023"
union all

select * from "raw_eliteserien_results_2024"
union all

select * from "raw_eliteserien_results_2025"
union all

select * from "raw_eliteserien_results_2026"




)

select
    season,
    date,
    matchday,
    home_team,
    away_team,
    result,
    cast(split_part(result, ':', 1) as integer) as home_goals,
    cast(split_part(result, ':', 2) as integer) as away_goals,
    -- Determine match winner
    case
        when home_goals > away_goals then 'home_team'
        when away_goals > home_goals then 'away_team'
        else 'draw'
    end as winner,
    snapshot_at,
    ingested_at
from raw_eliteserien_results
order by season, date, matchday
    );
    
  