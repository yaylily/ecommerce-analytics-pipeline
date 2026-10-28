select
    nullif(product_id, '') as product_id,
    nullif(product_category_name, '') as product_category_name,
    nullif(product_name_lenght, '') as product_name_length,
    nullif(product_description_lenght, '') as product_description_length,
    nullif(product_photos_qty, '') as product_photo_count,
    nullif(product_weight_g, '') as product_weight_g,
    nullif(product_length_cm, '') as product_length_cm,
    nullif(product_height_cm, '') as product_height_cm,
    nullif(product_width_cm, '') as product_width_cm
from {{ source('olist_raw', 'products') }}
