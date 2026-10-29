import dataclasses
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

from edsim.arrivals.profile import ArrivalProfile, load_profile
from edsim.arrivals.thinning import ArrivalRecord, DayRecord, simulate_arrivals
from edsim.arrivals.validation import (
    ALPHA,
    WEEKDAY_NAMES,
    check_dispersion,
    check_hourly_shape,
    check_p_uniformity,
    check_rescaled_gaps,
    check_volume,
    conditional_pearson_index,
    p_value_uniformity,
    pearson_index,
    rescaled_gaps,
    validate_arrivals,
)
from edsim.seeds import child_streams

EXAMPLE = Path(__file__).parent / "data" / "llegadas_ejemplo.toml"
DAY = 1440  # minutos
MONDAY = date(2026, 1, 5)
WEDNESDAY = date(2026, 1, 7)


def flat_profile(base: float = 240, start: date = MONDAY, cv: float = 0) -> ArrivalProfile:
    """Profile with every factor equal to 1: the rate is base / 1440 all the time.

    Every day expects ``base`` arrivals and every hour ``base / 24``, so the
    expected values of the tests can be computed by hand.
    """
    return ArrivalProfile(
        daily_base=base,
        hour_factors=(1,) * 24,
        weekday_factors=(1,) * 7,
        month_factors=(1,) * 12,
        daily_cv=cv,
        start_date=start,
    )


def make_days(
    profile: ArrivalProfile, accepted: list[int], effects: list[float] | None = None
) -> tuple[DayRecord, ...]:
    """Day records built by hand; ``expected`` and ``bound`` are dummies on purpose.

    The validation must take the hypothesis from the profile, never from the
    records, so absurd values here must not change any result.
    """
    effects = effects or [1.0] * len(accepted)
    return tuple(
        DayRecord(
            day=k,
            date=profile.start_date + timedelta(days=k),
            day_effect=z,
            expected=-999.0,
            bound=-999.0,
            candidates=n,
            accepted=n,
        )
        for k, (n, z) in enumerate(zip(accepted, effects, strict=True))
    )


def make_arrivals(times) -> tuple[ArrivalRecord, ...]:
    return tuple(ArrivalRecord(arrival_id=i, time=float(t)) for i, t in enumerate(times))


# --- a. Volumen ---------------------------------------------------------------


def test_volumen_cocientes_alrededor_de_uno_pasa():
    # 14 días: cada día de la semana aparece dos veces, una con 230 y otra con 250
    # (los días k y k + 7 tienen distinta paridad). Cocientes 1 ± 1/24, media 1.
    profile = flat_profile(240)
    days = make_days(profile, [230 if k % 2 else 250 for k in range(14)])

    result = check_volume(profile, days)

    assert result.name == "volume"
    assert result.passed
    assert result.statistic == pytest.approx(1, abs=1e-12)
    assert result.target == 1
    assert [d.name for d in result.details] == ["total", *WEEKDAY_NAMES]
    assert all(d.passed for d in result.details)


def test_volumen_bonferroni_8_intervalos():
    profile = flat_profile(240)
    days = make_days(profile, [230 if k % 2 else 250 for k in range(14)])
    confidence = 1 - ALPHA / 8  # 0,99875

    result = check_volume(profile, days)

    # Intervalo t del total recalculado a mano: n = 14, t con 13 g.l.
    ratios = np.array([230 if k % 2 else 250 for k in range(14)]) / 240
    half = stats.t.ppf((1 + confidence) / 2, df=13) * ratios.std(ddof=1) / math.sqrt(14)
    total = result.details[0]
    assert total.ci_low == pytest.approx(ratios.mean() - half, rel=1e-12)
    assert total.ci_high == pytest.approx(ratios.mean() + half, rel=1e-12)
    assert result.ci_low == total.ci_low and result.ci_high == total.ci_high
    assert "99.875" in result.criterion


def test_volumen_10_por_ciento_de_mas_falla_el_total():
    # 264 ± 10 frente a 240 esperadas: cociente medio 1,1. Con 2 valores por día de la
    # semana, t(0,999375; 1 g.l.) ≈ 509 y esos intervalos son enormes: pasan. El total,
    # con 14 valores, no contiene el 1. Un solo intervalo fuera basta para fallar.
    profile = flat_profile(240)
    days = make_days(profile, [254 if k % 2 else 274 for k in range(14)])

    result = check_volume(profile, days)

    assert not result.passed
    assert result.statistic == pytest.approx(1.1)
    assert not result.details[0].passed
    assert all(d.passed for d in result.details[1:])


