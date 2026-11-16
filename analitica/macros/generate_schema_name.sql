{#
    El esquema de cada modelo, con su nombre exacto (docs/specs/hito-8.md, «Esquemas y la
    variable hoja»).

    Por defecto, dbt pone delante el esquema del destino: «public_preparacion». Esta macro lo
    sustituye para que el esquema se llame exactamente como su capa (preparacion, plata, oro,
    laboratorio) en la hoja del hospital y, en las otras, con la hoja delante:
    verdad_preparacion, ingenuo_plata… Así el hospital no puede leer la verdad por error: cada
    hoja vive en sus esquemas (decisión 107, H8-8).

    Un modelo sin esquema propio va al del destino (profiles.yml), sin prefijo.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- elif var('hoja') == 'hospital' -%}
        {{ custom_schema_name | trim }}
    {%- else -%}
        {{ var('hoja') }}_{{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
