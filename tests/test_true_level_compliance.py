"""Cumplimiento por nivel real: la regla de Manchester con el nivel del ground truth.

El cumplimiento observable usa el nivel asignado, que es lo que sabe el hospital. Con el
ground truth se puede medir también con el nivel real: la diferencia es el coste del
infratriaje medido en tiempo (docs/specs/hito-4.md, «Relojes y cumplimiento»). Las tablas
de episodios se construyen a mano, como en test_targets; la verdad clínica, con
``hand_truth``.
"""

from collections import Counter
from pathlib import Path

import numpy as np
import pytest
from clinical_factory import hand_truth

from edsim.arrivals.profile import load_profile
from edsim.engine.analysis import EpisodeRecord, completed_in_window, episode_table
from edsim.engine.center import load_center
from edsim.engine.engine import simulate_ed
from edsim.engine.events import MemorySink
from edsim.engine.ground_truth import EpisodeTruth, GroundTruth
from edsim.engine.targets import (
    manchester_compliance,
    true_level_compliance,
    true_level_waits,
    true_levels,
)
from edsim.profiles.config import load_profiles

DAY = 1440.0
CONFIG = Path(__file__).parent.parent / "config"
DATA_H4 = Path(__file__).parent / "data"  # el config/ del hito 4, congelado en la tarea 5.6


def record(n: int, arrival: float, level: int, classified: float) -> EpisodeRecord:
    """Un episodio de nivel asignado ``level`` que ve al médico ``classified`` minutos
    después de clasificarse; sin pretriaje ni triaje, los tres relojes valen lo mismo."""
    return EpisodeRecord(
        episode_id=f"EP-{n:06d}",
        arrival=arrival,
        triage_start=arrival,
        triage_end=arrival,
        level=level,
        first_box=arrival,
        first_assessment=arrival + classified,
        decision=arrival + classified + 20,
        departure=arrival + classified + 20,
        destination="alta",
        displacements=0,
        triage_wait=0.0,
        box_wait=0.0,
        doctor_wait=0.0,
        initial_doctor_wait=0.0,
        door_to_doctor=classified,
        triage_start_to_doctor=classified,
        classified_to_doctor=classified,
        initial_box_wait=0.0,
        results_box_wait=0.0,
    )


def truth(n: int, level: int, true_level: int | None, *, clinical: bool = True) -> EpisodeTruth:
    """La verdad de un episodio con su nivel asignado y su nivel real."""
    return EpisodeTruth(
        episode_id=f"EP-{n:06d}",
        arrival_id=n,
        arrival_time=0.0,
        level=level,
        triage_time=5.0,
        assessment_time=20.0,
        reassessment_time=10.0,
        needs_tests=False,
        test_turnaround=None,
        admitted=False,
        clinical=hand_truth(level=level, true_level=true_level) if clinical else None,
    )


# El día 2, cuatro pacientes, todos con el reloj C que se indica:
# - EP-000001: asignado 3 y real 2 (infratriado), C = 30. Cumple con el nivel asignado
#   (30 ≤ 60) y no con el real (30 > 10).
# - EP-000002: asignado 3 y real 4 (sobretriado), C = 90. No cumple con el asignado
#   (90 > 60) y sí con el real (90 ≤ 120).
# - EP-000003: asignado y real 3, C = 20; EP-000004: asignado y real 2, C = 5.
CASES = ((1, 3, 2, 30.0), (2, 3, 4, 90.0), (3, 3, 3, 20.0), (4, 2, 2, 5.0))
TABLE = tuple(record(n, 2 * DAY + 60 * n, level, c) for n, level, _, c in CASES)
TRUTH = GroundTruth(tuple(truth(n, level, real) for n, level, real, _ in CASES), ())


