
    

    create  table
      "brann"."main"."fct_goal_contributions__dbt_tmp"
  
    
    as (
      


with final as (
   





    
    





select * from "raw_eliterserien_goal_contributions_2021"
union all

select * from "raw_eliterserien_goal_contributions_2022"
union all

select * from "raw_eliterserien_goal_contributions_2023"
union all

select * from "raw_eliterserien_goal_contributions_2024"
union all

select * from "raw_eliterserien_goal_contributions_2025"
union all

select * from "raw_eliterserien_goal_contributions_2026"




)

select *
from final
    );
    
  