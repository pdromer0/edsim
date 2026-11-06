"""Evaluación de la calibración: réplicas, horquillas, días fuera y vaciado (tarea 4.6b)."""

import dataclasses
import math
from datetime import date
from pathlib import Path
from types import MappingProxyType

import pytest

from edsim.arrivals.profile import load_profile
from edsim.arrivals.thinning import ArrivalRecord
from edsim.calibration import evaluate
from edsim.calibration.evaluate import (
    CHECK_SEED,
    DRAIN_DAYS,
    FIT_SEED,
    ReplicaValues,
    TargetValues,
    clinical_run,
    evaluate_targets,
    level_breakdown,
    replica_table,
    replica_values,
    simulate_replicas,
    summarize_targets,
)
from edsim.calibration.targets import FIT, MANCHESTER, PERCENTAGE, Target
from edsim.engine.analysis import EpisodeRecord, episode_table
from edsim.engine.center import load_center
from edsim.engine.clinical import PatientDraws
from edsim.engine.engine import run_engine
from edsim.engine.events import EventLog, MemorySink
from edsim.engine.targets import manchester_compliance
from edsim.profiles.config import load_profiles

DATA = Path(__file__).resolve().parent / "data"
DAY = 1440.0


def target(name="t", measure="triage_wait", levels=(2, 3, 4, 5), band=(6, 15), **kwargs):
    """Un objetivo de ajuste con fuente de relleno."""
    return Target(
        name=name,
        measure=measure,
        levels=levels,
        statistic=kwargs.pop("statistic", "media"),
        threshold=kwargs.pop("threshold", None),
        band=band,
        use=FIT,
        source="a mano",
        link="https://example.org",
        **kwargs,
    )


def record(episode_id, arrival, level, *, departure=None, **measures) -> EpisodeRecord:
    """Un episodio a mano: las medidas que no se dan valen 0 si salió y None si no."""
    default = 0.0 if departure is not None else None
    fields = {
        "triage_wait": default,
        "box_wait": default,
        "doctor_wait": default,
        "initial_doctor_wait": default,
        "door_to_doctor": default,
        "triage_start_to_doctor": default,
        "classified_to_doctor": default,
        "initial_box_wait": default,
        "results_box_wait": default,
        **measures,
    }
    return EpisodeRecord(
        episode_id=episode_id,
        arrival=arrival,
        triage_start=None,
        triage_end=None,
        level=level,
        first_box=None,
        first_assessment=None,
        decision=None,
        departure=departure,
        destination=None,
        displacements=0,
        **fields,
    )


def replica(name, value, daily=(), n=(), over=()) -> ReplicaValues:
    """Una réplica reducida a mano, con un solo objetivo."""
    values = TargetValues(value, tuple(daily), tuple(n), tuple(over))
    return ReplicaValues(MappingProxyType({name: values}), 100, 0, (0,) * 5, (0,) * 5)


# --- Regla 4: la media y el IC -----------------------------------------------------------


def test_ic_a_mano_con_tres_replicas_no_pasa_aunque_la_media_cae_dentro():
    # 10, 12 y 14: media 12, s = 2, t₂ = 4,303 → IC 12 ± 4,303 · 2 / √3 = [7,03; 16,97].
    # Anchura 9,94 > 9, la de [6, 15]: no pasa, aunque la media cae dentro.
    pretriage = target("pretriaje")
    (result,) = summarize_targets([replica("pretriaje", v, [v]) for v in (10, 12, 14)], [pretriage])

    assert result.mean == pytest.approx(12)
    assert result.summary.std == pytest.approx(2)
    assert result.summary.ci_low == pytest.approx(7.031, abs=1e-3)
    assert result.summary.ci_high == pytest.approx(16.969, abs=1e-3)
    assert result.ci_width == pytest.approx(9.937, abs=1e-3)
    assert result.within and not result.narrow
    assert not result.passed


def test_ic_con_diez_replicas_usa_la_t_de_student():
    # Valores 1 a 10: s = 3,0277; semiancho t₉ · s / √10 con t₉ = 2,262.
    values = [float(v) for v in range(1, 11)]
    (result,) = summarize_targets([replica("t", v, [v]) for v in values], [target(band=(0, 20))])
    half = (result.summary.ci_high - result.summary.ci_low) / 2
    assert half == pytest.approx(2.262 * 3.0277 / math.sqrt(10), abs=1e-3)
    assert result.passed


def test_pasa_con_la_media_dentro_y_el_ic_estrecho_y_falla_con_la_media_fuera():
    inside, outside = target("a"), target("b")
    reps = [
        ReplicaValues(
            MappingProxyType(
                {
                    "a": TargetValues(v, (v,), (), ()),
                    "b": TargetValues(v + 10, (v + 10,), (), ()),
                }
            ),
            100,
            0,
            (0,) * 5,
            (0,) * 5,
        )
        for v in (10.0, 10.5, 11.0)
    ]
    a, b = summarize_targets(reps, [inside, outside])
    assert a.passed and a.narrow and a.within
    assert not b.passed and b.narrow and not b.within


