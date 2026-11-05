select
    order_items.order_id,
    order_items.order_item_id,
    order_items.product_id,
    order_items.seller_id,
    products.category_key,
    orders.order_status,
    orders.order_purchase_timestamp,
    date_trunc('month', orders.order_purchase_timestamp)::date
        as purchase_month,
    order_items.shipping_limit_date,
    order_items.price,
    order_items.freight_value,
    order_items.price + order_items.freight_value as item_side_amount
from {{ ref('stg_order_items') }} as order_items
left join {{ ref('stg_orders') }} as orders
    on order_items.order_id = orders.order_id
left join {{ ref('dim_products') }} as products
    on order_items.product_id = products.product_id
left join {{ ref('dim_sellers') }} as sellers
    on order_items.seller_id = sellers.seller_id
