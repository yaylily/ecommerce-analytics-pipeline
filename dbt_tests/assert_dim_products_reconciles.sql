with expected as (
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
    from {{ ref('stg_products') }} as products
    left join {{ ref('stg_category_translation') }} as category_translation
        on products.product_category_name
            = category_translation.product_category_name
),

actual as (
    select *
    from {{ ref('dim_products') }}
)

select coalesce(expected.product_id, actual.product_id) as product_id
from expected
full outer join actual using (product_id)
where expected.product_id is null
    or actual.product_id is null
    or expected.product_category_name
        is distinct from actual.product_category_name
    or expected.product_category_name_english
        is distinct from actual.product_category_name_english
    or expected.category_key is distinct from actual.category_key
    or expected.category_display_name
        is distinct from actual.category_display_name
    or expected.category_mapping_status
        is distinct from actual.category_mapping_status
