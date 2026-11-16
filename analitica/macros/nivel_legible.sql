{#
    Si el nivel del triaje es legible: un número entero del 1 al 5, como el isinstance(int) de
    compare.py. Un 3.0 o un "3" no cuentan, y un nivel vacío (null) tampoco. Lo usan
    kpi_ejecucion y kpi_hora, para que el reparto por nivel cuente lo mismo en las dos.
#}
{% macro nivel_legible(payload='payload') -%}
    coalesce(
        jsonb_typeof({{ payload }} -> 'nivel') = 'number'
            and {{ payload }} ->> 'nivel' in ('1', '2', '3', '4', '5'),
        false
    )
{%- endmacro %}
