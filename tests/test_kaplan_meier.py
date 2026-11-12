"""Kaplan–Meier de la paciencia (tarea 5.7, nota 4 del issue #74).

El estimador puro con los valores a mano del plan, y `patience_survival` con seis pacientes de
nivel real 4 cuya paciencia y cuyos tiempos se escribieron antes que el código:

| paciente | llega | qué pasa                                  | tiempo | paciencia |
| -------- | ----- | ----------------------------------------- | ------ | --------- |
| P1       | 0     | se va a los 30                            | 30 (E) | 30        |
| P2       | 0     | ve al médico a los 20                     | 20 (C) | 500       |
| P3       | 0     | se va a los 50                            | 50 (E) | 40        |
| P4       | 0     | ve al médico a los 70                     | 70 (C) | 500       |
| P5       | 0     | se va a los 90                            | 90 (E) | 90        |
| P6       | 100   | sigue esperando a las 200 (horizonte)     | 100 (C)| 500       |

P3 tenía plazo vencido en el triaje: su paciencia era 40 y se va a los 50 (`late_leavers`).
"""

import math

import pytest
from episode_factory import episode, truth_of

from edsim.runs import kaplan_meier, patience_survival

# --- El estimador puro --------------------------------------------------------------------


def test_los_cuatro_tiempos_del_issue():
    # Tiempos 10 (E), 20 (C), 30 (E), 40 (E).
    # S(10) = 1 − 1/4 = 0,75; en 30 quedan 2: S(30) = 0,75 · (1 − 1/2) = 0,375; en 40 queda 1: 0.
    km = kaplan_meier([10, 20, 30, 40], [True, False, True, True])
    assert km.times == (10.0, 30.0, 40.0)
    assert km.at_risk == (4, 2, 1)
    assert km.events == (1, 1, 1)
    assert km.survival == pytest.approx((0.75, 0.375, 0.0), abs=1e-12)
    assert km.n == 4


def test_antes_del_primer_evento_es_uno_y_es_continua_por_la_derecha():
    km = kaplan_meier([10, 20, 30, 40], [True, False, True, True])
    assert km.at(0) == 1.0 and km.at(9.999) == 1.0
    assert km.at(10) == pytest.approx(0.75, abs=1e-12)  # el escalón ya vale en el propio tiempo
    assert km.at(29.9) == pytest.approx(0.75, abs=1e-12)
    assert km.at(30) == pytest.approx(0.375, abs=1e-12)
    assert km.at(1e9) == 0.0


def test_el_evento_va_antes_que_la_censura_del_mismo_tiempo():
    # Tiempos [10, 20, 20, 30], observados [sí, sí, no, sí].
    # S(10) = 0,75; en 20 siguen en riesgo 3 (el evento, el censurado y el de 30) con 1 evento:
    # S(20) = 0,75 · (1 − 1/3) = 0,5; en 30 queda 1: S(30) = 0. Si el censurado fuera antes habría
    # 2 en riesgo en 20 y saldría 0,75 · 1/2 = 0,375.
    km = kaplan_meier([10, 20, 20, 30], [True, True, False, True])
    assert km.at_risk == (4, 3, 1)
    assert km.survival == pytest.approx((0.75, 0.5, 0.0), abs=1e-12)


def test_si_el_ultimo_tiempo_es_una_censura_la_curva_no_baja_mas():
    # [10, 20], [sí, no]: S(10) = 1 − 1/2 = 0,5; el censurado en 20 no la cambia.
    km = kaplan_meier([10, 20], [True, False])
    assert km.at(20) == 0.5 and km.at(25) == 0.5 and km.at(1e6) == 0.5
    # Por encima del mayor tiempo observado no queda nadie en riesgo: el KM no estima nada ahí.
    assert km.at_risk_at(20) == 1  # el censurado en 20 aún cuenta en 20
    assert km.at_risk_at(25) == 0
    assert km.at_risk_at(0) == 2 and km.at_risk_at(10) == 2 and km.at_risk_at(10.5) == 1


