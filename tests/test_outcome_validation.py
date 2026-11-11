"""Validación estadística del desenlace: ``check_patience`` y ``check_destinations`` (tarea 5.2).

El muestreador (``OutcomeSampler``, flujos 4, 8 y 9) contra lo exacto (``OutcomeModel`` y
los cuantiles de la paciencia), con Bonferroni, la potencia escrita y las guardas de
pacientes suficientes, con el patrón de ``check_workup``. La hipótesis sale de los perfiles;
los sorteos, de ``sampled_profiles`` en los tests de potencia.
"""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from edsim.arrivals.profile import load_profile
from edsim.profiles.config import load_profiles
from edsim.profiles.outcome import outcome_model
from edsim.profiles.validation import (
    N_DESTINATION_CATEGORIES,
    N_PATIENCE_CATEGORIES,
    PATIENCE_YEARS,
    _draw_year,
    check_destinations,
    check_patience,
    detectable_share,
    detection_power,
    year_patients,
)

DATA = Path(__file__).parent / "data"
SEED = 2026
DESTINATIONS_N = 30_000  # la guarda pide 23 171: el grupo de cuatro alteradas es el 0,22 %


@pytest.fixture(scope="module")
def profiles():
    return load_profiles(DATA / "perfiles_h5_ejemplo.toml")


@pytest.fixture(scope="module")
def arrivals():
    return load_profile(DATA / "llegadas_ejemplo.toml")


@pytest.fixture(scope="module")
def model(profiles, arrivals):
    return outcome_model(profiles, arrivals)


def test_el_numero_de_categorias():
    assert N_PATIENCE_CATEGORIES == 5 * 4 * 2 == 40
    assert N_DESTINATION_CATEGORIES == 4 * (5 + 5 + 17) == 108


