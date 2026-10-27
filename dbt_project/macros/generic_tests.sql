{% test non_negative(model, column_name) %}

select {{ column_name }}
from {{ model }}
where {{ column_name }} is not null
  and {{ column_name }} < 0

{% endtest %}


{% test positive(model, column_name) %}

select {{ column_name }}
from {{ model }}
where {{ column_name }} is not null
  and {{ column_name }} <= 0

{% endtest %}


{% test within_range(model, column_name, min_value=none, max_value=none) %}

select {{ column_name }}
from {{ model }}
where {{ column_name }} is not null
  {% if min_value is not none %}and {{ column_name }} < {{ min_value }}{% endif %}
  {% if max_value is not none %}and {{ column_name }} > {{ max_value }}{% endif %}

{% endtest %}


{% test denominator_coverage(model, denominator_column, min_coverage=0.5) %}
{#-
  A row-level rate is only publishable when a denominator exists. This test
  fails a model that publishes rates computed without a denominator.
-#}
select
    count(*) as rows_without_denominator
from {{ model }}
where {{ denominator_column }} is null

{% endtest %}
