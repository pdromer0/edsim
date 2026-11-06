"""Ventana anual de la calibración: una réplica por mes (tarea 4.6c)."""

import dataclasses
import math
from datetime import date, datetime
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pytest

from edsim.arrivals.profile import load_profile
from edsim.calibration import evaluate
from edsim.calibration.evaluate import (
    ReplicaValues,
    TargetValues,
    clinical_run,
    pooled_value,
    replica_table,
    replica_values,
    simulate_replicas,
)
from edsim.calibration.targets import FIT, MANCHESTER, PERCENTAGE, Target, load_targets
from edsim.calibration.window import (
    ANNUAL,
    ANNUAL_REPLICAS,
    START,
    START_REPLICAS,
    WINDOWS,
    first_mondays,
    replica_start_dates,
    window_replicas,
    window_start_dates,
    with_start_date,
)
from edsim.engine.center import load_center
from edsim.profiles.config import load_profiles

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"
CONFIG = ROOT / "config"

MONDAYS_2026 = (
    date(2026, 1, 5),
    date(2026, 2, 2),
    date(2026, 3, 2),
    date(2026, 4, 6),
    date(2026, 5, 4),
    date(2026, 6, 1),
    date(2026, 7, 6),
    date(2026, 8, 3),
    date(2026, 9, 7),
    date(2026, 10, 5),
    date(2026, 11, 2),
    date(2026, 12, 7),
)

DAYS, WARMUP, SEED = 2, 1, 7  # réplicas cortas con los datos de ejemplo


def key(r: ReplicaValues):
    """Todo lo que da una réplica, comparable con ==: repr distingue cada bit y nan == nan."""
    targets = tuple((name, repr(values)) for name, values in sorted(r.targets.items()))
    return targets, r.arrivals, r.censored, r.compliance_days_out, r.compliance_days


# --- Los primeros lunes -------------------------------------------------------------------


def test_primeros_lunes_de_2026_a_mano():
    assert first_mondays(2026) == MONDAYS_2026


def test_primeros_lunes_de_2027_a_mano():
    assert first_mondays(2027) == (
        date(2027, 1, 4),
        date(2027, 2, 1),
        date(2027, 3, 1),
        date(2027, 4, 5),
        date(2027, 5, 3),
        date(2027, 6, 7),
        date(2027, 7, 5),
        date(2027, 8, 2),
        date(2027, 9, 6),
        date(2027, 10, 4),
        date(2027, 11, 1),
        date(2027, 12, 6),
    )


@pytest.mark.parametrize("year", [2026, 2027, 2028, 2030])
def test_cada_fecha_es_lunes_dentro_de_los_siete_primeros_dias_de_su_mes(year):
    mondays = first_mondays(year)
    assert [d.month for d in mondays] == list(range(1, 13))
    assert all(d.year == year and d.weekday() == 0 and d.day <= 7 for d in mondays)


# --- Ventana y réplicas -------------------------------------------------------------------


def test_ventanas_y_replicas():
    assert WINDOWS == (ANNUAL, START) == ("anual", "inicio")
    assert (ANNUAL_REPLICAS, START_REPLICAS) == (12, 10)
    assert window_replicas(ANNUAL, None) == 12
    assert window_replicas(ANNUAL, 12) == 12
    assert window_replicas(START, None) == 10
    assert window_replicas(START, 3) == 3


@pytest.mark.parametrize("replicas", [10, 2, 13])
def test_la_ventana_anual_no_admite_otro_numero_de_replicas(replicas):
    with pytest.raises(ValueError, match="the annual window has 12 replicas, one per month: got"):
        window_replicas(ANNUAL, replicas)


def test_ventana_desconocida():
    with pytest.raises(ValueError, match="window must be one of"):
        window_replicas("mensual", None)
    with pytest.raises(ValueError, match="window must be one of"):
        window_start_dates("mensual", load_profile(DATA / "llegadas_ejemplo.toml"))


def test_fechas_de_cada_ventana():
    profile = load_profile(DATA / "llegadas_ejemplo.toml")
    assert window_start_dates(ANNUAL, profile) == MONDAYS_2026
    assert window_start_dates(START, profile) is None
    later = dataclasses.replace(profile, start_date=date(2027, 3, 10))
    assert window_start_dates(ANNUAL, later) == first_mondays(2027)


