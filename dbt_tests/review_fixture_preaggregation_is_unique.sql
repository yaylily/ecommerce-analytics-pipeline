with orders (order_id) as (
    values ('synthetic_order')
),

reviews (order_id, review_score) as (
    values
        ('synthetic_order', 3),
        ('synthetic_order', 5)
),

raw_join as (
    select orders.order_id, reviews.review_score
    from orders
    inner join reviews using (order_id)
),

review_summary as (
    select
        order_id,
        count(*) as review_count,
        sum(review_score) as review_score_sum,
        sum(review_score)::numeric / count(*) as avg_review_score
    from reviews
    group by order_id
),

safe_join as (
    select orders.order_id, review_summary.*
    from orders
    inner join review_summary using (order_id)
)

select 1 as fixture_failure
where (select count(*) from raw_join) <> 2
    or (select count(*) from safe_join) <> 1
    or (select review_count from safe_join) <> 2
    or (select review_score_sum from safe_join) <> 8
    or (select avg_review_score from safe_join) <> 4
