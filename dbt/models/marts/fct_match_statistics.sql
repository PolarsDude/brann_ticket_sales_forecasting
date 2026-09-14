{{ config(materialized='table') }}

SELECT *
FROM {{ source('raw', 'raw_match_statistics') }}