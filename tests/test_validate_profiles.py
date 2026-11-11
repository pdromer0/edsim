"""Todas las comprobaciones del muestreador a la vez: edsim perfiles validar (tarea 4.5b).

validate_profiles sortea la mezcla con un hijo de la semilla y una sola muestra del año
con el otro, para el triaje, las pruebas y las duraciones. Cada fila es == a su check_*
llamado por separado, y la mezcla exige un mínimo con margen: sus categorías dentro de
la banda usan el recuento observado de la banda, que es aleatorio.
"""

import dataclasses
import math
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

from edsim.arrivals.profile import load_profile
from edsim.checks import ValidationResult
from edsim.profiles import report, validation
from edsim.profiles.config import N_BANDS, REASON_KEYS, load_profiles
from edsim.profiles.context import ArrivalContext, all_contexts
from edsim.profiles.durations import ASSESSMENT, duration_model
from edsim.profiles.mixing import band_probabilities, reason_probabilities
from edsim.profiles.validation import (
    CHECK_NAMES,
    MAX_MIXING_ERROR,
    check_durations,
    check_mixing,
    check_profiles_validation_counts,
    check_triage,
    check_workup,
    detectable_errors,
    mixing_error_probability,
    mixing_minimum,
    quantile_interval,
    share_interval,
    validate_profiles,
    year_minimum,
    year_patients,
)
from edsim.profiles.workup import workup_model
from edsim.seeds import child_streams

CONFIG = Path(__file__).resolve().parents[1] / "config"
SEED = 2026
MORNING = (ArrivalContext(0, 0, 0),)  # mañana laborable de invierno, OPPOSITE[:1]


@pytest.fixture(scope="module")
def profiles():
    return load_profiles(CONFIG / "perfiles.toml")


@pytest.fixture(scope="module")
def arrivals():
    return load_profile(CONFIG / "llegadas.toml")


# --- El mínimo de la mezcla, con margen (ajuste 1 de la aprobación) -------------------------


def exact_minimum(profiles, contexts):
    """Pacientes por contexto con 5 esperados exactos en cada motivo de cada banda."""
    return max(
        math.ceil(5 / (band_probabilities(profiles.population, c)[b] * min(p, 1 - p)))
        for c in contexts
        for b in range(N_BANDS)
        for p in reason_probabilities(profiles, c, b)
    )


def test_minimo_de_la_mezcla_con_config(profiles):
    # Lo esperado exacto pide 20 491 por contexto; para que la mezcla pare por falta de
    # pacientes con una probabilidad menor que 1e-6 hacen falta 21 379 (+4,3 %). Hasta la
    # tarea 4.6a, con la parada al 0,5 %, eran 13 993 y 15 234.
    assert exact_minimum(profiles, all_contexts()) == 20_491
    assert mixing_minimum(profiles) == 21_379
    assert mixing_error_probability(profiles, 21_379) < MAX_MIXING_ERROR
    assert mixing_error_probability(profiles, 21_378) >= MAX_MIXING_ERROR


def test_la_categoria_mas_justa_y_sus_probabilidades(profiles):
    # Desde la tarea 4.6a, la categoría más justa es la parada en 15-44 años, tarde
    # laborable de invierno: P(banda) = 38,0 % y P(motivo | banda) = 0,0642 %. Con n_banda
    # binomial, la probabilidad de que espere menos de 5 pacientes (y check_mixing pare)
    # es del 50,0 % en el mínimo exacto, del 1,3 % con un 2 % más, de 2,0e-8 con un 5 % y
    # de 2,7e-27 con un 10 %: la banda es la más grande y su recuento varía menos en
    # proporción que el de 80-99 años (18 %), que mandaba con la parada al 0,5 %.
    context = ArrivalContext(1, 0, 0)
    share = float(band_probabilities(profiles.population, context)[0])
    p = reason_probabilities(profiles, context, 0)
    worst = float(min(p.min(), 1 - p.max()))

    assert REASON_KEYS[int(p.argmin())] == "parada"
    assert (round(share, 3), round(100 * worst, 4)) == (0.380, 0.0642)
    assert math.ceil(5 / (share * worst)) == 20_491
    fewest = math.ceil(5 / worst)
    chances = [
        stats.binom.cdf(fewest - 1, math.ceil(20_491 * f), share) for f in (1, 1.02, 1.05, 1.10)
    ]
    assert [round(x, 3) for x in chances[:2]] == [0.500, 0.013]
    assert f"{chances[2]:.1e}" == "2.0e-08"
    assert f"{chances[3]:.1e}" == "2.7e-27"


