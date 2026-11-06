import math
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from edsim.arrivals.profile import load_profile
from edsim.arrivals.rate import cumulative_rate
from edsim.profiles.context import (
    DAY_TYPES,
    SEASONS,
    SHIFT_BANDS,
    ArrivalContext,
    all_contexts,
    arrival_context,
    context_indices,
    context_time,
    context_weights,
)

START = date(2026, 1, 5)  # fecha_inicio del perfil de llegadas: un lunes
STARTS = (8, 15, 22)
DAY = 1440
ARRIVALS = Path(__file__).parent / "data" / "llegadas_ejemplo.toml"

# Estación de cada mes, escrita a mano (diciembre a febrero es invierno).
SEASON_OF_MONTH = {
    1: "invierno", 2: "invierno", 3: "primavera", 4: "primavera", 5: "primavera",
    6: "verano", 7: "verano", 8: "verano", 9: "otono", 10: "otono", 11: "otono",
    12: "invierno",
}  # fmt: skip


def t_at(when: date, hour: int, minute: int = 0, start: date = START) -> float:
    """Minutes since 00:00 of ``start`` at ``hour:minute`` of ``when``."""
    return float((when - start).days * DAY + 60 * hour + minute)


def names(ctx: ArrivalContext) -> tuple[str, str, str]:
    return SHIFT_BANDS[ctx.shift_band], DAY_TYPES[ctx.day_type], SEASONS[ctx.season]


def shift_of(t: float, starts=STARTS) -> str:
    return SHIFT_BANDS[arrival_context(t, START, starts).shift_band]


# --- Franja en los bordes ------------------------------------------------------


@pytest.mark.parametrize(
    ("hour", "minute", "band"),
    [
        (0, 0, "noche"),
        (7, 59, "noche"),
        (8, 0, "manana"),
        (14, 59, "manana"),
        (15, 0, "tarde"),
        (21, 59, "tarde"),
        (22, 0, "noche"),
        (23, 59, "noche"),
    ],
)
def test_franja_en_los_bordes(hour, minute, band):
    assert shift_of(t_at(date(2026, 1, 6), hour, minute)) == band


def test_un_instante_antes_de_las_8_sigue_siendo_noche():
    assert shift_of(t_at(date(2026, 1, 6), 8) - 1e-9) == "noche"


@pytest.mark.parametrize(
    ("hour", "minute", "band"),
    [(6, 59, "noche"), (7, 0, "manana"), (13, 59, "manana"), (14, 0, "tarde"), (21, 0, "noche")],
)
def test_franjas_propias_distintas_de_los_turnos(hour, minute, band):
    # Las franjas son del perfil, no de centro.toml (turnos 8, 15 y 22): con
    # [7, 14, 21] las 7:00 ya son de mañana.
    assert shift_of(t_at(date(2026, 1, 6), hour, minute), (7, 14, 21)) == band


def test_franja_de_manana_desde_medianoche():
    # Con la mañana desde las 0:00, la noche es solo de 23:00 a 24:00.
    assert shift_of(t_at(date(2026, 1, 6), 0), (0, 12, 23)) == "manana"
    assert shift_of(t_at(date(2026, 1, 6), 22, 59), (0, 12, 23)) == "tarde"
    assert shift_of(t_at(date(2026, 1, 6), 23), (0, 12, 23)) == "noche"


# --- Tipo de día ---------------------------------------------------------------


def test_domingo_a_lunes():
    sunday, monday = date(2026, 1, 11), date(2026, 1, 12)
    assert sunday.weekday() == 6 and monday.weekday() == 0

    assert names(arrival_context(t_at(sunday, 23, 59), START, STARTS))[1] == "fin_de_semana"
    assert names(arrival_context(t_at(monday, 0), START, STARTS))[1] == "laborable"


def test_viernes_a_sabado():
    friday, saturday = date(2026, 1, 9), date(2026, 1, 10)

    assert names(arrival_context(t_at(friday, 23, 59), START, STARTS))[1] == "laborable"
    assert names(arrival_context(t_at(saturday, 0), START, STARTS))[1] == "fin_de_semana"


