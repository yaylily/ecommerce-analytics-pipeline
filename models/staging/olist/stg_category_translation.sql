select
    nullif(product_category_name, '') as product_category_name,
    nullif(product_category_name_english, '') as product_category_name_english
from {{ source('olist_raw', 'category_translation') }}
