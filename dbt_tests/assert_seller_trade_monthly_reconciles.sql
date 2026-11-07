with expected as (
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
),

actual as (
    select *
    from {{ ref('mart_seller_trade_monthly') }}
)

select
    coalesce(expected.purchase_month, actual.purchase_month) as purchase_month,
    coalesce(expected.seller_id, actual.seller_id) as seller_id
from expected
full outer join actual
    on expected.purchase_month = actual.purchase_month
    and expected.seller_id = actual.seller_id
where expected.purchase_month is null
    or actual.purchase_month is null
    or expected.seller_zip_code_prefix
        is distinct from actual.seller_zip_code_prefix
    or expected.seller_city is distinct from actual.seller_city
    or expected.seller_state is distinct from actual.seller_state
    or expected.gross_item_value is distinct from actual.gross_item_value
    or expected.freight_amount is distinct from actual.freight_amount
    or expected.item_side_amount is distinct from actual.item_side_amount
    or expected.ordered_item_row_count
        is distinct from actual.ordered_item_row_count
    or expected.distinct_product_count
        is distinct from actual.distinct_product_count
    or expected.associated_order_count
        is distinct from actual.associated_order_count