def test_un_festivo_cuenta_como_laborable():
    # No hay calendario de festivos (como en el hito 2): el 1 de mayo de 2026 es viernes.
    assert names(arrival_context(t_at(date(2026, 5, 1), 12), START, STARTS))[1] == "laborable"


# --- Estación ------------------------------------------------------------------


def test_30_de_noviembre_a_1_de_diciembre():
    assert names(arrival_context(t_at(date(2026, 11, 30), 23, 59), START, STARTS))[2] == "otono"
    assert names(arrival_context(t_at(date(2026, 12, 1), 0), START, STARTS))[2] == "invierno"


@pytest.mark.parametrize(
    ("last", "first", "before", "after"),
    [
        (date(2026, 2, 28), date(2026, 3, 1), "invierno", "primavera"),
        (date(2026, 5, 31), date(2026, 6, 1), "primavera", "verano"),
        (date(2026, 8, 31), date(2026, 9, 1), "verano", "otono"),
    ],
)
def test_cambios_de_estacion(last, first, before, after):
    assert names(arrival_context(t_at(last, 23, 59), START, STARTS))[2] == before
    assert names(arrival_context(t_at(first, 0), START, STARTS))[2] == after


def test_un_t_de_varios_anos():
    # 2029-03-01 a las 3:00, más de tres años después del inicio, con el 29 de
    # febrero de 2028 por medio; el esperado sale de datetime.
    when = date(2029, 3, 1)
    t = t_at(when, 3)
    assert t > 3 * 365 * DAY

    expected = ("noche", "fin_de_semana" if when.weekday() >= 5 else "laborable", "primavera")
    assert names(arrival_context(t, START, STARTS)) == expected


def test_vectorizado_igual_que_escalar():
    rng = np.random.default_rng(2026)
    times = rng.uniform(0, 3 * 365 * DAY, size=2000)

    shift, day_type, season = context_indices(times, START, STARTS)

    for i in range(0, 2000, 97):
        ctx = arrival_context(times[i], START, STARTS)
        assert (ctx.shift_band, ctx.day_type, ctx.season) == (shift[i], day_type[i], season[i])


def test_igual_que_datetime_en_muchos_instantes():
    # Comprobación independiente con datetime: franja por la hora, fin de semana
    # por el día de la semana y estación por el mes.
    rng = np.random.default_rng(7)
    times = rng.uniform(0, 3 * 365 * DAY, size=500)
    shift, day_type, season = context_indices(times, START, STARTS)

    for t, s, d, e in zip(times, shift, day_type, season, strict=True):
        when = datetime(START.year, START.month, START.day) + timedelta(minutes=float(t))
        band = "manana" if 8 <= when.hour < 15 else "tarde" if 15 <= when.hour < 22 else "noche"
        weekend = "fin_de_semana" if when.weekday() >= 5 else "laborable"
        assert (SHIFT_BANDS[s], DAY_TYPES[d], SEASONS[e]) == (
            band,
            weekend,
            SEASON_OF_MONTH[when.month],
        ), when


def test_otra_fecha_de_inicio():
    # El contexto depende de fecha_inicio: el minuto 0 de un sábado es fin de semana.
    saturday = date(2026, 7, 4)
    ctx = arrival_context(0.0, saturday, STARTS)

    assert names(ctx) == ("noche", "fin_de_semana", "verano")


@pytest.mark.parametrize("t", [-1.0, float("nan"), float("inf")])
def test_tiempo_no_valido(t):
    with pytest.raises(ValueError, match="t must"):
        arrival_context(t, START, STARTS)


# --- Los 24 contextos ----------------------------------------------------------


def test_todos_los_contextos():
    contexts = all_contexts()

    assert len(contexts) == 24
    assert len(set(contexts)) == 24
    assert contexts[0] == ArrivalContext(0, 0, 0)
    assert contexts[0].label == "manana/laborable/invierno"


def test_contexto_no_valido():
    with pytest.raises(ValueError, match="season"):
        ArrivalContext(0, 0, 4)


