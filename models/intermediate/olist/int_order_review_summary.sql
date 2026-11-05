select
    order_id,
    count(*) as review_count,
    sum(review_score) as review_score_sum,
    sum(review_score)::numeric / count(*) as order_avg_review_score,
    min(review_score) as min_review_score,
    max(review_score) as max_review_score
from {{ ref('stg_reviews') }}
group by order_id
