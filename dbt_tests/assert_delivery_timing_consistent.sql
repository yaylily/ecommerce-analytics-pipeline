with expected as (
    select
        order_id,
        order_status,
        order_purchase_timestamp,
        order_approved_at,
        order_delivered_carrier_date,
        order_delivered_customer_date,
        order_estimated_delivery_date,
        order_approved_at is null as is_approval_date_missing,
        order_delivered_carrier_date is null as is_carrier_date_missing,
        order_status = 'delivered'
            and order_delivered_customer_date is null
            as is_delivery_date_missing,
        case
            when order_approved_at is null then null
            else order_approved_at < order_purchase_timestamp
        end as is_approval_before_purchase,
        case
            when order_delivered_carrier_date is null then null
            else order_delivered_carrier_date < order_purchase_timestamp
        end as is_carrier_before_purchase,
        case
            when order_delivered_carrier_date is null
                or order_approved_at is null then null
            else order_delivered_carrier_date < order_approved_at
        end as is_carrier_before_approval,
        case
            when order_delivered_customer_date is null then null
            else order_delivered_customer_date < order_purchase_timestamp
        end as is_customer_before_purchase,
        case
            when order_delivered_customer_date is null
                or order_delivered_carrier_date is null then null
            else order_delivered_customer_date < order_delivered_carrier_date
        end as is_customer_before_carrier,
        case
            when order_approved_at is not null
                and order_approved_at >= order_purchase_timestamp
                then order_approved_at - order_purchase_timestamp
        end as purchase_to_approval_duration,
        case
            when order_delivered_carrier_date is not null
                and order_delivered_carrier_date >= order_purchase_timestamp
                then order_delivered_carrier_date - order_purchase_timestamp
        end as purchase_to_carrier_duration,
        case
            when order_delivered_customer_date is not null
                and order_delivered_carrier_date is not null
                and order_delivered_customer_date >= order_delivered_carrier_date
                then order_delivered_customer_date - order_delivered_carrier_date
        end as carrier_to_customer_duration,
        case
            when order_delivered_customer_date is not null
                and order_delivered_customer_date >= order_purchase_timestamp
                then order_delivered_customer_date - order_purchase_timestamp
        end as purchase_to_customer_duration,
        case
            when order_status = 'delivered'
                and order_delivered_customer_date is not null
                and order_estimated_delivery_date is not null
                then order_delivered_customer_date::date
                    - order_estimated_delivery_date::date
        end as delivery_days_vs_estimate
    from {{ ref('stg_orders') }}
),

expected_with_status as (
    select
        *,
        case
            when delivery_days_vs_estimate is not null
                then delivery_days_vs_estimate > 0
        end as is_late,
        case
            when order_status <> 'delivered' then 'not_applicable'
            when delivery_days_vs_estimate is null then 'unknown'
            when delivery_days_vs_estimate < 0 then 'early'
            when delivery_days_vs_estimate = 0 then 'promised_date'
            else 'late'
        end as delivery_timing_status
    from expected
)

select actual.order_id
from {{ ref('int_order_delivery_timing') }} as actual
inner join expected_with_status as expected using (order_id)
where actual.is_approval_date_missing
        is distinct from expected.is_approval_date_missing
    or actual.order_status is distinct from expected.order_status
    or actual.order_purchase_timestamp
        is distinct from expected.order_purchase_timestamp
    or actual.order_approved_at is distinct from expected.order_approved_at
    or actual.order_delivered_carrier_date
        is distinct from expected.order_delivered_carrier_date
    or actual.order_delivered_customer_date
        is distinct from expected.order_delivered_customer_date
    or actual.order_estimated_delivery_date
        is distinct from expected.order_estimated_delivery_date
    or actual.is_carrier_date_missing
        is distinct from expected.is_carrier_date_missing
    or actual.is_delivery_date_missing
        is distinct from expected.is_delivery_date_missing
    or actual.is_approval_before_purchase
        is distinct from expected.is_approval_before_purchase
    or actual.is_carrier_before_purchase
        is distinct from expected.is_carrier_before_purchase
    or actual.is_carrier_before_approval
        is distinct from expected.is_carrier_before_approval
    or actual.is_customer_before_purchase
        is distinct from expected.is_customer_before_purchase
    or actual.is_customer_before_carrier
        is distinct from expected.is_customer_before_carrier
    or actual.purchase_to_approval_duration
        is distinct from expected.purchase_to_approval_duration
    or actual.purchase_to_carrier_duration
        is distinct from expected.purchase_to_carrier_duration
    or actual.carrier_to_customer_duration
        is distinct from expected.carrier_to_customer_duration
    or actual.purchase_to_customer_duration
        is distinct from expected.purchase_to_customer_duration
    or actual.delivery_days_vs_estimate
        is distinct from expected.delivery_days_vs_estimate
    or actual.delivery_timing_status
        is distinct from expected.delivery_timing_status
    or actual.is_late is distinct from expected.is_late
