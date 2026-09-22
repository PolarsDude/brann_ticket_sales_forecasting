{% macro union_tables_by_prefix(table_prefix, schema_name='main') %}

{% set tables_query %}
    select table_name
    from information_schema.tables
    where table_schema = '{{ schema_name }}'
      and table_name like '{{ table_prefix }}%'
    order by table_name
{% endset %}

{% set matching_tables = [] %}
{% if execute %}
    {% set results = run_query(tables_query) %}
    {% set matching_tables = results.columns[0].values() %}
{% endif %}

{% if execute and matching_tables | length == 0 %}
    {{ exceptions.raise_compiler_error("No tables matching '" ~ table_prefix ~ "%' found in schema '" ~ schema_name ~ "'.") }}
{% endif %}

{% for table_name in matching_tables %}
select * from {{ adapter.quote(table_name) }}
{% if not loop.last %}union all{% endif %}
{% endfor %}

{% endmacro %}