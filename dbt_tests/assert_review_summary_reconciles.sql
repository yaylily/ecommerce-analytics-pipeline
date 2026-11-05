with expected as (
    select
        order_id,
        count(*) as review_count,
        sum(review_score) as review_score_sum,
        sum(review_score)::numeric / count(*) as order_avg_review_score,
        min(review_score) as min_review_score,
        max(review_score) as max_review_score
    from {{ ref('stg_reviews') }}
    group by order_id
),

actual as (
    select *
    from {{ ref('int_order_review_summary') }}
)

select coalesce(expected.order_id, actual.order_id) as order_id
from expected
full outer join actual using (order_id)
where expected.order_id is null
    or actual.order_id is null
    or expected.review_count is distinct from actual.review_count
    or expected.review_score_sum is distinct from actual.review_score_sum
    or expected.order_avg_review_score
        is distinct from actual.order_avg_review_score
    or expected.min_review_score is distinct from actual.min_review_score
    or expected.max_review_score is distinct from actual.max_review_score
