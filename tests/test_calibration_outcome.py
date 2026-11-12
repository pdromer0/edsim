"""La calibración con abandono, destinos y espera de cama (tarea 5.6).

Quién cuenta en cada objetivo con las reglas de la 5.4 (H5-8): el pretriaje es de los
triados, las medias de los relojes son de los atendidos, los porcentajes de los relojes
llevan la censura del cumplimiento, la estancia lleva a quien sigue dentro con su cota y el
abandono va sobre todas las llegadas. Los valores esperados están calculados a mano en el
plan de la tarea (sección 2), paciente a paciente.
"""

import math
from pathlib import Path

import pytest

from edsim.arrivals.profile import load_profile
from edsim.calibration.evaluate import (
    DRAIN_DAYS,
    clinical_run,
    replica_table,
    replica_values,
    simulate_replicas,
    split_targets,
)
from edsim.calibration.targets import (
    ARRIVALS_PERCENTAGE,
    CHECK,
    FIT,
    MANCHESTER,
    MEAN,
    PERCENTAGE,
    Target,
)
from edsim.engine.analysis import EpisodeRecord
from edsim.engine.center import load_center
from edsim.engine.outcome_metrics import (
    destination_shares,
    left_without_being_seen_shares,
    stay_by_destination,
)
from edsim.profiles.config import load_profiles

DATA = Path(__file__).resolve().parent / "data"
DAY = 1440.0
HORIZON = 2 * DAY  # la ventana [0, 1) día más el día de vaciado


def target(name, measure, statistic=MEAN, *, levels=(1, 2, 3, 4, 5), **kwargs) -> Target:
    """Un objetivo con fuente de relleno y una horquilla ancha: aquí importa su valor."""
    return Target(
        name=name,
        measure=measure,
        levels=() if statistic == ARRIVALS_PERCENTAGE else levels,
        statistic=statistic,
        threshold=kwargs.pop("threshold", None),
        band=kwargs.pop("band", (0, 100) if statistic != MEAN else (0, 5000)),
        use=kwargs.pop("use", FIT),
        source="a mano",
        link="https://example.org",
        **kwargs,
    )


def episode(episode_id, arrival, triage_start, level, **fields) -> EpisodeRecord:
    """Un episodio a mano, triado 5 minutos después de empezar el triaje.

    Lo que no se da vale None (no ha pasado) salvo los recuentos y las esperas acumuladas,
    que valen 0; el pretriaje sale de la llegada y del inicio del triaje.
    """
    defaults = {
        "first_box": None,
        "first_assessment": None,
        "decision": None,
        "departure": None,
        "destination": None,
        "displacements": 0,
        "box_wait": 0.0,
        "doctor_wait": 0.0,
        "initial_doctor_wait": None,
        "door_to_doctor": None,
        "triage_start_to_doctor": None,
        "classified_to_doctor": None,
        "initial_box_wait": None,
        "results_box_wait": 0.0,
    }
    return EpisodeRecord(
        episode_id=episode_id,
        arrival=arrival,
        triage_start=triage_start,
        triage_end=triage_start + 5,
        level=level,
        triage_wait=triage_start - arrival,
        **(defaults | fields),
    )


def seen(arrival, triage_start, assessment):
    """Los tres relojes de quien ve al médico en ``assessment``."""
    return {
        "first_assessment": assessment,
        "door_to_doctor": assessment - arrival,
        "triage_start_to_doctor": assessment - triage_start,
        "classified_to_doctor": assessment - (triage_start + 5),
    }


