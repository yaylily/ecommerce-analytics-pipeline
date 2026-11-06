with expected as (
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
),

actual as (
    select *
    from {{ ref('fct_order_items') }}
)

select
    coalesce(expected.order_id, actual.order_id) as order_id,
    coalesce(expected.order_item_id, actual.order_item_id) as order_item_id
from expected
full outer join actual
    on expected.order_id = actual.order_id
    and expected.order_item_id = actual.order_item_id
where expected.order_id is null
    or actual.order_id is null
    or expected.product_id is distinct from actual.product_id
    or expected.seller_id is distinct from actual.seller_id
    or expected.category_key is distinct from actual.category_key
    or expected.order_status is distinct from actual.order_status
    or expected.order_purchase_timestamp
        is distinct from actual.order_purchase_timestamp
    or expected.purchase_month is distinct from actual.purchase_month
    or expected.shipping_limit_date
        is distinct from actual.shipping_limit_date
    or expected.price is distinct from actual.price
    or expected.freight_value is distinct from actual.freight_value
    or expected.item_side_amount is distinct from actual.item_side_amount