def test_fecha_de_cada_replica_para_los_informes():
    profile = load_profile(DATA / "llegadas_ejemplo.toml")
    assert replica_start_dates(ANNUAL, profile, 12) == MONDAYS_2026
    assert replica_start_dates(START, profile, 3) == (date(2026, 1, 5),) * 3
    with pytest.raises(ValueError, match="the annual window has 12 replicas"):
        replica_start_dates(ANNUAL, profile, 10)


# --- simulate_replicas con fechas ---------------------------------------------------------


@pytest.fixture(scope="module")
def example():
    return (
        load_center(DATA / "centro_sala_ejemplo.toml"),
        load_profile(DATA / "llegadas_ejemplo.toml"),
        load_profiles(DATA / "perfiles_ejemplo.toml"),
        load_targets(CONFIG / "objetivos.toml"),
    )


@pytest.fixture(scope="module")
def annual(example):
    """La ventana anual con los datos de ejemplo, con un espía de cada simulación."""
    calls = []
    real = evaluate.simulate_ed

    def spy(center, profile, days, seed, **kwargs):
        calls.append((profile.start_date, seed.spawn_key, days, kwargs["warmup_days"]))
        return real(center, profile, days, seed, **kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(evaluate, "simulate_ed", spy)
        replicas = simulate_replicas(
            *example,
            replicas=12,
            days=DAYS,
            warmup_days=WARMUP,
            seed=SEED,
            start_dates=MONDAYS_2026,
        )
    return replicas, calls


def test_la_replica_m_simula_con_el_hijo_m_y_la_fecha_m(annual):
    _, calls = annual
    assert calls == [(MONDAYS_2026[m], (m,), DAYS + 1, WARMUP) for m in range(12)]


def test_sin_fechas_todas_las_replicas_usan_el_perfil_tal_cual(example, monkeypatch):
    profiles_seen = []
    real = evaluate.simulate_ed

    def spy(center, profile, days, seed, **kwargs):
        profiles_seen.append(profile)
        return real(center, profile, days, seed, **kwargs)

    monkeypatch.setattr(evaluate, "simulate_ed", spy)
    simulate_replicas(*example, replicas=2, days=DAYS, warmup_days=WARMUP, seed=SEED)
    assert all(p is example[1] for p in profiles_seen) and len(profiles_seen) == 2


def test_la_replica_de_enero_es_la_replica_0_sin_fechas(example, annual):
    replicas, _ = annual
    assert example[1].start_date == MONDAYS_2026[0]  # el ejemplo empieza el primer lunes
    without = simulate_replicas(*example, replicas=2, days=DAYS, warmup_days=WARMUP, seed=SEED)
    assert key(replicas[0]) == key(without[0])
    assert key(replicas[1]) != key(without[1])  # febrero no es enero


@pytest.mark.parametrize(
    ("m", "start"), [(6, "2026-07-06"), (11, "2026-12-07")], ids=["julio", "diciembre"]
)
def test_la_replica_m_es_una_simulacion_directa_con_su_hijo_y_su_fecha(
    example, annual, tmp_path, m, start
):
    # La simulación directa no pasa por with_start_date: carga una copia del perfil de
    # ejemplo con su fecha_inicio escrita a mano.
    center, _, profiles, targets = example
    text = (DATA / "llegadas_ejemplo.toml").read_text(encoding="utf-8")
    assert text.count("fecha_inicio = 2026-01-05") == 1
    path = tmp_path / "llegadas.toml"
    path.write_text(text.replace("fecha_inicio = 2026-01-05", f"fecha_inicio = {start}"))
    child = np.random.SeedSequence(SEED, spawn_key=(m,))
    run = clinical_run(center, load_profile(path), profiles, child, WARMUP)
    direct = replica_values(replica_table(run, DAYS, WARMUP), targets, WARMUP, DAYS)

    replicas, _ = annual
    assert key(replicas[m]) == key(direct)
    assert direct.arrivals > 0


def test_otra_fecha_conserva_los_factores_bit_a_bit():
    profile = load_profile(CONFIG / "llegadas.toml")
    july = with_start_date(profile, date(2026, 7, 6))
    assert july.start_date == date(2026, 7, 6) and profile.start_date == date(2026, 1, 5)
    # dataclasses.replace vuelve a normalizar los factores y los mueve en el último bit.
    assert dataclasses.replace(profile, start_date=profile.start_date) != profile
    for field in ("daily_base", "hour_factors", "weekday_factors", "month_factors", "daily_cv"):
        assert repr(getattr(july, field)) == repr(getattr(profile, field))
    assert with_start_date(profile, profile.start_date) == profile


def test_otra_fecha_con_hora_es_un_error():
    with pytest.raises(ValueError, match="date without time"):
        with_start_date(load_profile(CONFIG / "llegadas.toml"), datetime(2026, 7, 6))


def test_fechas_con_otra_longitud(example):
    with pytest.raises(ValueError, match="one start date per replica: 3 replicas and 12 dates"):
        simulate_replicas(
            *example, replicas=3, days=DAYS, warmup_days=WARMUP, seed=SEED, start_dates=MONDAYS_2026
        )


@pytest.mark.slow
def test_la_replica_de_enero_reproduce_la_replica_0_de_la_ventana_de_la_4_6b():
    # El centro de la 4.6b fijado en tests/data ([3, 2, 1] y [12, 11, 5]) con el resto de
    # config/, 14 días con 2 de calentamiento y la semilla 2026: la réplica de enero de la
    # ventana anual es la réplica 0 de la ventana de la 4.6b, valor a valor.
    center = load_center(DATA / "centro_4_6b.toml")
    assert (center.triage_nurses, center.doctors) == ((3, 2, 1), (12, 11, 5))
    args = (
        center,
        load_profile(CONFIG / "llegadas.toml"),
        load_profiles(CONFIG / "perfiles.toml"),
        load_targets(CONFIG / "objetivos.toml"),
    )
    options = {"days": 14, "warmup_days": 2, "seed": 2026}
    annual = simulate_replicas(*args, replicas=12, start_dates=first_mondays(2026), **options)
    start = simulate_replicas(*args, replicas=2, **options)

    assert key(annual[0]) == key(start[0])
    assert annual[0].targets["pretriaje_medio"].value == start[0].targets["pretriaje_medio"].value


# --- La media por paciente de todas las réplicas ------------------------------------------


def _target(statistic, threshold=None):
    return Target(
        name="t",
        measure="door_to_doctor",
        levels=(2, 3, 4, 5),
        statistic=statistic,
        threshold=threshold,
        band=(0, 100),
        use=FIT,
        source="a mano",
        link="https://example.org",
    )


def _replica(value, n, over=()):
    values = TargetValues(value, (value,), tuple(n), tuple(over))
    return ReplicaValues(MappingProxyType({"t": values}), 100, 0, (0,) * 5, (0,) * 5)


def test_media_por_paciente_de_una_media():
    # Media 10 con 1 paciente y 20 con 3: por paciente, (10 + 60) / 4 = 17,5; la media de
    # las réplicas sería 15.
    mean = _target("media")
    replicas = [_replica(10.0, (1, 0, 0, 0)), _replica(20.0, (1, 1, 1, 0))]
    assert pooled_value(replicas, mean) == pytest.approx(17.5, rel=1e-15)


def test_media_por_paciente_de_un_porcentaje():
    # 1 de 4 (25 %) y 3 de 6 (50 %): por paciente, 4 de 10, el 40 %; la media sería 37,5.
    pct = _target(PERCENTAGE, MANCHESTER)
    replicas = [
        _replica(25.0, (2, 2, 0, 0), (1, 0, 0, 0)),
        _replica(50.0, (3, 3, 0, 0), (2, 1, 0, 0)),
    ]
    assert pooled_value(replicas, pct) == pytest.approx(40.0, rel=1e-15)


def test_con_una_sola_replica_la_media_por_paciente_es_su_valor_exacto(example, annual):
    # Con los datos de ejemplo, para los cinco objetivos: el peso de la réplica es el
    # número de pacientes sobre el que se calcula su valor.
    replicas, _ = annual
    targets = example[3]
    assert len(targets) == 5
    for r in (replicas[0], replicas[6]):
        for t in targets:
            value = r.targets[t.name].value
            assert not math.isnan(value)
            assert pooled_value([r], t) == value, t.name


def test_media_por_paciente_sin_pacientes_es_nan():
    assert math.isnan(pooled_value([_replica(math.nan, (0, 0, 0, 0))], _target("media")))