def test_por_nivel_asignado_el_caso_a_mano():
    # Nivel 2: solo EP-000004, que cumple. Nivel 3: EP-000001, 2 y 3; cumplen 1 y 3 (2/3),
    # por debajo del 90 %: el día está fuera.
    c = manchester_compliance(TABLE, 2, 3)

    assert c.n[0].tolist() == [0, 1, 3, 0, 0]
    assert c.within[0, 1] == 1.0
    assert c.within[0, 2] == pytest.approx(2 / 3)
    assert c.out[0].tolist() == [False, False, True, False, False]


def test_por_nivel_real_el_caso_a_mano():
    # Nivel real 2: EP-000001 (no cumple) y EP-000004 (cumple), 50 %: fuera. Nivel real 3:
    # EP-000003, que cumple. Nivel real 4: EP-000002, que cumple con 120.
    c = true_level_compliance(TABLE, TRUTH, 2, 3)

    assert c.n[0].tolist() == [0, 2, 1, 1, 0]
    assert c.within[0, 1] == 0.5
    assert c.within[0, 2] == 1.0
    assert c.within[0, 3] == 1.0
    assert c.out[0].tolist() == [False, True, False, False, False]
    assert c.measure == "classified_to_doctor"


def test_el_infratriado_cumple_con_el_asignado_y_no_con_el_real():
    infra = (TABLE[0],)
    by_assigned = manchester_compliance(infra, 2, 3)
    by_true = true_level_compliance(infra, TRUTH, 2, 3)

    assert by_assigned.within[0, 2] == 1.0  # nivel asignado 3
    assert by_true.within[0, 1] == 0.0  # nivel real 2


def test_el_sobretriado_no_cumple_con_el_asignado_y_si_con_el_real():
    over = (TABLE[1],)
    by_assigned = manchester_compliance(over, 2, 3)
    by_true = true_level_compliance(over, TRUTH, 2, 3)

    assert by_assigned.within[0, 2] == 0.0  # nivel asignado 3
    assert by_true.within[0, 3] == 1.0  # nivel real 4


def test_bien_clasificados_es_el_cumplimiento_asignado():
    correct = GroundTruth(tuple(truth(n, level, level) for n, level, _, _ in CASES), ())
    for measure in ("door_to_doctor", "classified_to_doctor"):
        a = manchester_compliance(TABLE, 2, 3, measure=measure)
        b = true_level_compliance(TABLE, correct, 2, 3, measure=measure)

        assert a.measure == b.measure
        assert np.array_equal(a.days, b.days)
        assert np.array_equal(a.n, b.n)
        assert np.array_equal(a.within, b.within, equal_nan=True)
        assert np.array_equal(a.out, b.out)
        assert (a.max_wait, a.target) == (b.max_wait, b.target)


def test_otros_maximos_y_otro_objetivo():
    # Con un objetivo del 50 %, el nivel real 2 (50 %) ya no está fuera; con un máximo de
    # 40 min para el nivel 2, el infratriado cumple.
    lax = true_level_compliance(TABLE, TRUTH, 2, 3, target=0.5)
    wide = true_level_compliance(TABLE, TRUTH, 2, 3, max_wait=(0, 40, 60, 120, 240))

    assert not lax.out[0, 1]
    assert wide.within[0, 1] == 1.0


def test_niveles_reales_del_ground_truth():
    assert dict(true_levels(TRUTH)) == {
        "EP-000001": 2,
        "EP-000002": 4,
        "EP-000003": 3,
        "EP-000004": 2,
    }


def test_sin_verdad_clinica_es_un_error():
    provisional = GroundTruth((truth(1, 3, None, clinical=False),), ())

    with pytest.raises(ValueError, match="EP-000001 has no clinical truth"):
        true_levels(provisional)
    with pytest.raises(ValueError, match="no clinical truth"):
        true_level_compliance(TABLE[:1], provisional, 2, 3)


