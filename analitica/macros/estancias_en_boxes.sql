{#
    Las estancias en los boxes del maestro que cuentan para oro, con el origen de su ejecución
    (run_id, episode_id, box, entrada, salida, motivo_salida, origen, fecha_origen). Lo usan
    kpi_hora y kpi_turno, para que las dos cuenten las mismas.

    Una estancia sin entrada (un cierre suelto) no cuenta. Una abierta solo cuenta si su
    episodio sigue dentro (oro.cohorte): si su cierre se olvidó (sin_pareja) o se olvidó la
    salida del episodio, el box contaría ocupado para siempre.
#}
{% macro estancias_en_boxes() -%}
    select
        u.run_id,
        u.episode_id,
        u.box,
        u.entrada,
        u.salida,
        u.motivo_salida,
        p.origen,
        p.fecha_origen
    from {{ ref('ubicacion') }} as u
    join {{ ref('maestro_boxes') }} as b using (box)
    join {{ ref('parametros') }} as p using (run_id)
    left join {{ ref('cohorte') }} as c using (run_id, episode_id)
    where u.entrada is not null
        and (
            u.salida is not null
            or (not u.sin_pareja and coalesce(c.sigue_dentro, false))
        )
{%- endmacro %}
