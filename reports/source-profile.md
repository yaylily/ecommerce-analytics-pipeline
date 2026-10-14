# 원천 데이터 구조 프로파일

집계 검사로 생성한 파일이며 원천 행이나 샘플 값을 포함하지 않습니다.
후보키는 원천에서 관찰한 가설이며 아직 승인된 모델 기본키가 아닙니다.
미연결 행과 다중 행은 관찰 결과이며 처리 방식은 후속 계약에서 결정합니다.
타입·도메인·시간 순서와 원천 간 금액 대사는 후속 프로파일 범위입니다.

- Dataset: `olistbr/brazilian-ecommerce`
- Manifest SHA-256: `041d600393762a8894f995816d71f805ac09672b8ce2ea7d134ce3a0669f71bb`

## 파일

| 테이블 | 논리 행 수 | 바이트 | UTF-8 BOM | SHA-256 |
|---|---:|---:|:---:|---|
| `geolocation` | 1000163 | 61273883 | no | `b514f6fc991b9566aeba02aa5d67e2c3630f034b60a0e05aa0d082a3b66d88d6` |
| `customers` | 99441 | 9033957 | no | `983a422239e1712ded753b3bf9ecf47dc73f144d306029dcfa99e70a226883d2` |
| `category_translation` | 71 | 2613 | yes | `a81f0d1f27b27e7293f761bc79e3ce8f348ee39c4b3ed3e49bde38f478586278` |
| `products` | 32951 | 2379446 | no | `3e6569628a17fbc75fd206ee357b59e20364b9afa90f5b6cd5b4d624c58aa9cc` |
| `sellers` | 3095 | 174703 | no | `1f643d2b950373b85735e7794b20986f528d7a000432e7c6f9bcbb44d0846a0e` |
| `orders` | 99441 | 17654914 | no | `8df58ef3d2d7e9944010f7beecd9b75367f5588ec6e3c91cec19ae3345ef9ecf` |
| `order_items` | 112650 | 15438671 | no | `0bc4d068c4fe38cbb01bd90e8746e3c613fe7b4baef75fab7b0e329701c3e279` |
| `payments` | 103886 | 5777138 | no | `4f713964f2815dbbaa40b9488268c55aac3627bfce5aa96cf58d1f3616de3cc0` |
| `reviews` | 99224 | 14451670 | no | `012b61c7593e34f51fa614efdf802b9c7056ce6aae5307ddb93236e7cfc797d7` |

## 후보키와 관찰된 다중도

| 테이블 | 프로파일 | 고유값 | NULL 행 | 키 기준 추가 행 | 복수행 키 | 최대 다중도 |
|---|---|---:|---:|---:|---:|---:|
| `category_translation` | `product_category_name` | 71 | 0 | 0 | 0 | 1 |
| `customers` | `customer_id` | 99441 | 0 | 0 | 0 | 1 |
| `customers` | `customer_unique_id` | 96096 | 0 | 3345 | 2997 | 17 |
| `geolocation` | `geolocation_zip_code_prefix` | 19015 | 0 | 981148 | 17972 | 1146 |
| `order_items` | `order_id_order_item_id` | 112650 | 0 | 0 | 0 | 1 |
| `orders` | `order_id` | 99441 | 0 | 0 | 0 | 1 |
| `payments` | `order_id_payment_sequential` | 103886 | 0 | 0 | 0 | 1 |
| `products` | `product_id` | 32951 | 0 | 0 | 0 | 1 |
| `reviews` | `review_id_order_id` | 99224 | 0 | 0 | 0 | 1 |
| `reviews` | `order_id` | 98673 | 0 | 551 | 547 | 3 |
| `reviews` | `review_id` | 98410 | 0 | 814 | 789 | 3 |
| `sellers` | `seller_id` | 3095 | 0 | 0 | 0 | 1 |

## NULL과 공백 문자열

0보다 큰 항목만 표시합니다. 빈 문자열은 NULL로, 공백만 있는 문자열은 별도 집계합니다.

| 테이블 | 열 | NULL 행 | 공백 문자열 행 |
|---|---|---:|---:|
| `orders` | `order_approved_at` | 160 | 0 |
| `orders` | `order_delivered_carrier_date` | 1783 | 0 |
| `orders` | `order_delivered_customer_date` | 2965 | 0 |
| `products` | `product_category_name` | 610 | 0 |
| `products` | `product_name_lenght` | 610 | 0 |
| `products` | `product_description_lenght` | 610 | 0 |
| `products` | `product_photos_qty` | 610 | 0 |
| `products` | `product_weight_g` | 2 | 0 |
| `products` | `product_length_cm` | 2 | 0 |
| `products` | `product_height_cm` | 2 | 0 |
| `products` | `product_width_cm` | 2 | 0 |
| `reviews` | `review_comment_title` | 87656 | 2 |
| `reviews` | `review_comment_message` | 58247 | 27 |

## 관계

부모 측 키가 고유하지 않으면 직접 조인에서 자식 행이 증폭될 수 있습니다.

| 관계 | NULL 제외 자식 행 | NULL 키 | 연결 행 | 미연결 행 | 연결 부모 키당 최대 행 | 직접 조인 행 | 연결 자식당 행 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `customers_to_geolocation` | 99441 | 0 | 99163 | 278 | 1146 | 15083455 | 152.107691 |
| `order_items_to_orders` | 112650 | 0 | 112650 | 0 | 1 | 112650 | 1.000000 |
| `order_items_to_products` | 112650 | 0 | 112650 | 0 | 1 | 112650 | 1.000000 |
| `order_items_to_sellers` | 112650 | 0 | 112650 | 0 | 1 | 112650 | 1.000000 |
| `orders_to_customers` | 99441 | 0 | 99441 | 0 | 1 | 99441 | 1.000000 |
| `payments_to_orders` | 103886 | 0 | 103886 | 0 | 1 | 103886 | 1.000000 |
| `products_to_category_translation` | 32341 | 610 | 32328 | 13 | 1 | 32328 | 1.000000 |
| `reviews_to_orders` | 99224 | 0 | 99224 | 0 | 1 | 99224 | 1.000000 |
| `sellers_to_geolocation` | 3095 | 0 | 3088 | 7 | 965 | 435087 | 140.896049 |

## Fan-out

| 프로파일 | 부모 수 | 자식 0개 | 1개 | 복수 | 최대 |
|---|---:|---:|---:|---:|---:|
| `items_per_order` | 99441 | 775 | 88863 | 9803 | 21 |
| `payments_per_order` | 99441 | 1 | 96479 | 2961 | 29 |
| `reviews_per_order` | 99441 | 768 | 98126 | 547 | 3 |

## 직접 조인 증폭

### `order_items_x_payments_by_order`

- 양쪽에 모두 존재하는 키: 98665
- 조인 전 왼쪽 행: 112647
- 조인 전 오른쪽 행: 103056
- 직접 조인 후 행: 117601
- 왼쪽 대비 행 배수: 1.043978
- 오른쪽 대비 행 배수: 1.141137

| 측면 | 금액 열 | 기준 합계 | 직접 조인 합계 | 배수 | 증가액 | NULL 행 | 변환 실패 행 |
|---|---|---:|---:|---:|---:|---:|---:|
| left | `freight_value` | 2251901.05 | 2357428.51 | 1.046861 | 105527.46 | 0 | 0 |
| left | `price` | 13591508.73 | 14209115.34 | 1.045441 | 617606.61 | 0 | 0 |
| right | `payment_value` | 15846280.17 | 20308134.71 | 1.281571 | 4461854.54 | 0 | 0 |
