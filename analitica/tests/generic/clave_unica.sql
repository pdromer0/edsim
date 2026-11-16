{#
    Test de datos: la clave compuesta «columnas» no se repite en el modelo. Falla con una fila
    por clave repetida. El «unique» de dbt solo mira una columna, y las claves de plata llevan
    siempre run_id (decisión 104, H8-5).
#}
{% test clave_unica(model, columnas) %}

select
    {{ columnas | join(', ') }},
    count(*) as repeticiones
from {{ model }}
group by {{ columnas | join(', ') }}
having count(*) > 1

{% endtest %}
