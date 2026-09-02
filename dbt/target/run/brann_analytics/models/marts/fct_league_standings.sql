
    

    create  table
      "brann"."main"."fct_league_standings__dbt_tmp"
  
    
    as (
      

-- League standings after each matchday
-- Shows cumulative points, goals, and position for each team

with matches as (
    select * from "brann"."main"."fct_matches"
),

-- Split each match into two rows (one per team)
home as (
    select
        season,
        matchday,
        home_team as team,
        home_goals as goals_for,
        away_goals as goals_against,
        case
            when home_goals > away_goals then 3
            when home_goals = away_goals then 1
            else 0
        end as points
    from matches
),

away as (
    select
        season,
        matchday,
        away_team as team,
        away_goals as goals_for,
        home_goals as goals_against,
        case
            when away_goals > home_goals then 3
            when away_goals = home_goals then 1
            else 0
        end as points
    from matches
),

all_results as (
    select * from home
    union all
    select * from away
),

-- Cumulative stats per team per matchday
standings as (
    select
        season,
        matchday,
        team,
        sum(points) over (partition by season, team order by matchday) as total_points,
        sum(goals_for) over (partition by season, team order by matchday) as total_goals_for,
        sum(goals_against) over (partition by season, team order by matchday) as total_goals_against,
        (sum(goals_for) over (partition by season, team order by matchday)) -
        (sum(goals_against) over (partition by season, team order by matchday)) as goal_difference
    from all_results
),

-- Add table position
final as (
    select
        season,
        matchday,
        team,
        total_points,
        total_goals_for,
        total_goals_against,
        goal_difference,
        row_number() over (partition by season, matchday order by total_points desc, goal_difference desc) as position
    from standings
)

select * from final
order by season desc, matchday desc, position
    );
    
  