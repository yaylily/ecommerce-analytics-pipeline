{% test expression_is_true(model, expression) %}

select 1 as contract_failure
from {{ model }}
where not ({{ expression }})

{% endtest %}