def test_volumen_dia_de_la_semana_segun_el_calendario():
    # El día 0 es miércoles: los miércoles (k % 7 == 0) tienen el doble.
    profile = flat_profile(240, start=WEDNESDAY)
    days = make_days(profile, [480 if k % 7 == 0 else 240 for k in range(14)])

    by_name = {d.name: d for d in check_volume(profile, days).details}

    assert by_name["wednesday"].statistic == pytest.approx(2)
    assert by_name["monday"].statistic == pytest.approx(1)


def test_volumen_esperado_del_perfil_no_de_los_registros():
    # Mismos recuentos, otra hipótesis: con base 200, 240 llegadas son un 20 % de más.
    days = make_days(flat_profile(240), [240] * 14)

    assert check_volume(flat_profile(240), days).statistic == pytest.approx(1)
    assert check_volume(flat_profile(200), days).statistic == pytest.approx(1.2)


def test_volumen_necesita_14_dias():
    profile = flat_profile(240)
    with pytest.raises(ValueError, match="14 days"):
        check_volume(profile, make_days(profile, [240] * 13))


# --- b. Forma horaria ---------------------------------------------------------


def test_forma_horaria_recuentos_iguales_a_los_esperados():
    # Perfil plano: 10 llegadas en cada hora, justo lo esperado tras reescalar.
    profile = flat_profile(240)
    times = [h * 60 + 1 + i for h in range(24) for i in range(10)]

    result = check_hourly_shape(profile, make_arrivals(times), make_days(profile, [240]))

    assert result.name == "hourly_shape"
    assert result.statistic == pytest.approx(0, abs=1e-12)
    assert result.p_value == pytest.approx(1)
    assert result.passed


def test_forma_horaria_chi_cuadrado_a_mano():
    # 34 llegadas a las 0 h y 10 en el resto: total 264, 11 esperadas por hora tras
    # reescalar. χ² = (34 − 11)²/11 + 23 · (10 − 11)²/11 = 552/11 ≈ 50,2, con 23 g.l.
    profile = flat_profile(240)
    times = [h * 60 + 1 + i for h in range(24) for i in range(34 if h == 0 else 10)]

    result = check_hourly_shape(profile, make_arrivals(times), make_days(profile, [264]))

    assert result.statistic == pytest.approx(552 / 11, rel=1e-12)
    assert result.p_value == pytest.approx(stats.chi2.sf(552 / 11, 23), rel=1e-9)
    assert not result.passed  # p ≈ 0,0008 < 0,01


def test_forma_horaria_hora_del_reloj_en_varios_dias():
    # Las llegadas del segundo día cuentan en la misma hora del reloj que las del primero.
    profile = flat_profile(240)
    times = [d * DAY + h * 60 + 1 + i for d in range(2) for h in range(24) for i in range(10)]

    result = check_hourly_shape(profile, make_arrivals(times), make_days(profile, [240, 240]))

    assert result.statistic == pytest.approx(0, abs=1e-12)


# --- c. Huecos reescalados ----------------------------------------------------


def test_huecos_reescalados_con_z():
    # Base 1440: λ = 1 por minuto y Λ(t) = t. Con Z = 2 el día, Λ(t) = 2t.
    profile = flat_profile(1440)
    arrivals = make_arrivals([1.0, 3.0, 6.0])

    assert rescaled_gaps(profile, arrivals, make_days(profile, [3])).tolist() == pytest.approx(
        [1, 2, 3]
    )
    assert rescaled_gaps(
        profile, arrivals, make_days(profile, [3], effects=[2.0])
    ).tolist() == pytest.approx([2, 4, 6])


def test_huecos_cuantiles_exponenciales_pasa():
    # Huecos iguales a los cuantiles (i − 0,5)/n de la Exp(1): D = 0,5/n exactamente.
    profile = flat_profile(1440)
    n = 100
    gaps = stats.expon.ppf((np.arange(1, n + 1) - 0.5) / n)
    arrivals = make_arrivals(np.cumsum(gaps))

    result = check_rescaled_gaps(profile, arrivals, make_days(profile, [n]))

    assert result.name == "rescaled_gaps"
    assert result.statistic == pytest.approx(0.5 / n, rel=1e-6)
    assert result.passed


def test_huecos_todos_iguales_falla():
    # Todos los huecos valen 1: la ECDF salta de 0 a 1 en x = 1, donde F(1) = 1 − e⁻¹,
    # así que D = máx(1 − e⁻¹, e⁻¹) = 1 − e⁻¹ ≈ 0,632.
    profile = flat_profile(1440)
    arrivals = make_arrivals(np.arange(1, 101, dtype=float))

    result = check_rescaled_gaps(profile, arrivals, make_days(profile, [100]))

    assert result.statistic == pytest.approx(1 - math.exp(-1), rel=1e-9)
    assert not result.passed