def test_sin_eventos_la_supervivencia_es_uno():
    km = kaplan_meier([5, 7, 9], [False, False, False])
    assert km.times == () and km.at(100) == 1.0 and km.at_risk_at(6) == 2


def test_sin_observaciones():
    km = kaplan_meier([], [])
    assert (km.n, km.times) == (0, ()) and km.at(5) == 1.0 and km.at_risk_at(0) == 0


def test_el_orden_de_entrada_no_importa():
    a = kaplan_meier([40, 10, 30, 20], [True, True, True, False])
    b = kaplan_meier([10, 20, 30, 40], [True, False, True, True])
    assert a == b


def test_un_tiempo_enorme_es_valido():
    km = kaplan_meier([1e300, 5.0], [True, True])
    assert km.survival == pytest.approx((0.5, 0.0), abs=1e-12)


def test_un_millon_de_observaciones_y_recuentos_enteros():
    n = 1_000_000
    times = [float(i % 1000) for i in range(n)]
    km = kaplan_meier(times, [True] * n)
    assert km.n == n and km.at_risk[0] == n and isinstance(km.at_risk[0], int)
    assert sum(km.events) == n and km.survival[-1] == 0.0


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, -1.0])
def test_tiempos_no_validos(bad):
    with pytest.raises(ValueError, match="finite"):
        kaplan_meier([1.0, bad], [True, True])


def test_listas_de_distinta_longitud():
    with pytest.raises(ValueError, match="same length"):
        kaplan_meier([1.0, 2.0], [True])


@pytest.mark.parametrize("bad", [math.nan, math.inf])
def test_consultar_en_un_tiempo_no_finito(bad):
    km = kaplan_meier([1.0], [True])
    with pytest.raises(ValueError, match="finite"):
        km.at(bad)
    with pytest.raises(ValueError, match="finite"):
        km.at_risk_at(bad)


# --- patience_survival, con seis pacientes a mano -----------------------------------------


def six():
    table = [
        episode(1, 0.0, left=30.0),
        episode(2, 0.0, assessment=20.0, departure=60.0),
        episode(3, 0.0, left=50.0),
        episode(4, 0.0, assessment=70.0, departure=100.0),
        episode(5, 0.0, left=90.0),
        episode(6, 100.0),
    ]
    patience = {1: 30.0, 2: 500.0, 3: 40.0, 4: 500.0, 5: 90.0, 6: 500.0}
    truth = {f"EP-{i:06d}": truth_of(p) for i, p in patience.items()}
    return table, truth


def test_los_seis_pacientes_a_mano():
    table, truth = six()
    result = patience_survival(table, truth, 0.0, 200.0, 200.0, "true_level")
    group = result.groups[3]  # nivel 4
    # Ordenados: 20C, 30E, 50E, 70C, 90E, 100C.
    # S(30) = 4/5 = 0,8; S(50) = 0,8 · 3/4 = 0,6; S(90) = 0,6 · 1/2 = 0,3 (en 90 quedan 2).
    assert group.km.times == (30.0, 50.0, 90.0)
    assert group.km.at_risk == (5, 4, 2)
    assert group.km.survival == pytest.approx((0.8, 0.6, 0.3), abs=1e-12)
    assert (group.left, group.seen, group.waiting) == (3, 2, 1)
    assert group.n == 6 and result.unclassified == 0
    # Los demás niveles están vacíos.
    assert all(g.n == 0 and g.km.at(10) == 1.0 for i, g in enumerate(result.groups) if i != 3)


def test_quien_tenia_el_plazo_vencido_en_el_triaje_es_un_late_leaver():
    table, truth = six()
    group = patience_survival(table, truth, 0.0, 200.0, 200.0, "true_level").groups[3]
    # P3 tenía paciencia 40 y se va a los 50 (50 > 40); P1 y P5 se van justo en su paciencia.
    assert group.late_leavers == 1


