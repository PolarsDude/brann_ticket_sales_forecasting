
    

    create  table
      "brann"."main"."fct_lineups__dbt_tmp"
  
    
    as (
      


with final as (
   





    
    





select * from "raw_eliterserien_lineups_2021"
union all

select * from "raw_eliterserien_lineups_2022"
union all

select * from "raw_eliterserien_lineups_2023"
union all

select * from "raw_eliterserien_lineups_2024"
union all

select * from "raw_eliterserien_lineups_2025"
union all

select * from "raw_eliterserien_lineups_2026"




)

select *
from final
    );
    
  