# --- d. Dispersión ------------------------------------------------------------


def test_pearson_sin_z_a_mano():
    # e = 100 los dos días: (10²/100 + 10²/100) / 2 = 1. Z no interviene.
    profile = flat_profile(100)
    days = make_days(profile, [110, 90], effects=[1.1, 0.9])

    assert pearson_index(profile, days) == pytest.approx(1)


def test_pearson_condicional_a_mano():
    # Esperado con Z: 110 y 90. Con 121 y 81: (11²/110 + 9²/90) / 2 = (1,1 + 0,9) / 2 = 1.
    profile = flat_profile(100)

    exact = make_days(profile, [110, 90], effects=[1.1, 0.9])
    off = make_days(profile, [121, 81], effects=[1.1, 0.9])

    assert conditional_pearson_index(profile, exact) == pytest.approx(0, abs=1e-12)
    assert conditional_pearson_index(profile, off) == pytest.approx(1)


def replications_with_deviations(profile, deviations) -> list[tuple[DayRecord, ...]]:
    """One 2-day replication per deviation d, with counts 100 ± d and Z = 1: P = d²/100."""
    return [make_days(profile, [100 + d, 100 - d]) for d in deviations]


def test_dispersion_pasa_con_la_teoria_dentro():
    # P de cada réplica: 1; 0,25; 1,69. Media 0,98 y el 1 dentro de los dos intervalos.
    profile = flat_profile(100)
    replications = replications_with_deviations(profile, [10, 5, 13])

    result = check_dispersion(profile, replications)

    assert result.name == "dispersion"
    assert result.statistic == pytest.approx((1 + 0.25 + 1.69) / 3)
    assert result.target == 1
    assert [d.name for d in result.details] == ["unconditional", "conditional"]
    assert all("99.5" in d.criterion for d in result.details)  # Bonferroni: 1 − 0,01/2
    assert result.passed


def test_dispersion_falla_con_varianza_de_mas():
    # P ≈ 4: 4; 4; 4,41; 3,61; 4. Con 3 réplicas no bastaría: t(0,9975; 2 g.l.) ≈ 14 y el
    # intervalo contendría el 1. Con 5, t ≈ 5,6 y el intervalo, ≈ [3,3; 4,7], lo excluye.
    profile = flat_profile(100)

    result = check_dispersion(profile, replications_with_deviations(profile, [20, 20, 21, 19, 20]))

    assert not result.passed
    assert not any(d.passed for d in result.details)


def test_dispersion_teoria_con_cv_del_perfil():
    # Teoría sin Z: 1 + CV²·ē = 1 + 0,01 · 100 = 2; la del condicional sigue siendo 1.
    profile = flat_profile(100, cv=0.1)

    result = check_dispersion(profile, replications_with_deviations(profile, [10, 5, 13]))

    assert result.target == pytest.approx(2)
    assert result.details[1].target == 1


def test_dispersion_necesita_dos_replicas():
    profile = flat_profile(100)
    with pytest.raises(ValueError, match="2 replications"):
        check_dispersion(profile, replications_with_deviations(profile, [10]))


# --- e. Uniformidad de los p-valores ------------------------------------------


def test_p_valores_uniformes_pasa():
    n = 50
    result = p_value_uniformity((np.arange(1, n + 1) - 0.5) / n)

    assert result.name == "p_uniformity"
    assert result.statistic == pytest.approx(0.5 / n)
    assert result.passed


def test_p_valores_todos_pequenos_falla():
    result = p_value_uniformity([0.001] * 50)

    assert result.statistic == pytest.approx(0.999)
    assert not result.passed


def test_uniformidad_usa_el_p_valor_de_c_de_cada_ejecucion():
    profile = flat_profile(1440)
    gaps = stats.expon.ppf((np.arange(1, 101) - 0.5) / 100)
    runs = [
        (make_arrivals(np.cumsum(gaps)), make_days(profile, [100])),
        (make_arrivals(np.arange(1, 101, dtype=float)), make_days(profile, [100])),
        (make_arrivals(np.cumsum(gaps[::-1]) * 1.3), make_days(profile, [100])),
    ]
    p_values = [check_rescaled_gaps(profile, a, d).p_value for a, d in runs]

    assert check_p_uniformity(profile, runs) == p_value_uniformity(p_values)


# --- Validación completa ------------------------------------------------------

# Tamaños mínimos para que los tests rápidos tarden poco: no comprueban si pasa.
SMALL = dict(days=14, replicas=2, short_runs=2, short_days=2)
NAMES = ["volume", "hourly_shape", "rescaled_gaps", "dispersion", "p_uniformity"]


@pytest.fixture(scope="module")
def example() -> ArrivalProfile:
    return load_profile(EXAMPLE)


