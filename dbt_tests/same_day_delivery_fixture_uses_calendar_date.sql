with fixture as (
    select
        '2018-01-10 16:00:00'::timestamp without time zone
            as delivered_at,
        '2018-01-10 00:00:00'::timestamp without time zone
            as estimated_at
),

comparison as (
    select
        delivered_at > estimated_at as timestamp_would_be_late,
        delivered_at::date - estimated_at::date as delivery_day_difference
    from fixture
)

select *
from comparison
where not timestamp_would_be_late
    or delivery_day_difference <> 0
