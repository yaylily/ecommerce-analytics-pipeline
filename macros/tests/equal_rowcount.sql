{% test equal_rowcount(model, compare_model) %}

with model_count as (
    select count(*) as row_count
    from {{ model }}
),

comparison_count as (
    select count(*) as row_count
    from {{ compare_model }}
)

select
    model_count.row_count as model_row_count,
    comparison_count.row_count as comparison_row_count
from model_count
cross join comparison_count
where model_count.row_count <> comparison_count.row_count

{% endtest %}