def test_minimo_de_un_solo_contexto(profiles):
    # Mañana laborable de invierno: 20 022 sin margen y 20 898 con él (13 846 y 15 081
    # hasta la tarea 4.6a). Con 20 000, por debajo de lo esperado, un test pararía según
    # la semilla (cota de 0,55): los tests rápidos con este contexto usan mixing_minimum.
    assert exact_minimum(profiles, MORNING) == 20_022
    assert mixing_minimum(profiles, MORNING) == 20_898
    assert mixing_error_probability(profiles, 20_000, MORNING) > 0.01


@pytest.mark.parametrize(
    "path", [CONFIG / "perfiles.toml", CONFIG.parent / "tests/data/perfiles_ejemplo.toml"]
)
def test_los_pacientes_por_defecto_bastan_para_la_mezcla(path):
    # DEFAULT_MIXING_PATIENTS (25 000) por encima de mixing_minimum (21 379, +16,9 %),
    # en config/ y en tests/data: perfiles validar por defecto no puede parar por falta
    # de pacientes. Con 20 000 (hasta la tarea 4.6a) ya no bastaría.
    assert validation.DEFAULT_MIXING_PATIENTS == 25_000
    assert validation.DEFAULT_MIXING_PATIENTS >= mixing_minimum(load_profiles(path)) == 21_379


def test_minimo_del_ano(profiles, arrivals):
    # Desde la tarea 4.6a manda la parada (0,302 % de los pacientes), que necesita 50
    # pacientes esperados en las medianas por motivo: 16 545. Hasta entonces mandaba el
    # nivel real 1 (0,42 %), con 11 826.
    assert year_minimum(profiles, arrivals) == 16_545


def test_pacientes_por_defecto_y_minimos(profiles, arrivals):
    assert check_profiles_validation_counts(profiles, arrivals) == (25_000, 109_542)
    assert year_patients(profiles, arrivals) == 109_542
    n = mixing_minimum(profiles, MORNING)
    assert check_profiles_validation_counts(profiles, arrivals, n, MORNING) == (n, n)
    with pytest.raises(ValueError, match="21378 < 21379"):
        check_profiles_validation_counts(profiles, arrivals, 21_378)
    with pytest.raises(ValueError, match="patients"):
        check_profiles_validation_counts(profiles, arrivals, 0)


def test_el_ano_tambien_tiene_su_minimo(profiles, arrivals, monkeypatch):
    # Con el mismo N en las dos muestras manda siempre la mezcla (20 898 > 16 545), aunque
    # N baste para el año. El mínimo del año se ve con los valores por defecto y un perfil
    # de llegadas de menos de 16 545 pacientes al año (aquí, simulado).
    with pytest.raises(ValueError, match="mix: 17000 < 20898"):
        check_profiles_validation_counts(profiles, arrivals, 17_000, MORNING)
    monkeypatch.setattr(validation, "year_patients", lambda *args: 1000)
    with pytest.raises(ValueError, match="triage, the tests and the durations: 1000 < 16545"):
        check_profiles_validation_counts(profiles, arrivals)


# --- validate_profiles frente a los check_* --------------------------------------------------