# Los ocho pacientes de la sección 2 del plan, en la ventana [0, 1) y con horizonte 2880.
A = episode(
    "A", 0, 2, 3, departure=100, destination="alta", initial_box_wait=10, initial_doctor_wait=13,
    **seen(0, 2, 30),
)  # fmt: skip
B = episode(
    "B", 10, 14, 2, departure=510, destination="ingreso", bed_requested=60,
    bed_assigned=510, bed_wait=450, initial_box_wait=1, initial_doctor_wait=0,
    **seen(10, 14, 20),
)  # fmt: skip
C = episode("C", 20, 25, 4, left=150, left_from="medico")
D = episode("D", 30, 31, 4)
E = episode(
    "E", 40, 43, 3, decision=90, bed_requested=90, initial_box_wait=2, initial_doctor_wait=10,
    **seen(40, 43, 60),
)  # fmt: skip
F = episode("F", 50, 60, 4, left=170, left_from="medico")
G = episode("G", 60, 66, 4, left=110, left_from="medico")
H = episode(
    "H", 70, 77, 4, departure=270, destination="alta", initial_box_wait=40, initial_doctor_wait=48,
    **seen(70, 77, 170),
)  # fmt: skip
TABLE = (A, B, C, D, E, F, G, H)

PRETRIAJE = target("pretriaje_medio", "triage_wait", levels=(2, 3, 4, 5))
PRETRIAJE_MAS_5 = target(
    "porcentaje_pretriaje_mas_5", "triage_wait", PERCENTAGE, levels=(2, 3, 4, 5), threshold=5
)
ABANDONO = target("abandono", "left", ARRIVALS_PERCENTAGE)
INGRESO_OBSERVADO = target(
    "ingreso_observado", "departure", ARRIVALS_PERCENTAGE, destination="ingreso"
)
ESTANCIA_INGRESADOS = target("estancia_ingresados", "stay", destination="ingreso")
INGRESADOS_MAS_4H = target(
    "ingresados_mas_4h", "stay", PERCENTAGE, threshold=240, destination="ingreso", use=CHECK
)
ESTANCIA_ATENDIDOS = target("estancia_atendidos", "stay", use=CHECK)
MANCHESTER_4 = target(
    "sobre_manchester_4", "door_to_doctor", PERCENTAGE, levels=(4,), threshold=MANCHESTER
)
RELOJ_A_4 = target("reloj_a_4", "door_to_doctor", levels=(4,))
TARGETS = (
    PRETRIAJE,
    PRETRIAJE_MAS_5,
    ABANDONO,
    INGRESO_OBSERVADO,
    ESTANCIA_INGRESADOS,
    INGRESADOS_MAS_4H,
    ESTANCIA_ATENDIDOS,
    MANCHESTER_4,
    RELOJ_A_4,
)


@pytest.fixture(scope="module")
def values():
    return replica_values(TABLE, TARGETS, 0, 1)


def test_el_horizonte_por_defecto_es_el_del_dia_de_vaciado():
    assert DRAIN_DAYS == 1
    explicit = replica_values(TABLE, TARGETS, 0, 1, horizon=HORIZON)
    assert explicit == replica_values(TABLE, TARGETS, 0, 1)


def test_el_pretriaje_es_de_los_triados_que_terminan(values):
    # A 2, B 4, C 5, F 10, G 6 y H 7: también los que se van después del triaje. D y E
    # siguen dentro y no cuentan. 34 / 6 = 5,667; solo con los atendidos (A, B, H) sería
    # 13 / 3 = 4,333.
    v = values.targets["pretriaje_medio"]
    assert v.value == pytest.approx(34 / 6)
    assert v.n_by_level == (1, 1, 4, 0)  # niveles 2 (B), 3 (A), 4 (C, F, G, H) y 5
    assert v.bounded == 0


def test_el_porcentaje_de_pretriaje_de_mas_de_5_minutos(values):
    # F (10), G (6) y H (7) por encima de los seis triados; C, con 5 justos, no.
    v = values.targets["porcentaje_pretriaje_mas_5"]
    assert v.value == pytest.approx(50.0)
    assert (sum(v.n_by_level), sum(v.over_by_level)) == (6, 3)


