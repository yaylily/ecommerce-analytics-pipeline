select
    order_items.purchase_month,
    order_items.seller_id,
    sellers.seller_zip_code_prefix,
    sellers.seller_city,
    sellers.seller_state,
    sum(order_items.price) as gross_item_value,
    sum(order_items.freight_value) as freight_amount,
    sum(order_items.item_side_amount) as item_side_amount,
    count(*) as ordered_item_row_count,
    count(distinct order_items.product_id) as distinct_product_count,
    count(distinct order_items.order_id) as associated_order_count
from {{ ref('fct_order_items') }} as order_items
left join {{ ref('dim_sellers') }} as sellers
    on order_items.seller_id = sellers.seller_id
where order_items.order_status = 'delivered'
group by
    order_items.purchase_month,
    order_items.seller_id,
    sellers.seller_zip_code_prefix,
    sellers.seller_city,
    sellers.seller_state