@pytest.fixture(scope="module")
def validated(profiles, arrivals):
    """Una validación con un contexto y el mínimo con margen, contando los sorteos del año."""
    patients = mixing_minimum(profiles, MORNING)
    draws = []
    real = validation._draw_year
    ticks = iter([0.0, 1.0, 3.0, 6.0, 10.0, 15.0])

    def counted(*args, **kwargs):
        draws.append(args[3])
        return real(*args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(validation, "_draw_year", counted)
        result = validate_profiles(
            profiles,
            arrivals,
            seed=SEED,
            patients=patients,
            contexts=MORNING,
            timer=lambda: next(ticks),
        )
    return result, patients, draws


def test_cada_fila_es_la_de_su_check(profiles, arrivals, validated):
    result, patients, _ = validated
    mixing_seed, year_seed = child_streams(SEED, 2)

    assert result.check("mixing").result == check_mixing(
        profiles, arrivals.start_date, seed=mixing_seed, patients=patients, contexts=MORNING
    )
    for name, check in (
        ("triage", check_triage),
        ("workup", check_workup),
        ("durations", check_durations),
    ):
        assert result.check(name).result == check(
            profiles, arrivals, seed=year_seed, patients=patients
        ), name


def test_el_ano_se_sortea_una_sola_vez(validated):
    _, patients, draws = validated

    assert draws == [patients]


def test_filas_de_la_tabla(validated):
    result, patients, _ = validated

    assert [c.name for c in result.checks] == ["mixing", "triage", "workup", "durations"]
    assert [c.categories for c in result.checks] == [89, 30, 134, 64]
    assert [c.patients for c in result.checks] == [patients] * 4  # un contexto: 1 × N
    assert result.year_patients == patients
    assert all(c.alpha == 0.01 / c.categories for c in result.checks)
    assert all(c.failures == 0 and c.passed for c in result.checks)
    assert result.passed
    # El reloj inyectado: la mezcla con su sorteo, el año una vez y cada evaluación.
    assert [c.seconds for c in result.checks] == [1.0, 3.0, 4.0, 5.0]
    assert result.year_seconds == 2.0


def test_los_fallos_cuentan_categorias_tambien_en_la_mezcla(profiles, arrivals):
    # Con el sesgo del triaje desplazado +1 en el muestreador (no en la hipótesis), falla
    # el triaje, con 17 categorías con esta semilla (18 hasta la tarea 4.6a, con otro N y
    # otros umbrales). Las pruebas y las duraciones dependen
    # de G y del nivel real, no del asignado, y la mezcla no depende del triaje: pasan.
    patients = mixing_minimum(profiles, MORNING)
    sampled = dataclasses.replace(
        profiles, triage=dataclasses.replace(profiles.triage, bias=profiles.triage.bias + 1.0)
    )
    result = validate_profiles(
        profiles, arrivals, seed=SEED, patients=patients, contexts=MORNING, sampled_profiles=sampled
    )

    triage = result.check("triage")
    assert not triage.passed and not result.passed
    assert triage.failures == int(triage.result.statistic) == 17
    assert all(result.check(name).passed for name in ("mixing", "workup", "durations"))


# --- El error detectable --------------------------------------------------------------------


def test_error_detectable_con_las_cifras_de_la_especificacion(profiles, arrivals):
    # Pedir analítica en el quintil central (44,9 %; 45,0 % hasta la tarea 4.6a) se ve si
    # pasa a 48,7 % con 20 000 y a 46,5 % en un año; la mediana de la valoración del nivel
    # real 3, a 52,7 % y 51,2 %; el nivel 1 asignado (0,40 %), a 0,61 % y 0,49 %. En la
    # mezcla, con los 25 000 por contexto por defecto, un motivo del 5 % que pasa a 5,76 %
    # (5,85 % con los 20 000 de antes).
    small = detectable_errors(profiles, arrivals, 25_000, 20_000)
    year = detectable_errors(profiles, arrivals, 25_000, 109_542)

    assert small["workup"].category == "pedir/analitica/quintil_3"
    assert round(100 * small["workup"].p0, 1) == 44.9
    assert round(100 * small["workup"].p1, 1) == 48.7
    assert round(100 * year["workup"].p1, 1) == 46.5
    assert small["durations"].category == "valoracion/real_3/mediana"
    assert round(100 * small["durations"].p1, 1) == 52.7
    assert round(100 * year["durations"].p1, 1) == 51.2
    assert round(100 * small["triage"].p0, 2) == 0.40
    assert round(100 * small["triage"].p1, 2) == 0.61
    assert round(100 * year["triage"].p1, 2) == 0.49
    assert (small["mixing"].p0, small["mixing"].patients) == (0.05, 25_000)
    assert round(100 * small["mixing"].p1, 2) == 5.76


# --- Intervalos de las gráficas ---------------------------------------------------------------


def test_intervalo_de_wilson_a_mano():
    # 5 de 10: 0,5 ± ... con z = 1,96, (0,2366; 0,7634).
    low, high = share_interval(5, 10)
    assert (round(low, 4), round(high, 4)) == (0.2366, 0.7634)


def test_intervalo_del_cuantil_a_mano():
    # n = 100, q = 0,5: los rangos de la binomial(100; 0,5) al 2,5 % y al 97,5 % son 40 y
    # 60, así que el IC va de x_(40) a x_(61).
    values = np.arange(100, 0, -1, dtype=float)  # desordenados: 100, 99, ..., 1
    assert quantile_interval(values, 0.5) == (40.0, 61.0)
    # Con muy pocos valores, el rango superior (B⁻¹(0,975) + 1 = 4) se recorta a n = 3; el
    # inferior es B⁻¹(0,025) = 1, porque P(X ≤ 1) = 0,028 con la binomial(3; 0,9).
    assert quantile_interval(np.array([3.0, 1.0, 2.0]), 0.9) == (1.0, 3.0)


def test_datos_de_las_graficas(profiles, arrivals, validated):
    result, patients, _ = validated
    figures = result.figures
    workup = workup_model(profiles, arrivals)

    reasons = figures.reasons
    assert reasons.labels == REASON_KEYS
    assert reasons.exact == tuple(float(p) for p in workup.mixture.weights.sum(axis=1))
    assert round(sum(reasons.observed), 12) == 1.0
    assert reasons.counts == (patients,) * len(REASON_KEYS)
    assert len(figures.triage) == 5
    assert sum(c.counts[0] for c in figures.triage) == patients
    for c in figures.triage:
        assert math.isclose(sum(c.exact), 1.0) and math.isclose(sum(c.observed), 1.0)
    assert [c.title for c in figures.workup] == ["analitica", "radiografia", "ecg", "imagen"]
    assert sum(figures.workup[0].counts) == patients
    durations = duration_model(profiles, arrivals)
    first = figures.durations[0]
    assert (first.title, first.q) == ("valoracion/mediana", 0.5)
    assert first.exact == tuple(
        float(durations.quantile(ASSESSMENT, 0.5, level=n)) for n in range(1, 6)
    )
    assert [c.title for c in figures.durations] == [
        "valoracion/mediana",
        "valoracion/p90",
        "reevaluacion/mediana",
        "reevaluacion/p90",
    ]
    for c in (reasons, *figures.triage, *figures.workup, *figures.durations):
        for low, observed, high in zip(c.low, c.observed, c.high, strict=True):
            assert low <= observed <= high, c.title


# --- Informe ----------------------------------------------------------------------------------


def test_tabla_del_informe(validated):
    result, patients, _ = validated
    text = report.format_profiles_validation(result)
    lines = text.splitlines()

    for column in ("pacientes", "categorías", "fallos", "p mínimo", "α (Bonferroni)"):
        assert column in lines[0]
    assert "error detectable (80 %)" in lines[0] and "tiempo" in lines[0]
    # Los perfiles de ejemplo son del hito 4: las cuatro filas de siempre, y la salida dice
    # que la paciencia y los destinos no se comprueban (tarea 5.3).
    assert [c.name for c in result.checks] == list(CHECK_NAMES)
    for c in result.checks:
        (row,) = [line for line in lines if line.startswith(report.CHECK_LABELS[c.name])]
        assert f"{c.patients}" in row and f"{c.categories}" in row and row.endswith("pasa")
        assert c.detectable.category in row
    assert f"Muestra del año: {patients} pacientes" in text
    assert report.WITHOUT_OUTCOME in lines
    assert report.FALSE_ALARM in lines
    assert "hasta un 4 % de las veces" in report.FALSE_ALARM
    assert lines[-1] == "Resultado: pasan las 4 comprobaciones"


def test_tabla_con_una_comprobacion_que_falla(validated):
    result, _, _ = validated
    triage = result.check("triage")
    failing = ValidationResult("real_1/asignado_3", 9.0, 1e-9, None, None, 0.001, "p", False)
    broken = dataclasses.replace(
        triage,
        result=dataclasses.replace(
            triage.result, passed=False, details=(failing, *triage.result.details[1:])
        ),
        failures=1,
    )
    checks = tuple(broken if c.name == "triage" else c for c in result.checks)
    text = report.format_profiles_validation(dataclasses.replace(result, checks=checks))

    assert "Triaje: fallan 1 categorías" in text
    assert "real_1/asignado_3: p = 1e-09, exacto 0.10 %" in text
    assert text.splitlines()[-1] == "Resultado: FALLAN triaje"
    (row,) = [line for line in text.splitlines() if line.startswith("Triaje ")]
    assert row.endswith("FALLA")


def test_las_cuatro_graficas(validated):
    result, _, _ = validated
    figures = result.figures

    names = [name for name, _ in report.PLOTS]
    assert names == [
        "motivos.png",
        "triaje.png",
        "pruebas_por_gravedad.png",
        "duraciones_por_nivel.png",
    ]
    reasons = report.plot_reasons(figures)
    (ax,) = reasons.axes
    heights = [bar.get_height() for bar in ax.patches]
    assert heights == pytest.approx([100 * p for p in figures.reasons.exact])
    assert len(report.plot_triage(figures).axes) == 5
    (ax,) = report.plot_workup(figures).axes
    exact_lines = [line for line in ax.get_lines() if line.get_label().endswith("(exacto)")]
    assert [list(line.get_ydata()) for line in exact_lines] == [
        pytest.approx([100 * p for p in c.exact]) for c in figures.workup
    ]
    durations = report.plot_durations(figures)
    assert len(durations.axes) == 2
    exact = [
        line for line in durations.axes[0].get_lines() if line.get_label().endswith("(exacto)")
    ]
    assert [list(line.get_ydata()) for line in exact] == [
        pytest.approx(list(figures.durations[0].exact)),
        pytest.approx(list(figures.durations[1].exact)),
    ]
