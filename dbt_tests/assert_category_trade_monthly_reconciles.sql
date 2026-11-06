with expected as (
    select
        order_items.purchase_month,
        order_items.category_key,
        products.product_category_name,
        products.product_category_name_english,
        products.category_display_name,
        products.category_mapping_status,
        sum(order_items.price) as gross_item_value,
        sum(order_items.freight_value) as freight_amount,
        sum(order_items.item_side_amount) as item_side_amount,
        count(*) as ordered_item_row_count,
        count(distinct order_items.product_id) as distinct_product_count,
        count(distinct order_items.order_id) as associated_order_count
    from {{ ref('fct_order_items') }} as order_items
    left join {{ ref('dim_products') }} as products
        on order_items.product_id = products.product_id
    where order_items.order_status = 'delivered'
    group by
        order_items.purchase_month,
        order_items.category_key,
        products.product_category_name,
        products.product_category_name_english,
        products.category_display_name,
        products.category_mapping_status
),

actual as (
    select *
    from {{ ref('mart_category_trade_monthly') }}
)

select
    coalesce(expected.purchase_month, actual.purchase_month) as purchase_month,
    coalesce(expected.category_key, actual.category_key) as category_key
from expected
full outer join actual
    on expected.purchase_month = actual.purchase_month
    and expected.category_key = actual.category_key
where expected.purchase_month is null
    or actual.purchase_month is null
    or expected.product_category_name
        is distinct from actual.product_category_name
    or expected.product_category_name_english
        is distinct from actual.product_category_name_english
    or expected.category_display_name
        is distinct from actual.category_display_name
    or expected.category_mapping_status
        is distinct from actual.category_mapping_status
    or expected.gross_item_value is distinct from actual.gross_item_value
    or expected.freight_amount is distinct from actual.freight_amount
    or expected.item_side_amount is distinct from actual.item_side_amount
    or expected.ordered_item_row_count
        is distinct from actual.ordered_item_row_count
    or expected.distinct_product_count
        is distinct from actual.distinct_product_count
    or expected.associated_order_count
        is distinct from actual.associated_order_count
