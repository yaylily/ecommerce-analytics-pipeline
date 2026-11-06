with fixture_products (product_id, product_category_name) as (
    values
        ('product_mapped', 'category_mapped'),
        ('product_missing', null::text),
        ('product_unmapped', 'category_unmapped')
),

fixture_translation (
    product_category_name,
    product_category_name_english
) as (
    values ('category_mapped', 'mapped_category')
),

actual as (
    select
        products.product_id,
        coalesce(
            products.product_category_name,
            '__missing_source__'
        ) as category_key,
        case
            when products.product_category_name is null then 'missing_source'
            when translation.product_category_name_english is null
                then 'unmapped_translation'
            else 'mapped'
        end as category_mapping_status
    from fixture_products as products
    left join fixture_translation as translation
        on products.product_category_name = translation.product_category_name
),

expected (product_id, category_key, category_mapping_status) as (
    values
        ('product_mapped', 'category_mapped', 'mapped'),
        ('product_missing', '__missing_source__', 'missing_source'),
        (
            'product_unmapped',
            'category_unmapped',
            'unmapped_translation'
        )
)

select coalesce(expected.product_id, actual.product_id) as product_id
from expected
full outer join actual using (product_id)
where expected.product_id is null
    or actual.product_id is null
    or expected.category_key is distinct from actual.category_key
    or expected.category_mapping_status
        is distinct from actual.category_mapping_status