@pytest.fixture(scope="module")
def small(example):
    return validate_arrivals(example, seed=7, **SMALL)


def test_validacion_cinco_resultados_en_orden(small):
    assert [r.name for r in small.results] == NAMES
    assert small.passed == all(r.passed for r in small.results)
    assert small.result("dispersion") is small.results[3]
    with pytest.raises(KeyError):
        small.result("otra")


def test_validacion_reproducible(example, small):
    assert validate_arrivals(example, seed=7, **SMALL) == small
    assert validate_arrivals(example, seed=8, **SMALL).arrivals != small.arrivals


def test_validacion_semillas_por_bloque(example, small):
    # Hijo 0 para la ejecución larga, 1 para las réplicas y 2 para las cortas.
    long_seq, reps_seq, _ = child_streams(7, 3)

    assert (small.arrivals, small.days) == simulate_arrivals(example, 14, long_seq)
    for i, replication in enumerate(small.replications):
        assert replication == simulate_arrivals(example, 14, child_streams(reps_seq, 2)[i])[1]


def test_validacion_bloques_independientes(example, small):
    # Más réplicas o más ejecuciones cortas no cambian la ejecución larga ni las
    # réplicas que ya había.
    more = validate_arrivals(example, seed=7, **{**SMALL, "replicas": 3, "short_runs": 5})

    assert (more.arrivals, more.days) == (small.arrivals, small.days)
    assert more.replications[:2] == small.replications
    assert more.result("volume") == small.result("volume")


@pytest.mark.parametrize(
    ("argument", "value"),
    [("days", 13), ("replicas", 1), ("short_runs", 1), ("short_days", 0), ("days", 14.0)],
)
def test_validacion_argumentos_invalidos(example, argument, value):
    with pytest.raises(ValueError, match=argument):
        validate_arrivals(example, seed=7, **{**SMALL, argument: value})


# --- Validación con semilla fija (slow) ---------------------------------------

# Como en la especificación: 364 días, 20 réplicas y 100 ejecuciones de 14 días.
# Si un test falla, no se cambia la semilla: se analiza la causa.
SEED = 2026
DAYS = 364


@pytest.fixture(scope="module")
def validation_cv0(example):
    return validate_arrivals(dataclasses.replace(example, daily_cv=0), DAYS, 20, SEED)


@pytest.fixture(scope="module")
def validation_cv006(example):
    assert example.daily_cv == 0.06
    return validate_arrivals(example, DAYS, 20, SEED)


@pytest.mark.slow
@pytest.mark.parametrize("fixture", ["validation_cv0", "validation_cv006"])
def test_las_cinco_pruebas_pasan(request, fixture):
    validation = request.getfixturevalue(fixture)

    failed = [r.name for r in validation.results if not r.passed]
    assert validation.passed, f"fallan: {failed}"


# --- Potencia (slow) ----------------------------------------------------------


@pytest.mark.slow
def test_potencia_base_330_frente_a_300_falla_volumen(example):
    # Un 10 % de llegadas de más: el cociente medio ronda 1,1.
    _, days = simulate_arrivals(dataclasses.replace(example, daily_base=330), DAYS, SEED)

    result = check_volume(example, days)

    assert not result.passed
    assert result.statistic == pytest.approx(1.1, abs=0.02)


@pytest.mark.slow
def test_potencia_perfil_desplazado_una_hora_falla_forma_y_huecos(example):
    # Cada hora toma el factor de la anterior: el pico pasa de las 11 h a las 12 h.
    h = example.hour_factors
    shifted = dataclasses.replace(example, hour_factors=h[-1:] + h[:-1])
    arrivals, days = simulate_arrivals(shifted, DAYS, SEED)

    # b: los recuentos por hora no tienen la forma esperada. c: los huecos reescalados
    # con la λ equivocada se estiran donde λ se subestima y se encogen donde se
    # sobrestima, y dejan de ser Exp(1).
    assert not check_hourly_shape(example, arrivals, days).passed
    assert not check_rescaled_gaps(example, arrivals, days).passed


@pytest.mark.slow
def test_potencia_cv_ignorado_falla_dispersion(example, validation_cv006):
    # Las réplicas generadas con CV 0,06, validadas como si el CV fuera 0: la teoría
    # sin Z pasa a ser 1 y el Pearson observado ronda 2,1.
    result = check_dispersion(
        dataclasses.replace(example, daily_cv=0), validation_cv006.replications
    )

    assert not result.passed
    unconditional, conditional = result.details
    assert not unconditional.passed
    # El condicional usa la Z real de los registros y sigue pasando: el error está en
    # la hipótesis sobre Z, no en el Poisson de cada día.
    assert conditional.passed
