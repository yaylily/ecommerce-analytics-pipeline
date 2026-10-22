select
    nullif(order_id, '') as order_id,
    nullif(customer_id, '') as customer_id,
    nullif(order_status, '') as order_status,
    cast(nullif(order_purchase_timestamp, '') as timestamp without time zone)
        as order_purchase_timestamp,
    cast(nullif(order_approved_at, '') as timestamp without time zone)
        as order_approved_at,
    cast(nullif(order_delivered_carrier_date, '') as timestamp without time zone)
        as order_delivered_carrier_date,
    cast(nullif(order_delivered_customer_date, '') as timestamp without time zone)
        as order_delivered_customer_date,
    cast(nullif(order_estimated_delivery_date, '') as timestamp without time zone)
        as order_estimated_delivery_date
from {{ source('olist_raw', 'orders') }}
