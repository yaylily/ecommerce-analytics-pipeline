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