def test_menos_de_dos_replicas_o_sin_pacientes_es_un_error():
    with pytest.raises(ValueError, match="replications"):
        summarize_targets([replica("t", 10, [10])], [target()])
    with pytest.raises(ValueError, match="objetivos.t: some replication has no patients"):
        summarize_targets([replica("t", 10, [10]), replica("t", math.nan, [])], [target()])


# --- Días fuera ---------------------------------------------------------------------------


def test_dias_fuera_a_mano():
    # Una réplica con medias diarias 5, 8, 16 y 10 frente a [6, 15]: 2 de 4, el 50 %.
    # La otra, todo dentro (0 %): la media entre réplicas es el 25 %. Un día sin
    # pacientes (nan) no cuenta.
    reps = [replica("t", 9.75, [5, 8, 16, 10]), replica("t", 9, [9, math.nan, 9])]
    (result,) = summarize_targets(reps, [target()])
    assert result.days_out == (0.5, 0.0)
    assert result.share_days_out == 0.25


def test_borde_de_la_horquilla_esta_dentro():
    (result,) = summarize_targets([replica("t", 6, [6, 15]), replica("t", 15, [15])], [target()])
    assert result.days_out == (0.0, 0.0)


# --- Una réplica, a partir de los episodios ------------------------------------------------


def test_media_diaria_por_paciente_y_no_media_de_las_medias_por_nivel():
    # Día 1: un nivel 2 con 10 minutos y dos niveles 3 con 1. Por paciente: 12 / 3 = 4;
    # la media de las medias por nivel daría (10 + 1) / 2 = 5,5. Día 2: un nivel 4 con 7.
    table = [
        record("EP-1", DAY + 10, 2, departure=DAY + 100, triage_wait=10.0),
        record("EP-2", DAY + 20, 3, departure=DAY + 100, triage_wait=1.0),
        record("EP-3", DAY + 30, 3, departure=DAY + 100, triage_wait=1.0),
        record("EP-4", 2 * DAY + 5, 4, departure=2 * DAY + 50, triage_wait=7.0),
    ]
    values = replica_values(table, [target()], 1, 3).targets["t"]
    assert values.daily == (4.0, 7.0)
    assert values.value == pytest.approx(19 / 4)
    assert values.n_by_level == (1, 2, 1, 0)


def test_la_ventana_deja_fuera_el_calentamiento_y_el_dia_de_vaciado():
    # Calentamiento de 1 día y ventana [1, 2): cuentan las llegadas del día 1, no las del
    # día 0 ni las del día de vaciado (día 2), aunque hayan salido.
    table = [
        record("EP-1", 100.0, 3, departure=200.0, triage_wait=50.0),
        record("EP-2", DAY + 100, 3, departure=DAY + 200, triage_wait=8.0),
        record("EP-3", 2 * DAY + 100, 3, departure=2 * DAY + 200, triage_wait=90.0),
    ]
    values = replica_values(table, [target()], 1, 2)
    assert values.targets["t"].value == 8.0
    assert values.arrivals == 1


def test_niveles_del_objetivo():
    table = [
        record("EP-1", 10.0, 1, departure=50.0, triage_wait=0.0),
        record("EP-2", 20.0, 3, departure=90.0, triage_wait=6.0),
        record("EP-3", 30.0, 4, departure=90.0, triage_wait=10.0),
    ]
    assert replica_values(table, [target(levels=(3,))], 0, 1).targets["t"].value == 6.0
    assert replica_values(table, [target(levels=(2, 3, 4, 5))], 0, 1).targets["t"].value == 8.0


def test_porcentaje_sobre_manchester_en_el_borde():
    # Nivel 3, máximo 60: con 60 justos cumple (no cuenta); con 60,5, por encima.
    # Nivel 2, máximo 10: con 16 está por encima. 2 de 3 por encima: 66,7 %.
    over = target(
        "sobre",
        measure="door_to_doctor",
        band=(10, 30),
        statistic=PERCENTAGE,
        threshold=MANCHESTER,
    )
    table = [
        record("EP-1", 10.0, 3, departure=500.0, door_to_doctor=60.0),
        record("EP-2", 20.0, 3, departure=500.0, door_to_doctor=60.5),
        record("EP-3", 30.0, 2, departure=500.0, door_to_doctor=16.0),
    ]
    values = replica_values(table, [over], 0, 1).targets["sobre"]
    assert values.value == pytest.approx(200 / 3)
    assert values.n_by_level == (1, 2, 0, 0)
    assert values.over_by_level == (1, 1, 0, 0)