@pytest.mark.parametrize("ctx", all_contexts())
def test_context_time_cae_en_su_contexto(ctx):
    t = context_time(START, STARTS, ctx)

    assert 0 <= t < 366 * DAY
    assert arrival_context(t, START, STARTS) == ctx


# --- Llegadas esperadas por contexto -------------------------------------------


@pytest.fixture(scope="module")
def arrivals():
    return load_profile(ARRIVALS)


def test_un_dia_a_mano(arrivals):
    # El día 0 es un lunes de enero: todo cae en laborable de invierno.
    w = context_weights(arrivals, STARTS, days=1)
    lam = lambda h: cumulative_rate(60.0 * h, arrivals)  # noqa: E731

    assert w[0, 0, 0] == pytest.approx(lam(15) - lam(8), rel=1e-12)
    assert w[1, 0, 0] == pytest.approx(lam(22) - lam(15), rel=1e-12)
    assert w[2, 0, 0] == pytest.approx(lam(8) + lam(24) - lam(22), rel=1e-12)
    assert w.sum() == pytest.approx(w[:, 0, 0].sum(), rel=1e-15)  # el resto, cero


def test_un_ano_suma_las_llegadas_esperadas(arrivals):
    w = context_weights(arrivals, STARTS)

    assert w.shape == (3, 2, 4)
    assert w.sum() == pytest.approx(cumulative_rate(365.0 * DAY, arrivals), rel=1e-12)
    assert (w > 0).all()  # los 24 contextos ocurren en un año
    # Fin de semana: 2 de cada 7 días, algo menos por el reparto semanal (26,6 %).
    assert w[:, 1, :].sum() / w.sum() == pytest.approx(0.2658, abs=5e-4)


def test_franjas_propias_cambian_los_pesos(arrivals):
    w = context_weights(arrivals, STARTS)
    other = context_weights(arrivals, (7, 14, 21))

    assert other.sum() == pytest.approx(w.sum(), rel=1e-12)
    # La noche de 21 a 7 gana la hora de las 21 (5,0 % del día) y pierde la de las 7 (2,1 %).
    assert other[2].sum() > w[2].sum()


def test_dias_no_validos(arrivals):
    with pytest.raises(ValueError, match="days"):
        context_weights(arrivals, STARTS, days=0)


# --- arrival_context es context_indices, bit a bit (tarea 4.5a) ---------------------


def _edges(shift_band_starts, days=800):
    """Bordes de franja y de día, con el float anterior y el siguiente, y tiempos al azar."""
    times = [0.0]
    for day in range(days):
        for minute in (0, *(60 * h for h in shift_band_starts)):
            t = float(day * 1440 + minute)
            times += [math.nextafter(t, 0.0), t, math.nextafter(t, math.inf)]
    rng = np.random.default_rng(45)
    times += list(rng.uniform(0, days * 1440, size=5000))
    return [t for t in times if t >= 0]


@pytest.mark.parametrize("start", [date(2026, 1, 5), date(2025, 12, 27), date(2028, 2, 26)])
@pytest.mark.parametrize("bands", [(8, 15, 22), (7, 14, 21), (0, 12, 23)])
def test_arrival_context_igual_que_context_indices(start, bands):
    # arrival_context hace con números de Python la aritmética de context_indices (y de
    # rate.split_days): el mismo contexto en los bordes de franja, de día, de mes y de
    # año, con los floats contiguos, y en tiempos al azar de dos años.
    times = _edges(bands)
    shift, day_type, season = context_indices(times, start, bands)
    for t, s, d, e in zip(times, shift, day_type, season, strict=True):
        assert arrival_context(t, start, bands) == ArrivalContext(int(s), int(d), int(e)), t


@pytest.mark.parametrize("t", [-1.0, float("nan"), float("inf"), -1e-300])
def test_arrival_context_rechaza_tiempos_invalidos(t):
    with pytest.raises(ValueError, match="finite and not negative"):
        arrival_context(t, date(2026, 1, 5), (8, 15, 22))