def test_la_verdad_son_las_paciencias_de_todos():
    table, truth = six()
    group = patience_survival(table, truth, 0.0, 200.0, 200.0, "true_level").groups[3]
    assert group.patiences == (30.0, 40.0, 90.0, 500.0, 500.0, 500.0)
    # Más de 30: 5 de 6; más de 40: 4 de 6; más de 90: 3 de 6; más de 500: ninguno.
    assert group.truth_survival(30.0) == pytest.approx(5 / 6, abs=1e-12)
    assert group.truth_survival(40.0) == pytest.approx(4 / 6, abs=1e-12)
    assert group.truth_survival(90.0) == pytest.approx(0.5, abs=1e-12)
    assert group.truth_survival(500.0) == 0.0
    assert group.truth_survival(0.0) == 1.0
    empty = patience_survival(table, truth, 0.0, 200.0, 200.0, "true_level").groups[0]
    assert empty.truth_survival(10.0) is None


def test_el_horizonte_censura_a_quien_sigue_esperando():
    table, truth = six()
    # Con el horizonte en 150, P6 (llegó en 100) lleva 50 y se censura ahí.
    group = patience_survival(table, truth, 0.0, 150.0, 150.0, "true_level").groups[3]
    assert group.waiting == 1 and 50.0 in group.km.observed


def test_por_nivel_asignado_quien_se_va_antes_del_triaje_queda_fuera():
    table, truth = six()
    # P1 se va antes de su triaje: sin nivel asignado.
    table[0] = episode(1, 0.0, left=30.0, level=None)
    result = patience_survival(table, truth, 0.0, 200.0, 200.0, "assigned_level")
    assert result.unclassified == 1
    group = result.groups[3]
    # Sin P1: 20C, 50E, 70C, 90E, 100C. S(50) = 1 − 1/4 = 0,75; S(90) = 0,75 · 1/2 = 0,375.
    assert group.km.survival == pytest.approx((0.75, 0.375), abs=1e-12)
    assert group.n == 5
    # Por nivel real, en cambio, P1 sí está.
    assert patience_survival(table, truth, 0.0, 200.0, 200.0, "true_level").groups[3].n == 6


def test_el_nivel_real_y_el_asignado_pueden_repartir_distinto():
    table, truth = six()
    truth["EP-000002"] = truth_of(500.0, true_level=2)  # el P2 es en verdad un nivel 2
    result = patience_survival(table, truth, 0.0, 200.0, 200.0, "true_level")
    assert result.groups[1].n == 1 and result.groups[3].n == 5
    assert patience_survival(table, truth, 0.0, 200.0, 200.0, "assigned_level").groups[3].n == 6


def test_la_ventana_incluye_el_inicio_y_excluye_el_final():
    table, truth = six()
    # Ventana [100, 200): solo P6, que llegó justo en el inicio.
    only = patience_survival(table, truth, 100.0, 200.0, 200.0, "true_level").groups[3]
    assert only.n == 1 and only.waiting == 1
    # Ventana [0, 100): P6, llegado justo en el final, queda fuera.
    assert patience_survival(table, truth, 0.0, 100.0, 200.0, "true_level").groups[3].n == 5


def test_errores():
    table, truth = six()
    with pytest.raises(ValueError, match="by must be"):
        patience_survival(table, truth, 0.0, 1000.0, 1000.0, "nivel")
    with pytest.raises(ValueError, match="start"):
        patience_survival(table, truth, 0.0, 2000.0, 1000.0, "true_level")
    with pytest.raises(ValueError, match="not in the ground truth"):
        patience_survival(table, {}, 0.0, 1000.0, 1000.0, "true_level")
    # Salió sin ser visto ni irse: el log está mal.
    bad = [episode(1, 0.0, departure=50.0)]
    with pytest.raises(ValueError, match="without being seen"):
        patience_survival(bad, {"EP-000001": truth_of(10.0)}, 0.0, 1000.0, 1000.0, "true_level")