def test_potencia_escrita(profiles, arrivals, model):
    year = year_patients(profiles, arrivals)
    assert year == 109_542
    alpha = 0.01 / N_DESTINATION_CATEGORIES
    # El quintil más grave, con un año: el ingreso del 25,5 % se detecta si pasa al 26,9 %,
    # y el exitus del 0,54 %, si pasa al 0,78 % (el docstring del módulo). Con 0,2692 ± 5e-5,
    # el valor exacto, 0,269153, quedaba a 3,5e-6 del borde: lo destapó la versión V12.
    most_severe = model.by_severity()[0]
    assert most_severe[[1, 3]] == pytest.approx((0.2551, 0.0054), abs=5e-5)
    assert detectable_share(most_severe[1], year // 5, alpha) == pytest.approx(0.26915, abs=5e-6)
    assert detectable_share(most_severe[3], year // 5, alpha) == pytest.approx(0.007843, abs=5e-7)
    # V9 (la paciencia con el nivel asignado), en el nivel real 2 de 15 a 44 años: el
    # 57,19 % bajo la mediana en vez del 50 % (el prototipo del plan). Con dos años, la
    # potencia de esa sola categoría es mayor que 0,9999.
    group = model.true_level_band_shares()[1, 0]
    n = int(PATIENCE_YEARS * year * group)
    assert detection_power(0.5, 0.5719, n, 0.01 / N_PATIENCE_CATEGORIES) > 0.9999


def test_las_guardas(profiles, arrivals, model):
    # El nivel real 1 de 15 a 44 años espera 37 pacientes al año (< 50): con un año, error.
    shares = model.true_level_band_shares()
    assert year_patients(profiles, arrivals) * shares[0, 0] == pytest.approx(37.0, abs=0.5)
    with pytest.raises(ValueError, match=r"too few patients for real_1/banda_15_44"):
        check_patience(profiles, arrivals, seed=SEED, patients=109_542)
    # Las cuatro alteradas, el 0,2158 %: con 20 000 pacientes esperan 43.
    with pytest.raises(ValueError, match=r"too few patients for alteradas_4: expected 43\.2"):
        check_destinations(profiles, arrivals, seed=SEED, patients=20_000)


def test_sin_bloque_no_hay_comprobaciones(arrivals):
    hito4 = load_profiles(DATA / "perfiles_ejemplo.toml")
    for check in (check_patience, check_destinations):
        with pytest.raises(ValueError, match=r"needs the block \[abandono\]"):
            check(hito4, arrivals, seed=SEED, patients=DESTINATIONS_N)


def test_el_ano_con_desenlace_no_cambia_los_sorteos_del_hito_4(profiles, arrivals):
    # child_streams(s, 10) empieza por los 8 hijos de child_streams(s, 8).
    plain = _draw_year(profiles, arrivals, SEED, 2_000)
    full = _draw_year(profiles, arrivals, SEED, 2_000, outcome=True)
    assert plain.band is None and full.band is not None
    for name in ("severity", "level", "true_level", "reason", "ordered", "abnormal", "triage"):
        assert np.array_equal(getattr(plain, name), getattr(full, name))


def test_destinos_con_30000_pacientes(profiles, arrivals):
    result = check_destinations(profiles, arrivals, seed=SEED, patients=DESTINATIONS_N)

    assert result.passed, [(d.name, d.p_value) for d in result.details if not d.passed]
    names = [d.name for d in result.details]
    assert len(names) == len(set(names)) == N_DESTINATION_CATEGORIES
    assert names[:4] == [
        f"destino/{d}/quintil_1" for d in ("alta", "ingreso", "traslado", "exitus")
    ]
    assert names[20] == "destino/alta/alteradas_0"
    assert names[40] == "destino/alta/traumatismo"
    assert names[-1] == "destino/exitus/otros"
    criteria = {d.name: d.criterion.split()[0] for d in result.details}
    # El exitus del quintil más leve espera casi 0 pacientes: binomial exacta.
    assert criteria["destino/exitus/quintil_1"] == "binomial"
    assert criteria["destino/ingreso/quintil_5"] == "p"


def test_detecta_otro_odds_ratio_del_ingreso(profiles, arrivals, model):
    # El muestreador sortea con or_gravedad 2 y no 1,5 en el ingreso; las bases, las escritas.
    # En el quintil más grave el ingreso sube del 25,51 % al 33,32 % (outcome_model con los
    # dos perfiles): potencia > 0,9999 con 6000 pacientes en el quintil.
    admission = replace(profiles.outcome.admission, severity_or=2.0)
    sampled = replace(profiles, outcome=replace(profiles.outcome, admission=admission))
    before = model.by_severity()[0, 1]
    after = outcome_model(sampled, arrivals).by_severity()[0, 1]
    assert (before, after) == pytest.approx((0.2551, 0.3332), abs=5e-5)
    power = detection_power(before, after, DESTINATIONS_N // 5, 0.01 / N_DESTINATION_CATEGORIES)
    assert power > 0.9999

    result = check_destinations(
        profiles, arrivals, seed=SEED, patients=DESTINATIONS_N, sampled_profiles=sampled
    )

    assert "destino/ingreso/quintil_5" in {d.name for d in result.details if not d.passed}


@pytest.mark.slow
def test_destinos_de_un_ano(profiles, arrivals):
    result = check_destinations(profiles, arrivals, seed=SEED)
    assert result.passed, [(d.name, d.p_value) for d in result.details if not d.passed]


@pytest.mark.slow
def test_paciencia_de_dos_anos(profiles, arrivals):
    result = check_patience(profiles, arrivals, seed=SEED)

    assert result.passed, [(d.name, d.p_value) for d in result.details if not d.passed]
    names = [d.name for d in result.details]
    assert len(names) == len(set(names)) == N_PATIENCE_CATEGORIES
    assert names[:2] == [
        "paciencia/real_1/banda_15_44/mediana",
        "paciencia/real_1/banda_15_44/p90",
    ]
    assert names[-1] == "paciencia/real_5/banda_80_99/p90"


@pytest.mark.slow
def test_detecta_otra_paciencia(profiles, arrivals):
    # El muestreador sortea con las medianas y los p90 × 1,2: bajo la mediana exacta queda
    # Φ(−ln 1,2 / σ) = Φ(−0,2127) = 41,6 % en vez del 50 %. Con el mínimo de la guarda.
    abandonment = profiles.outcome.abandonment
    slower = replace(
        abandonment, patience=tuple((1.2 * m, 1.2 * p) for m, p in abandonment.patience)
    )
    sampled = replace(profiles, outcome=replace(profiles.outcome, abandonment=slower))

    result = check_patience(
        profiles, arrivals, seed=SEED, patients=150_000, sampled_profiles=sampled
    )

    failing = {d.name for d in result.details if not d.passed}
    assert "paciencia/real_4/banda_15_44/mediana" in failing
