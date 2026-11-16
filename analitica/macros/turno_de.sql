{#
    El turno de la hora k (horas desde el origen, que es una medianoche): un left join lateral
    que añade turno, inicio_turno y fecha_turno, vacíos si k es nulo (un episodio sin llegada). Los turnos empiezan a las horas de la semilla
    turnos (8, 15 y 22, como [turnos].inicio de config/centro.toml).

    La hora del día es k mod 24 y la fecha, la del origen más k div 24 días: aritmética entera,
    sin depender de la zona horaria de la sesión. El turno es el último que ha empezado ese día;
    antes del primero (de 00:00 a 08:00) sigue el último del día anterior, y su fecha es la del
    día anterior: la noche pertenece a la fecha en que empieza.
#}
{% macro turno_de(k, fecha_origen) -%}
    left join lateral (
        select
            t.turno,
            t.inicio as inicio_turno,
            {{ fecha_origen }} + floor({{ k }}::numeric / 24)::int
                - case when t.inicio > mod(mod({{ k }}, 24) + 24, 24) then 1 else 0 end
                as fecha_turno
        from {{ ref('turnos') }} as t
        where {{ k }} is not null
        order by t.inicio <= mod(mod({{ k }}, 24) + 24, 24) desc, t.inicio desc
        limit 1
    ) as del_turno on true
{%- endmacro %}
