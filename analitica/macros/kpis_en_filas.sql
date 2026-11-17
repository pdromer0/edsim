{#
    Los nueve indicadores del hito 7 de oro.kpi_ejecucion, en el orden de la tabla de tres
    columnas: el de Comparison.rows() de compare.py.
#}
{% macro kpis_ejecucion() -%}
    {{ return([
        'llegadas', 'censo_medio', 'mediana_triaje_min', 'mediana_medico_min',
        'pct_nivel_1', 'pct_nivel_2', 'pct_nivel_3', 'pct_nivel_4', 'pct_nivel_5',
    ]) }}
{%- endmacro %}


{#
    Los nueve indicadores de una tabla kpi_ejecucion, una fila por (run_id, kpi), con su valor
    en double precision. Las llegadas son un recuento: en double precision son exactas mientras
    no pasen de 2^53.
#}
{% macro kpis_en_filas(relacion) -%}
    select k.run_id, v.kpi, v.valor
    from {{ relacion }} as k
    cross join lateral (
        values
        {%- for kpi in kpis_ejecucion() %}
            ('{{ kpi }}', k.{{ kpi }}::double precision){{ "," if not loop.last }}
        {%- endfor %}
    ) as v (kpi, valor)
{%- endmacro %}
