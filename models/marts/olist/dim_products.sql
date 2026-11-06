with products as (
    select
        product_id,
        product_category_name
    from {{ ref('stg_products') }}
),

category_translation as (
    select
        product_category_name,
        product_category_name_english
    from {{ ref('stg_category_translation') }}
)

select
    products.product_id,
    products.product_category_name,
    category_translation.product_category_name_english,
    coalesce(
        products.product_category_name,
        '__missing_source__'
    ) as category_key,
    coalesce(
        category_translation.product_category_name_english,
        products.product_category_name,
        'Unknown'
    ) as category_display_name,
    case
        when products.product_category_name is null then 'missing_source'
        when category_translation.product_category_name_english is null
            then 'unmapped_translation'
        else 'mapped'
    end as category_mapping_status
from products
left join category_translation
    on products.product_category_name
        = category_translation.product_category_name
