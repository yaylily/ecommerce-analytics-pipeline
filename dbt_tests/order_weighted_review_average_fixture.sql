with orders (order_id, is_late) as (
    values
        ('late_order_a', true),
        ('late_order_b', true),
        ('not_late_order', false)
),

review_rows (order_id, review_score) as (
    values
        ('late_order_a', 1),
        ('late_order_a', 1),
        ('late_order_b', 5),
        ('not_late_order', 4)
),

order_review_summary as (
    select
        order_id,
        sum(review_score)::numeric / count(*) as order_avg_review_score
    from review_rows
    group by order_id
),

order_weighted as (
    select
        avg(order_avg_review_score) filter (where is_late)
            as late_avg_review_score,
        avg(order_avg_review_score) filter (where not is_late)
            as not_late_avg_review_score
    from orders
    inner join order_review_summary using (order_id)
),

review_row_weighted as (
    select avg(review_score::numeric) as late_avg_review_score
    from orders
    inner join review_rows using (order_id)
    where is_late
)

select 1 as fixture_failure
from order_weighted
cross join review_row_weighted
where order_weighted.late_avg_review_score <> 3
    or order_weighted.not_late_avg_review_score <> 4
    or order_weighted.late_avg_review_score
        - order_weighted.not_late_avg_review_score <> -1
    or review_row_weighted.late_avg_review_score <> 7::numeric / 3
    or order_weighted.late_avg_review_score
        is not distinct from review_row_weighted.late_avg_review_score
