import dataclasses
import math
from datetime import date, datetime
from pathlib import Path

import pytest

from edsim.arrivals.profile import DAYS_PER_MONTH, ArrivalProfile, load_profile

EXAMPLE = Path(__file__).parent / "data" / "llegadas_ejemplo.toml"
CONFIG = Path(__file__).parents[1] / "config" / "llegadas.toml"

# Los valores de tests/data/llegadas_ejemplo.toml, para construir variantes en los tests.
# fmt: off
DEFAULT = {
    "base_diaria": 300,
    "cv_diario": 0.06,
    "fecha_inicio": date(2026, 1, 5),
    "reparto_horario": [
        2.7, 2.1, 1.6, 1.3, 1.2, 1.1, 1.3, 2.1,
        3.7, 5.4, 6.6, 7.0, 6.7, 6.0, 5.1, 5.4,
        6.2, 6.2, 5.7, 5.3, 5.0, 4.7, 4.2, 3.4,
    ],
    "reparto_semanal": [16.27, 14.80, 14.30, 14.20, 13.77, 13.08, 13.58],
    "factor_mensual": [1.10, 1.05, 1.02, 0.99, 1.00, 0.98, 0.99, 0.97, 0.94, 0.97, 0.98, 1.02],
}
# fmt: on

LIST_KEYS = ["reparto_horario", "reparto_semanal", "factor_mensual"]