def test_el_abandono_va_sobre_todas_las_llegadas(values):
    # C, F y G sobre las ocho llegadas: 37,5 %. Sobre los atendidos (A, B, H) sería 100 %.
    v = values.targets["abandono"]
    assert v.value == pytest.approx(37.5)
    assert (v.n_by_level, v.over_by_level) == ((8,), (3,))


def test_el_ingreso_observado_va_sobre_todas_las_llegadas(values):
    # Solo B ha salido ingresada; E espera cama y no ha salido: 1 / 8.
    v = values.targets["ingreso_observado"]
    assert v.value == pytest.approx(12.5)
    assert (v.n_by_level, v.over_by_level) == ((8,), (1,))


def test_la_estancia_de_los_ingresados_lleva_al_que_espera_cama_con_su_cota(values):
    # B sale en 510 (estancia 500); E sigue esperando cama: cota 2880 − 40 = 2840.
    # (500 + 2840) / 2 = 1670, una cota («≥»). Sin E sería 500.
    v = values.targets["estancia_ingresados"]
    assert v.value == pytest.approx(1670.0)
    assert v.bounded == 1
    assert sum(v.n_by_level) == 2


def test_los_ingresados_de_mas_de_4_horas_con_la_cota(values):
    # 500 > 240 y la cota 2840 ya pasa de 240: los dos por encima.
    v = values.targets["ingresados_mas_4h"]
    assert v.value == pytest.approx(100.0)
    assert (sum(v.n_by_level), sum(v.over_by_level)) == (2, 2)


def test_la_estancia_de_los_atendidos(values):
    # A 100, B 500, H 200 y E con su cota 2840: 3640 / 4 = 910 «≥». D no ha visto al
    # médico y no cuenta.
    v = values.targets["estancia_atendidos"]
    assert v.value == pytest.approx(910.0)
    assert v.bounded == 1


def test_el_porcentaje_sobre_manchester_con_la_censura_de_los_que_se_van(values):
    # Nivel 4, máximo 120 con el reloj A. H, visto en 100: dentro. C se va con 130: por
    # encima seguro. F se va justo con 120: no fue visto en 120, así que también. G se va
    # con 50: censurado, no cuenta. 2 / 3; quitando a los que se van, 0 / 1.
    v = values.targets["sobre_manchester_4"]
    assert v.value == pytest.approx(200 / 3)
    assert (v.n_by_level, v.over_by_level) == ((3,), (2,))


def test_la_media_del_reloj_es_de_los_atendidos(values):
    # Del nivel 4 solo H ha visto al médico y ha salido: 100.
    assert values.targets["reloj_a_4"].value == pytest.approx(100.0)


def test_recuentos_de_la_replica(values):
    assert values.arrivals == 8
    # Censurados: los que siguen dentro (D y E), no los que no tienen salida (serían 5).
    assert values.censored == 2
    assert values.left == 3
    assert values.censored_seen == 1  # E
    assert (values.admitted, values.censored_admitted) == (2, 1)  # B y E; E sigue esperando
    assert values.censored_admitted_share == pytest.approx(0.5)


def test_esperando_cama_por_la_ley_de_little(values):
    # B espera cama 450 min (de 60 a 510); E sigue esperando: cota 2880 − 90 = 2790. Con la
    # ventana de un día, L = Σ W / T = (450 + 2790) / 1440 = 2,25.
    assert values.bed_wait_minutes == pytest.approx(3240.0)
    assert values.window_minutes == DAY
    assert values.boxes_waiting_bed == pytest.approx(2.25)


def test_cuello_de_botella_con_los_atendidos_de_los_niveles_2_a_5(values):
    # A, B y H: box (10 + 1 + 40) / 3 = 17; médico (13 + 0 + 48) / 3 = 20,333.
    assert values.box_wait == pytest.approx(17.0)
    assert values.doctor_wait == pytest.approx(61 / 3)