def test_un_episodio_que_falta_en_el_ground_truth_es_un_error():
    partial = GroundTruth(TRUTH.episodes[:3], ())

    with pytest.raises(ValueError, match="EP-000004 is not in the ground truth"):
        true_level_compliance(TABLE, partial, 2, 3)
    with pytest.raises(ValueError, match="EP-000004 is not in the ground truth"):
        true_level_waits(TABLE, partial, "classified_to_doctor", 2, 3)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"measure": "box_wait"}, "measure must be one of"),
        ({"target": 0}, "target must be in"),
        ({"max_wait": (0, 10)}, "max_wait must be 5 values"),
    ],
)
def test_argumentos_no_validos(kwargs, message):
    with pytest.raises(ValueError, match=message):
        true_level_compliance(TABLE, TRUTH, 2, 3, **kwargs)


def test_esperas_con_los_dos_niveles():
    w = true_level_waits(TABLE, TRUTH, "classified_to_doctor", 2, 3)

    assert w.episode_ids == ("EP-000001", "EP-000002", "EP-000003", "EP-000004")
    assert w.assigned.tolist() == [3, 3, 3, 2]
    assert w.true.tolist() == [2, 4, 3, 2]
    assert w.values.tolist() == [30.0, 90.0, 20.0, 5.0]


def test_esperas_emparejadas_por_episodio_y_no_por_posicion():
    # La tabla en otro orden que el ground truth: cada episodio conserva su nivel real.
    w = true_level_waits(TABLE[::-1], TRUTH, "classified_to_doctor", 2, 3)

    assert w.episode_ids == ("EP-000004", "EP-000003", "EP-000002", "EP-000001")
    assert w.true.tolist() == [2, 3, 4, 2]
    assert w.values.tolist() == [5.0, 20.0, 90.0, 30.0]


def test_esperas_medida_desconocida():
    with pytest.raises(ValueError, match="measure must be one of"):
        true_level_waits(TABLE, TRUTH, "espera", 2, 3)


@pytest.fixture(scope="module")
def short_run():
    """Tres días del modelo clínico del hito 4 (sin abandono: el cumplimiento cuenta a los
    completados), con sus copias congeladas: la tabla y el ground truth."""
    sink = MemorySink()
    result = simulate_ed(
        load_center(DATA_H4 / "centro_h4.toml"),
        load_profile(CONFIG / "llegadas.toml"),
        3,
        2026,
        sink=sink,
        warmup_days=1,
        profiles=load_profiles(DATA_H4 / "perfiles_h4.toml"),
    )
    return episode_table(sink.events), result.ground_truth


def test_en_una_ejecucion_cuenta_los_niveles_reales(short_run):
    table, ground_truth = short_run
    done = completed_in_window(table, DAY, 3 * DAY)
    real = true_levels(ground_truth)
    by_true = Counter(real[e.episode_id] for e in done)
    by_assigned = Counter(e.level for e in done)
    c = true_level_compliance(table, ground_truth, 1, 3)

    # El caso ocurre: hay pacientes mal clasificados, y por eso los dos recuentos difieren.
    assert sum(real[e.episode_id] != e.level for e in done) > 0
    assert by_true != by_assigned
    assert c.n.sum(axis=0).tolist() == [by_true[k] for k in range(1, 6)]
    assert c.n.sum(axis=0).tolist() != [by_assigned[k] for k in range(1, 6)]


def test_en_una_ejecucion_las_esperas_llevan_los_dos_niveles(short_run):
    table, ground_truth = short_run
    w = true_level_waits(table, ground_truth, "classified_to_doctor", 1, 3)
    truth_of = {e.episode_id: e for e in ground_truth.episodes}

    assert (w.assigned > w.true).sum() > 0  # hay infratriados
    assert len(w.episode_ids) == len(completed_in_window(table, DAY, 3 * DAY))
    for i, episode_id in enumerate(w.episode_ids):
        assert w.true[i] == truth_of[episode_id].clinical.triage.true_level
        assert w.assigned[i] == truth_of[episode_id].level
