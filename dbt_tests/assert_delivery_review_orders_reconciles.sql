with expected as (
    select
        delivery.order_id,
        delivery.order_status,
        delivery.order_purchase_timestamp,
        delivery.order_delivered_customer_date,
        delivery.order_estimated_delivery_date,
        delivery.delivery_days_vs_estimate,
        delivery.delivery_timing_status,
        delivery.is_late,
        delivery.is_approval_date_missing,
        delivery.is_carrier_date_missing,
        delivery.is_approval_before_purchase,
        delivery.is_carrier_before_purchase,
        delivery.is_carrier_before_approval,
        delivery.is_customer_before_purchase,
        delivery.is_customer_before_carrier,
        reviews.review_count,
        reviews.review_score_sum,
        reviews.order_avg_review_score,
        reviews.min_review_score,
        reviews.max_review_score
    from {{ ref('int_order_delivery_timing') }} as delivery
    inner join {{ ref('int_order_review_summary') }} as reviews
        on delivery.order_id = reviews.order_id
    where delivery.order_status = 'delivered'
        and delivery.order_delivered_customer_date is not null
        and delivery.order_estimated_delivery_date is not null
        and delivery.delivery_timing_status in (
            'early',
            'promised_date',
            'late'
        )
),

actual as (
    select *
    from {{ ref('mart_delivery_review_orders') }}
)

select coalesce(expected.order_id, actual.order_id) as order_id
from expected
full outer join actual using (order_id)
where expected.order_id is null
    or actual.order_id is null
    or expected.order_status is distinct from actual.order_status
    or expected.order_purchase_timestamp
        is distinct from actual.order_purchase_timestamp
    or expected.order_delivered_customer_date
        is distinct from actual.order_delivered_customer_date
    or expected.order_estimated_delivery_date
        is distinct from actual.order_estimated_delivery_date
    or expected.delivery_days_vs_estimate
        is distinct from actual.delivery_days_vs_estimate
    or expected.delivery_timing_status
        is distinct from actual.delivery_timing_status
    or expected.is_late is distinct from actual.is_late
    or expected.is_approval_date_missing
        is distinct from actual.is_approval_date_missing
    or expected.is_carrier_date_missing
        is distinct from actual.is_carrier_date_missing
    or expected.is_approval_before_purchase
        is distinct from actual.is_approval_before_purchase
    or expected.is_carrier_before_purchase
        is distinct from actual.is_carrier_before_purchase
    or expected.is_carrier_before_approval
        is distinct from actual.is_carrier_before_approval
    or expected.is_customer_before_purchase
        is distinct from actual.is_customer_before_purchase
    or expected.is_customer_before_carrier
        is distinct from actual.is_customer_before_carrier
    or expected.review_count is distinct from actual.review_count
    or expected.review_score_sum is distinct from actual.review_score_sum
    or expected.order_avg_review_score
        is distinct from actual.order_avg_review_score
    or expected.min_review_score is distinct from actual.min_review_score
    or expected.max_review_score is distinct from actual.max_review_score