def _toml_value(value) -> str:
    """Write one value as TOML: tomllib can only read."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)  # nan e inf se escriben igual que en TOML
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, date):  # incluye datetime
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise TypeError(f"tipo no previsto en el test: {type(value)}")


def write_profile(tmp_path: Path, **changes) -> Path:
    """Write the example profile with some keys changed, added or removed (None)."""
    values = {**DEFAULT, **changes}
    lines = [f"{key} = {_toml_value(v)}" for key, v in values.items() if v is not None]
    path = tmp_path / "llegadas.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def with_value(key: str, index: int, value) -> dict:
    """Copy of the list under ``key`` with one value replaced."""
    values = list(DEFAULT[key])
    values[index] = value
    return {key: values}


@pytest.fixture(scope="module")
def profile() -> ArrivalProfile:
    return load_profile(EXAMPLE)


# --- Carga y normalización ---------------------------------------------------


def test_carga_del_toml_de_ejemplo(profile):
    assert profile.daily_base == 300
    assert profile.daily_cv == pytest.approx(0.06)
    assert profile.start_date == date(2026, 1, 5)
    assert profile.start_date.weekday() == 0  # lunes
    assert len(profile.hour_factors) == 24
    assert len(profile.weekday_factors) == 7
    assert len(profile.month_factors) == 12


def test_config_de_produccion_es_valida():
    # Los valores a mano usan el perfil de ejemplo, que no se recalibra; este test solo
    # comprueba que el perfil del centro base, que sí puede cambiar, carga y es válido.
    p = load_profile(CONFIG)

    assert isinstance(p, ArrivalProfile)
    assert sum(p.hour_factors) / 24 == pytest.approx(1, rel=1e-12)


def test_enteros_aceptados(tmp_path):
    # En TOML, 7 es un entero y 7.0 un float: los dos son valores válidos.
    changes = {key: [int(round(v)) or 1 for v in DEFAULT[key]] for key in LIST_KEYS}
    p = load_profile(write_profile(tmp_path, base_diaria=300, cv_diario=0, **changes))

    assert p.daily_base == 300.0
    assert all(type(x) is float for x in p.hour_factors + p.weekday_factors + p.month_factors)
    assert sum(p.hour_factors) / 24 == pytest.approx(1, rel=1e-12)


def test_toml_escrito_por_el_test_igual_que_el_de_ejemplo(tmp_path, profile):
    # Comprueba el helper: sin cambios, el TOML escrito da el mismo perfil.
    assert load_profile(write_profile(tmp_path)) == profile


def test_factores_horario_y_semanal_con_media_uno(profile):
    assert sum(profile.hour_factors) / 24 == pytest.approx(1, rel=1e-12)
    assert sum(profile.weekday_factors) / 7 == pytest.approx(1, rel=1e-12)
    # Lunes: 7 × 16,27 / 100 = 1,1389; el máximo horario, a las 11 h: 24 × 7 / 100 = 1,68.
    assert profile.weekday_factors[0] == pytest.approx(1.1389)
    assert profile.hour_factors[11] == pytest.approx(1.68)


def test_repartos_no_necesitan_sumar_100(tmp_path, profile):
    # Repartos que suman 200: los factores deben ser los mismos (se divide por la
    # suma, no por 100).
    doubled = {key: [2 * v for v in DEFAULT[key]] for key in ("reparto_horario", "reparto_semanal")}

    p = load_profile(write_profile(tmp_path, **doubled))

    assert p.hour_factors == pytest.approx(profile.hour_factors, rel=1e-12)
    assert p.weekday_factors == pytest.approx(profile.weekday_factors, rel=1e-12)


def test_factor_mensual_ponderado_por_dias(profile):
    # Con los valores escritos, la media ponderada es 1,000740 y la simple, 1,000833:
    # normalizar con la simple dejaría la ponderada en 0,999907.
    weighted = sum(m * n for m, n in zip(profile.month_factors, DAYS_PER_MONTH, strict=True))

    assert sum(DAYS_PER_MONTH) == 365
    assert weighted / 365 == pytest.approx(1, rel=1e-12)


def test_factor_mensual_ponderado_a_mano(tmp_path):
    # Todo 1 salvo febrero = 2. Media ponderada = (365 + 28) / 365 = 393 / 365, así que
    # febrero = 2 × 365 / 393 = 1,857506 y el resto 365 / 393 = 0,928753.
    # Con la media simple (13/12) saldría febrero = 1,846154.
    factors = [1.0] * 12
    factors[1] = 2.0

    p = load_profile(write_profile(tmp_path, factor_mensual=factors))

    assert p.month_factors[1] == pytest.approx(2 * 365 / 393, rel=1e-12)
    assert p.month_factors[0] == pytest.approx(365 / 393, rel=1e-12)
    assert p.month_factors[1] == pytest.approx(1.857506, abs=5e-7)


def test_normalizacion_idempotente(profile):
    # Construir con factores ya normalizados no los vuelve a cambiar.
    again = dataclasses.replace(profile)

    assert again.hour_factors == pytest.approx(profile.hour_factors, rel=1e-15)
    assert again.weekday_factors == pytest.approx(profile.weekday_factors, rel=1e-15)
    assert again.month_factors == pytest.approx(profile.month_factors, rel=1e-15)


def test_inmutable(profile):
    assert isinstance(profile.hour_factors, tuple)
    assert isinstance(profile.weekday_factors, tuple)
    assert isinstance(profile.month_factors, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        profile.daily_base = 400


def test_construccion_directa_tambien_valida():
    # Sin pasar por load_profile, el perfil se valida igual.
    with pytest.raises(ValueError, match="reparto_horario"):
        ArrivalProfile(
            daily_base=300,
            hour_factors=(1.0,) * 23,
            weekday_factors=(1.0,) * 7,
            month_factors=(1.0,) * 12,
            daily_cv=0.06,
            start_date=date(2026, 1, 5),
        )


# --- Errores -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "n"),
    [
        ("reparto_horario", 23),
        ("reparto_horario", 25),
        ("reparto_semanal", 6),
        ("factor_mensual", 11),
    ],
)
def test_numero_de_valores_incorrecto(tmp_path, key, n):
    values = (DEFAULT[key] * 3)[:n]

    with pytest.raises(ValueError, match=rf"{key} must have \d+ values, got {n}"):
        load_profile(write_profile(tmp_path, **{key: values}))


@pytest.mark.parametrize("key", LIST_KEYS)
@pytest.mark.parametrize("value", [-1.0, 0.0])
def test_valores_no_positivos(tmp_path, key, value):
    with pytest.raises(ValueError, match=rf"{key}.*positive"):
        load_profile(write_profile(tmp_path, **with_value(key, 3, value)))


@pytest.mark.parametrize("key", LIST_KEYS)
@pytest.mark.parametrize("value", [math.nan, math.inf, "7", True])
def test_valores_no_finitos_o_no_numericos(tmp_path, key, value):
    with pytest.raises(ValueError, match=key):
        load_profile(write_profile(tmp_path, **with_value(key, 0, value)))


def test_cv_negativo(tmp_path):
    with pytest.raises(ValueError, match="cv_diario"):
        load_profile(write_profile(tmp_path, cv_diario=-0.01))


def test_cv_cero_valido(tmp_path):
    # CV 0 desactiva el efecto diario: es un valor válido.
    assert load_profile(write_profile(tmp_path, cv_diario=0)).daily_cv == 0


@pytest.mark.parametrize("value", [0, -300, math.nan, math.inf, "300", True])
def test_base_no_valida(tmp_path, value):
    with pytest.raises(ValueError, match="base_diaria"):
        load_profile(write_profile(tmp_path, base_diaria=value))


def test_falta_una_clave(tmp_path):
    with pytest.raises(ValueError, match="missing.*cv_diario"):
        load_profile(write_profile(tmp_path, cv_diario=None))


def test_sobra_una_clave(tmp_path):
    # Una errata no puede pasar en silencio: falta la buena y sobra la mala.
    with pytest.raises(ValueError, match="unknown.*base_diara"):
        load_profile(write_profile(tmp_path, base_diaria=None, base_diara=300))


@pytest.mark.parametrize("value", ["2026-01-05", datetime(2026, 1, 5, 0, 0)])
def test_fecha_inicio_no_es_fecha(tmp_path, value):
    with pytest.raises(ValueError, match="fecha_inicio"):
        load_profile(write_profile(tmp_path, fecha_inicio=value))
