


with final as (
   





    
    





select * from "raw_match_statistics_2021"
union all

select * from "raw_match_statistics_2022"
union all

select * from "raw_match_statistics_2023"
union all

select * from "raw_match_statistics_2024"
union all

select * from "raw_match_statistics_2025"
union all

select * from "raw_match_statistics_2026"




)

select *
from final