def test_porcentaje_con_umbral_en_minutos():
    long_wait = target("largo", band=(30, 60), statistic=PERCENTAGE, threshold=5)
    table = [
        record("EP-1", 10.0, 3, departure=500.0, triage_wait=5.0),
        record("EP-2", 20.0, 4, departure=500.0, triage_wait=5.01),
    ]
    assert replica_values(table, [long_wait], 0, 1).targets["largo"].value == 50.0


def test_censurados_contados_por_replica():
    # Dos llegados en la ventana; uno sigue dentro al final del horizonte.
    table = [
        record("EP-1", 10.0, 3, departure=500.0, triage_wait=4.0),
        record("EP-2", 20.0, 3),
    ]
    values = replica_values(table, [target()], 0, 1)
    assert (values.arrivals, values.censored) == (2, 1)
    assert values.censored_share == 0.5
    assert values.targets["t"].value == 4.0


def test_cumplimiento_del_cumplidor_con_el_reloj_c():
    # Nivel 2 (máximo 10): reloj A de 20, pero C de 5. Con C cumple: 0 días fuera.
    table = [
        record("EP-1", 10.0, 2, departure=500.0, door_to_doctor=20.0, classified_to_doctor=5.0)
    ]
    values = replica_values(table, [target()], 0, 1)
    assert values.compliance_days_out[1] == 0 and values.compliance_days[1] == 1
    assert values.compliance_days[2] == 0  # sin pacientes de nivel 3
    out = values.compliance_out
    assert out[1] == 0.0
    assert math.isnan(out[2])


def test_dias_fuera_enteros_y_su_proporcion_como_manchester_compliance(example):
    # La proporción de días fuera que se guardaba antes (Compliance.share_out) es la de los
    # días enteros, bit a bit.
    center, profile, profiles = example
    run = clinical_run(center, profile, profiles, 7, 1)
    table = replica_table(run, days=4, warmup_days=1)
    values = replica_values(table, [target()], 1, 4)
    compliance = manchester_compliance(table, 1, 4)
    assert values.compliance_days_out == tuple(int(x) for x in compliance.out.sum(axis=0))
    assert values.compliance_days == tuple(int(x) for x in compliance.days_with_patients)
    assert repr(values.compliance_out) == repr(tuple(float(x) for x in compliance.share_out))


def test_la_evaluacion_es_una_funcion_pura():
    table = (
        record("EP-1", 10.0, 3, departure=500.0, triage_wait=4.0, door_to_doctor=30.0),
        record("EP-2", DAY + 20, 2, departure=DAY + 500, triage_wait=9.0, door_to_doctor=40.0),
        record("EP-3", DAY + 30, 4),
    )
    targets = [target(), target("a", measure="door_to_doctor", band=(35, 70))]
    copy = tuple(dataclasses.replace(e) for e in table)

    first = evaluate_targets([table, table[:2]], targets, 0, 2)
    second = evaluate_targets([table, table[:2]], targets, 0, 2)

    # repr y no ==: los niveles sin pacientes dan nan, y nan != nan.
    assert repr(first) == repr(second)
    assert repr(replica_values(table, targets, 0, 2)) == repr(replica_values(table, targets, 0, 2))
    assert table == copy


# --- Desglose por nivel ------------------------------------------------------------------


def test_desglose_por_nivel_a_mano():
    # Réplica 1: nivel 2, 8 de 10 por encima; nivel 3, 2 de 30: global 10 / 40 = 25 %.
    # Contribuciones 8 / 40 = 20 y 2 / 40 = 5 puntos. Réplica 2: nivel 2, 6 de 10;
    # nivel 3, 4 de 30: 25 %, con 15 y 10. Medias: nivel 2 70 % y 17,5 puntos;
    # nivel 3, 10 % y 7,5 puntos; suman el 25 %.
    over = target("sobre", levels=(2, 3), band=(10, 30), statistic=PERCENTAGE, threshold=5)
    reps = [
        replica("sobre", 25.0, [25.0], n=(10, 30), over=(8, 2)),
        replica("sobre", 25.0, [25.0], n=(10, 30), over=(6, 4)),
    ]
    level2, level3 = level_breakdown(reps, over)
    assert (level2.level, level2.percentage, level2.contribution) == (2, 70.0, 17.5)
    assert (level3.level, level3.percentage, level3.contribution) == (3, 10.0, 7.5)
    assert level2.contribution + level3.contribution == 25.0


def test_desglose_solo_para_porcentajes():
    with pytest.raises(ValueError, match="is a mean"):
        level_breakdown([replica("t", 1.0)], target())


# --- Día de vaciado ------------------------------------------------------------------------


