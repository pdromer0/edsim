import dataclasses
import math
import statistics
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from edsim.arrivals.faults import midnight_lags, midnight_restart_fault
from edsim.arrivals.profile import load_profile
from edsim.arrivals.rate import rate
from edsim.arrivals.thinning import ArrivalRecord, DayRecord, simulate_arrivals
from edsim.seeds import child_streams

EXAMPLE = Path(__file__).parent / "data" / "llegadas_ejemplo.toml"
DAY = 1440  # minutos
MONDAY = date(2026, 1, 5)
SEED = 2026


def make_days(bounds, accepted=None) -> tuple[DayRecord, ...]:
    """Day records with the given bounds; the other fields only need to be coherent."""
    accepted = accepted or [0] * len(bounds)
    return tuple(
        DayRecord(
            day=k,
            date=MONDAY + timedelta(days=k),
            day_effect=1.0,
            expected=300.0,
            bound=b,
            candidates=1000,
            accepted=a,
        )
        for k, (b, a) in enumerate(zip(bounds, accepted, strict=True))
    )


def make_arrivals(times) -> tuple[ArrivalRecord, ...]:
    return tuple(ArrivalRecord(arrival_id=i, time=float(t)) for i, t in enumerate(times))


@pytest.fixture(scope="module")
def run():
    return simulate_arrivals(load_profile(EXAMPLE), 56, SEED)


# --- Retrasos tras la medianoche ----------------------------------------------


def test_retraso_del_dia_0_es_cero():
    lags = midnight_lags(make_days([0.4] * 5), SEED)

    assert lags.shape == (5,)
    assert lags[0] == 0
    assert np.all(lags[1:] > 0)


def test_retraso_medio_es_uno_entre_la_cota_del_dia_anterior():
    # Cotas que alternan entre dos valores: el retraso del día d tiene media
    # 1 / cota(d − 1). Con n = 10 000 días, lags · cota es Exp(1), de error típico
    # 1/√n = 0,01 en la media; la tolerancia son 5.
    n = 10_000
    bounds = np.where(np.arange(n) % 2 == 0, 0.2, 0.6)
    lags = midnight_lags(make_days(bounds.tolist()), SEED)

    scaled = lags[1:] * bounds[:-1]
    assert np.mean(scaled) == pytest.approx(1, abs=0.05)
    assert np.std(scaled) == pytest.approx(1, abs=0.05)  # exponencial: DT = media


def test_retrasos_reproducibles_y_dependen_de_la_semilla():
    days = make_days([0.4] * 5)
    seq = np.random.SeedSequence(SEED)

    assert midnight_lags(days, seq).tolist() == midnight_lags(days, seq).tolist()
    assert midnight_lags(days, SEED).tolist() == midnight_lags(days, seq).tolist()
    assert midnight_lags(days, SEED).tolist() != midnight_lags(days, SEED + 1).tolist()


def test_dias_no_consecutivos_da_error():
    days = make_days([0.4] * 3)
    with pytest.raises(ValueError, match="days"):
        midnight_lags(days[1:], SEED)
    with pytest.raises(ValueError, match="days"):
        midnight_lags((), SEED)


# --- Perturbación C′ ----------------------------------------------------------


def test_cota_infima_borra_los_dias_siguientes_enteros():
    # Con una cota ínfima el retraso es enorme: desaparecen todos los días ≥ 1, el 0 no.
    arrivals = make_arrivals([0.5, 700, DAY + 0.5, DAY + 700, 2 * DAY + 3])
    days = make_days([1e-12] * 3, accepted=[2, 2, 1])

    faulty, faulty_days = midnight_restart_fault(arrivals, days, SEED)

    assert faulty == make_arrivals([0.5, 700])
    assert [d.accepted for d in faulty_days] == [2, 0, 0]


