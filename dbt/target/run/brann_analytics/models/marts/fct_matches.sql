
    

    create  table
      "brann"."main"."fct_matches__dbt_tmp"
  
    
    as (
      

-- Match results with parsed goals and winner information
-- Each row is one match with home and away team stats

select
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
from "brann"."main"."raw_eliteserien_results"
order by date, matchday
    );
    
  