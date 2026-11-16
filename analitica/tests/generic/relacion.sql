{#
    Test de datos: cada fila del modelo con «columnas» completas tiene su fila en «a», con las
    mismas columnas. Falla con una fila por cada huérfana. Es el «relationships» de dbt para
    una clave compuesta, que el suyo no admite: (run_id, episode_id) o (run_id, patient_id).
#}
{% test relacion(model, a, columnas) %}

select
    {% for c in columnas %}hija.{{ c }}{% if not loop.last %}, {% endif %}{% endfor %}
from {{ model }} as hija
left join {{ a }} as madre
    on {% for c in columnas %}madre.{{ c }} = hija.{{ c }}{% if not loop.last %}
    and {% endif %}{% endfor %}
where madre.{{ columnas[0] }} is null
    {% for c in columnas %}and hija.{{ c }} is not null
    {% endfor %}

{% endtest %}
