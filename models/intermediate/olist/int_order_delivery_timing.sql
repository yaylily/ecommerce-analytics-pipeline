with orders as (
    select
        order_id,
        order_status,
        order_purchase_timestamp,
        order_approved_at,
        order_delivered_carrier_date,
        order_delivered_customer_date,
        order_estimated_delivery_date
    from {{ ref('stg_orders') }}
),

derived as (
    select
        *,
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
            when order_status = 'delivered'
                and order_delivered_customer_date is not null
                and order_estimated_delivery_date is not null
                then order_delivered_customer_date::date
                    - order_estimated_delivery_date::date
        end as delivery_days_vs_estimate
    from orders
)

select
    order_id,
    order_status,
    order_purchase_timestamp,
    order_approved_at,
    order_delivered_carrier_date,
    order_delivered_customer_date,
    order_estimated_delivery_date,
    is_approval_date_missing,
    is_carrier_date_missing,
    is_delivery_date_missing,
    is_approval_before_purchase,
    is_carrier_before_purchase,
    is_carrier_before_approval,
    is_customer_before_purchase,
    is_customer_before_carrier,
    case
        when order_approved_at is not null
            and not is_approval_before_purchase
            then order_approved_at - order_purchase_timestamp
    end as purchase_to_approval_duration,
    case
        when order_delivered_carrier_date is not null
            and not is_carrier_before_purchase
            then order_delivered_carrier_date - order_purchase_timestamp
    end as purchase_to_carrier_duration,
    case
        when order_delivered_customer_date is not null
            and order_delivered_carrier_date is not null
            and not is_customer_before_carrier
            then order_delivered_customer_date - order_delivered_carrier_date
    end as carrier_to_customer_duration,
    case
        when order_delivered_customer_date is not null
            and not is_customer_before_purchase
            then order_delivered_customer_date - order_purchase_timestamp
    end as purchase_to_customer_duration,
    delivery_days_vs_estimate,
    case
        when order_status <> 'delivered' then 'not_applicable'
        when delivery_days_vs_estimate is null then 'unknown'
        when delivery_days_vs_estimate < 0 then 'early'
        when delivery_days_vs_estimate = 0 then 'promised_date'
        else 'late'
    end as delivery_timing_status,
    case
        when delivery_days_vs_estimate is not null
            then delivery_days_vs_estimate > 0
    end as is_late
from derived
