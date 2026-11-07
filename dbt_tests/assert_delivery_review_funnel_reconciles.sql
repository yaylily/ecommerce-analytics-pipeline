with timing_and_reviews as (
    select
        delivery.*,
        reviews.order_id is not null as has_review_summary,
        reviews.review_count,
        reviews.review_score_sum
    from {{ ref('int_order_delivery_timing') }} as delivery
    left join {{ ref('int_order_review_summary') }} as reviews
        on delivery.order_id = reviews.order_id
),

expected as (
    select
        count(*) filter (
            where order_status = 'delivered'
        ) as delivered_order_count,
        count(*) filter (
            where order_status = 'delivered'
                and order_delivered_customer_date is not null
                and order_estimated_delivery_date is not null
        ) as comparable_delivery_order_count,
        count(*) filter (
            where order_status = 'delivered'
                and (
                    order_delivered_customer_date is null
                    or order_estimated_delivery_date is null
                )
        ) as unknown_delivery_order_count,
        count(*) filter (
            where order_status = 'delivered'
                and order_delivered_customer_date is not null
                and order_estimated_delivery_date is not null
                and has_review_summary
        ) as reviewed_comparable_order_count,
        count(*) filter (
            where order_status = 'delivered'
                and order_delivered_customer_date is not null
                and order_estimated_delivery_date is not null
                and not has_review_summary
        ) as unreviewed_comparable_order_count,
        sum(review_count) filter (
            where order_status = 'delivered'
                and order_delivered_customer_date is not null
                and order_estimated_delivery_date is not null
                and has_review_summary
        ) as review_row_count,
        sum(review_score_sum) filter (
            where order_status = 'delivered'
                and order_delivered_customer_date is not null
                and order_estimated_delivery_date is not null
                and has_review_summary
        ) as review_score_sum
    from timing_and_reviews
),

actual as (
    select
        count(*) as reviewed_comparable_order_count,
        count(*) filter (
            where delivery_timing_status = 'early'
        ) as early_order_count,
        count(*) filter (
            where delivery_timing_status = 'promised_date'
        ) as promised_date_order_count,
        count(*) filter (
            where delivery_timing_status = 'late'
        ) as late_status_order_count,
        count(*) filter (where is_late) as late_flag_order_count,
        count(*) filter (where not is_late) as not_late_order_count,
        sum(review_count) as review_row_count,
        sum(review_score_sum) as review_score_sum
    from {{ ref('mart_delivery_review_orders') }}
)

select 1 as reconciliation_failure
from expected
cross join actual
where expected.delivered_order_count is distinct from
        expected.comparable_delivery_order_count
        + expected.unknown_delivery_order_count
    or expected.comparable_delivery_order_count is distinct from
        expected.reviewed_comparable_order_count
        + expected.unreviewed_comparable_order_count
    or actual.reviewed_comparable_order_count
        is distinct from expected.reviewed_comparable_order_count
    or actual.reviewed_comparable_order_count is distinct from
        actual.early_order_count
        + actual.promised_date_order_count
        + actual.late_status_order_count
    or actual.reviewed_comparable_order_count is distinct from
        actual.late_flag_order_count + actual.not_late_order_count
    or actual.late_status_order_count
        is distinct from actual.late_flag_order_count
    or actual.review_row_count is distinct from expected.review_row_count
    or actual.review_score_sum is distinct from expected.review_score_sum