def _draws() -> PatientDraws:
    return PatientDraws(
        level=3,
        triage_time=5.0,
        assessment_time=60.0,
        reassessment_time=10.0,
        needs_tests=False,
        test_turnaround=60.0,
        admitted=False,
    )


def test_vaciado_a_mano_un_episodio_que_sale_despues_de_la_ventana():
    # Ventana de 1 día sin calentamiento. Una llegada en el minuto 1430: triaje de 5
    # (reloj A = 5, sin esperas) y valoración de 60; sale en 1495, después del final de
    # la ventana (1440). Con el día de vaciado sale dentro del horizonte (2880): cuenta,
    # sin censurados. Sin él, quedaría censurada y el objetivo sin pacientes.
    center = load_center(DATA / "centro_ejemplo.toml")
    horizons = []

    def run(horizon_days):
        horizons.append(horizon_days)
        sink = MemorySink()
        run_engine(
            center,
            [ArrivalRecord(0, 1430.0)],
            lambda arrival: _draws(),
            EventLog("rtest", date(2026, 1, 5), sink),
            horizon_days,
        )
        return sink.events

    table = replica_table(run, days=1, warmup_days=0)
    clock_a = target("a", measure="door_to_doctor", levels=(3,), band=(0, 10))
    values = replica_values(table, [clock_a], 0, 1)

    assert horizons == [1 + DRAIN_DAYS] == [2]
    assert table[0].departure == pytest.approx(1495.0)
    assert (values.arrivals, values.censored) == (1, 0)
    assert values.targets["a"].value == pytest.approx(5.0)


@pytest.fixture(scope="module")
def example():
    return (
        load_center(DATA / "centro_sala_ejemplo.toml"),
        load_profile(DATA / "llegadas_ejemplo.toml"),
        load_profiles(DATA / "perfiles_ejemplo.toml"),
    )


def test_simulate_replicas_simula_un_dia_mas_con_cada_hijo_de_la_semilla(example, monkeypatch):
    calls = []
    real = evaluate.simulate_ed

    def spy(center, profile, days, seed, **kwargs):
        calls.append((days, seed.spawn_key, kwargs["warmup_days"]))
        return real(center, profile, days, seed, **kwargs)

    monkeypatch.setattr(evaluate, "simulate_ed", spy)
    reduced = simulate_replicas(*example, [target()], replicas=2, days=2, warmup_days=1, seed=7)

    assert calls == [(3, (0,), 1), (3, (1,), 1)]
    assert len(reduced) == 2 and all(r.arrivals > 0 for r in reduced)


def test_replica_table_comprueba_el_horizonte():
    with pytest.raises(ValueError, match="warmup_days"):
        replica_table(lambda horizon: [], days=2, warmup_days=2)


# --- El pretriaje no depende de los médicos --------------------------------------------------


def _triage_waits(center, arrivals, profiles):
    table = replica_table(clinical_run(center, arrivals, profiles, 2026, 1), days=3, warmup_days=1)
    return {e.episode_id: e.triage_wait for e in table}


def test_con_la_misma_semilla_los_medicos_no_cambian_el_pretriaje(example):
    # Con otros médicos (muchos menos), el triage_wait de cada episodio es exactamente el
    # mismo: la enfermera se libera al clasificar y la cola del triaje no ve a los médicos.
    center, arrivals, profiles = example
    few = dataclasses.replace(center, doctors=(3, 3, 1))
    base, other = _triage_waits(center, arrivals, profiles), _triage_waits(few, arrivals, profiles)

    assert base == other
    assert sum(w is not None and w > 0 for w in base.values()) > 50  # hay colas de triaje


def test_con_otra_enfermeria_el_pretriaje_cambia(example):
    # Guarda contra el vacío: el mismo caso sí ve a la enfermería.
    center, arrivals, profiles = example
    fewer = dataclasses.replace(center, triage_nurses=(1, 1, 1))
    base, other = (
        _triage_waits(center, arrivals, profiles),
        _triage_waits(fewer, arrivals, profiles),
    )

    assert base.keys() == other.keys()
    assert base != other


# --- Semillas -----------------------------------------------------------------------------


def test_semillas_de_ajuste_y_de_comprobacion_distintas(example):
    assert (FIT_SEED, CHECK_SEED) == (2026, 2027)
    center, arrivals, profiles = example
    fit = replica_table(clinical_run(center, arrivals, profiles, FIT_SEED, 1), 2, 1)
    check = replica_table(clinical_run(center, arrivals, profiles, CHECK_SEED, 1), 2, 1)
    assert [e.arrival for e in fit] != [e.arrival for e in check]


def test_misma_semilla_mismos_episodios(example):
    center, arrivals, profiles = example
    run = clinical_run(center, arrivals, profiles, FIT_SEED, 1)
    assert episode_table(run(2)) == episode_table(run(2))
