{#
    El paso al final de cada construcción (on-run-end) que da USAGE en los esquemas que tocó
    (pendiente de la 8.4; notas del chat de la 8.5, punto 7). La configuración grants de dbt da
    SELECT en cada tabla y vista, dentro de la transacción que la crea, pero no USAGE en su
    esquema, y sin USAGE un rol no ve nada de él.

    Los esquemas del hospital (preparacion, plata y oro), a hospital y laboratorio; los de las
    otras hojas (verdad_*, ingenuo_*) y laboratorio, solo a laboratorio. «schemas» es la lista
    de esquemas de la construcción, que dbt da al on-run-end. Un esquema que no es de ninguna
    hoja no se toca.
#}
{% macro dar_uso_de_esquemas(schemas) -%}
    {%- set del_hospital = ['preparacion', 'plata', 'oro'] -%}
    {%- set sentencias = [] -%}
    {%- for esquema in schemas | sort -%}
        {%- if esquema in del_hospital -%}
            {%- do sentencias.append('grant usage on schema ' ~ adapter.quote(esquema) ~ ' to hospital, laboratorio') -%}
        {%- elif esquema == 'laboratorio' or esquema.startswith('verdad_') or esquema.startswith('ingenuo_') -%}
            {%- do sentencias.append('grant usage on schema ' ~ adapter.quote(esquema) ~ ' to laboratorio') -%}
        {%- endif -%}
    {%- endfor -%}
    {{ return(sentencias | join(';\n') if sentencias else 'select 1') }}
{%- endmacro %}
