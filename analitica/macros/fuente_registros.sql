{#
    De dónde lee preparacion.registros según la hoja: lo registrado (bronce.eventos) en las
    hojas hospital e ingenuo, y la verdad de la simulación (verdad.eventos) en la hoja verdad.
#}
{% macro fuente_registros() -%}
    {%- set hoja = var('hoja') -%}
    {%- if hoja in ('hospital', 'ingenuo') -%}
        {{ source('bronce', 'eventos') }}
    {%- elif hoja == 'verdad' -%}
        {{ source('verdad', 'eventos') }}
    {%- else -%}
        {{ exceptions.raise_compiler_error("hoja desconocida: '" ~ hoja ~ "'; las válidas son hospital, verdad e ingenuo") }}
    {%- endif -%}
{%- endmacro %}
