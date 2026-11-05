select product_category_name
from {{ ref('stg_products') }}
where product_category_name = '__missing_source__'