def test_cota_enorme_no_borra_nada():
    # Con una cota enorme el retraso es de ~1e-12 minutos: nada cae dentro.
    arrivals = make_arrivals([0.5, DAY + 0.5, 2 * DAY + 0.5])
    days = make_days([1e12] * 3, accepted=[1, 1, 1])

    assert midnight_restart_fault(arrivals, days, SEED) == (arrivals, days)


def test_borra_exactamente_el_tramo_tras_cada_medianoche(run):
    arrivals, days = run
    lags = midnight_lags(days, SEED)

    faulty, _ = midnight_restart_fault(arrivals, days, SEED)

    kept = [a.time for a in arrivals if a.time - (a.time // DAY) * DAY >= lags[int(a.time // DAY)]]
    assert [a.time for a in faulty] == kept
    assert len(faulty) < len(arrivals)  # 56 días: se espera borrar unas 24


def test_registros_coherentes(run):
    arrivals, days = run

    faulty, faulty_days = midnight_restart_fault(arrivals, days, SEED)

    # Ids consecutivos, como los daría el generador con el error.
    assert [a.arrival_id for a in faulty] == list(range(len(faulty)))
    # accepted cuenta las llegadas que quedan; el resto de campos no cambia.
    per_day = np.bincount([math.floor(a.time / DAY) for a in faulty], minlength=len(days))
    assert [d.accepted for d in faulty_days] == per_day.tolist()
    for original, changed in zip(days, faulty_days, strict=True):
        assert dataclasses.replace(changed, accepted=original.accepted) == original


def test_no_modifica_la_entrada_y_es_reproducible(run):
    arrivals, days = run
    copy = (tuple(arrivals), tuple(days))

    first = midnight_restart_fault(arrivals, days, SEED)
    second = midnight_restart_fault(arrivals, days, SEED)
    other = midnight_restart_fault(arrivals, days, SEED + 1)

    assert (arrivals, days) == copy
    assert first == second
    assert first[0] != other[0]


def test_llegadas_fuera_de_los_dias_da_error():
    arrivals = make_arrivals([0.5, 3 * DAY + 1])
    with pytest.raises(ValueError, match="day"):
        midnight_restart_fault(arrivals, make_days([0.4] * 2), SEED)


# --- Déficit medio (slow) -----------------------------------------------------

DEFICIT_RUNS = 10
DEFICIT_DAYS = 364


@pytest.mark.slow
def test_deficit_medio_por_dia():
    # C′ pierde las llegadas de [0:00, 0:00 + E), con E de media 1/cota(d − 1): el
    # déficit esperado del día d es ≈ λ(0:00 del día d) / cota(d − 1), la escala de dos
    # días seguidos casi se cancela y queda ≈ forma(0:00) / máx(h) = 0,732 / 1,68 ≈ 0,44.
    # Cada día pierde una Poisson de media λ·E, con E exponencial: varianza
    # ≈ 0,44 + 0,44² ≈ 0,63. Con 10 × 363 días, el error típico de la media es ≈ 0,013;
    # la tolerancia, ±0,04, son unos 3.
    profile = load_profile(EXAMPLE)
    deficits, theories = [], []
    for child in child_streams(SEED, DEFICIT_RUNS):
        generator_seq, fault_seq = child_streams(child, 2)
        arrivals, days = simulate_arrivals(profile, DEFICIT_DAYS, generator_seq)
        _, faulty_days = midnight_restart_fault(arrivals, days, fault_seq)

        effects = [d.day_effect for d in days]
        midnights = np.arange(1, DEFICIT_DAYS) * DAY
        lam = rate(midnights, profile, day_effects=effects)
        theories.extend(lam / np.array([d.bound for d in days[:-1]]))
        pairs = zip(days[1:], faulty_days[1:], strict=True)
        deficits.extend(d.accepted - f.accepted for d, f in pairs)

    theory = statistics.fmean(theories)
    observed = statistics.fmean(deficits)

    assert theory == pytest.approx(0.44, abs=0.01)
    assert observed == pytest.approx(theory, abs=0.04), f"déficit = {observed:.3f}"