def test_los_dias_por_llegada():
    # Un paciente del día 1 con la ventana [0, 2): cada día con los suyos.
    later = episode("I", DAY + 10, DAY + 12, 4, left=DAY + 100, left_from="box")
    v = replica_values((*TABLE, later), (ABANDONO,), 0, 2).targets["abandono"]
    assert v.daily == pytest.approx((37.5, 100.0))
    assert v.value == pytest.approx(400 / 9)


def test_un_porcentaje_de_una_medida_sin_reloj_para_quien_se_va_es_un_error():
    box = target("box", "box_wait", PERCENTAGE, levels=(4,), threshold=30)
    with pytest.raises(ValueError, match="objetivos.box: the measure 'box_wait' has no clock"):
        replica_values(TABLE, (box,), 0, 1)


def test_sin_pacientes_la_estancia_de_los_ingresados_es_nan():
    v = replica_values((A, C), (ESTANCIA_INGRESADOS,), 0, 1).targets["estancia_ingresados"]
    assert math.isnan(v.value) and v.n_by_level == (0, 0, 0, 0, 0)


# --- Con el motor: la regla, frente a los indicadores de la 5.4 ------------------------------


@pytest.fixture(scope="module")
def h5():
    return (
        load_center(DATA / "centro_h5_ejemplo.toml"),
        load_profile(DATA / "llegadas_ejemplo.toml"),
        load_profiles(DATA / "perfiles_h5_ejemplo.toml"),
    )


def test_con_el_motor_coincide_con_los_indicadores_del_desenlace(h5):
    # Dos implementaciones distintas de la misma regla: los indicadores de la 5.4
    # (engine/outcome_metrics.py) y la reducción de la calibración, en una réplica de 3
    # días con 1 de calentamiento y el de vaciado.
    center, profile, profiles = h5
    run = clinical_run(center, profile, profiles, 2026, 1)
    table = replica_table(run, 3, 1)
    horizon = (3 + DRAIN_DAYS) * DAY
    start, end = DAY, 3 * DAY
    v = replica_values(table, TARGETS, 1, 3).targets

    left = left_without_being_seen_shares(table, start, end)
    assert left.left > 0
    assert v["abandono"].value == pytest.approx(100 * left.share)
    destinations = destination_shares(table, start, end)
    assert v["ingreso_observado"].value == pytest.approx(100 * destinations.share("ingreso"))
    stay = stay_by_destination(table, start, end, horizon)
    admitted = stay.by_destination["ingreso"]
    assert v["estancia_ingresados"].value == pytest.approx(admitted.mean.value)
    assert v["estancia_ingresados"].bounded == admitted.censored
    assert v["ingresados_mas_4h"].value == pytest.approx(100 * stay.admitted_over.share)


def test_los_objetivos_del_hito_5_no_aplican_al_hito_4(h5):
    h4 = (
        load_center(DATA / "centro_sala_ejemplo.toml"),
        load_profiles(DATA / "perfiles_ejemplo.toml"),
    )
    applies, out = split_targets(TARGETS, *h4)
    assert [t.name for t in out] == [
        "abandono",
        "ingreso_observado",
        "estancia_ingresados",
        "ingresados_mas_4h",
    ]
    # La estancia de todos y los relojes existen en el hito 4.
    assert "estancia_atendidos" in {t.name for t in applies}
    center, _, profiles = h5
    assert split_targets(TARGETS, center, profiles) == (TARGETS, ())


def test_simular_un_objetivo_que_no_aplica_es_un_error_antes_de_simular(monkeypatch, h5):
    monkeypatch.setattr(
        "edsim.calibration.evaluate.simulate_ed", lambda *a, **k: pytest.fail("simuló")
    )
    _, profile, _ = h5
    with pytest.raises(ValueError, match="objetivos.abandono: only the milestone 5 model"):
        simulate_replicas(
            load_center(DATA / "centro_sala_ejemplo.toml"),
            profile,
            load_profiles(DATA / "perfiles_ejemplo.toml"),
            (PRETRIAJE, ABANDONO),
            replicas=2,
            days=2,
            warmup_days=1,
            seed=2026,
        )
