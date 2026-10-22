select
    nullif(order_id, '') as order_id,
    cast(nullif(order_item_id, '') as integer) as order_item_id,
    nullif(product_id, '') as product_id,
    nullif(seller_id, '') as seller_id,
    cast(nullif(shipping_limit_date, '') as timestamp without time zone)
        as shipping_limit_date,
    cast(nullif(price, '') as numeric) as price,
    cast(nullif(freight_value, '') as numeric) as freight_value
from {{ source('olist_raw', 'order_items') }}
