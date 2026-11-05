import copy
import dataclasses
import math
from pathlib import Path

import pytest

from edsim.profiles.config import (
    REASON_KEYS,
    REASONS,
    ClinicalProfiles,
    Population,
    ReasonProfile,
    Severity,
    TriageProfile,
    load_profiles,
)

# Un perfil pequeño para los tests de carga: los pesos del catálogo y solo unos
# factores. Los ficheros de verdad (config/perfiles.toml y su copia de ejemplo) se
# prueban en test_profiles_files.py.
DEFAULT = {
    "contexto": {"franjas": [8, 15, 22]},
    "poblacion": {
        "bandas_edad": [15, 45, 65, 80],
        "reparto_edad": [38, 22, 22, 18],
        "franja": [[1, 1, 1.3], [1, 1, 1], [1, 1, 1], [1, 1, 1]],
        "dia": [[1, 1.15], [1, 1], [1, 1], [1, 1]],
        "mujeres": [50, 50, 55, 62],
        "ambulancia": [6, 10, 21, 34],
    },
    "motivos": {
        key: {"nombre": name, "peso_base": weight, "gravedad": {"media": 0.0, "desviacion": 1.0}}
        for key, name, weight in REASONS
    },
    "triaje": {
        "reparto_objetivo": [0.4, 12.1, 33.6, 52.6, 1.4],
        "infratriaje": 10.1,
        "sobretriaje": 6.3,
        "ruido": 0.32,
        "sesgo": -0.08,
        "umbrales": [2.7, 1.13, 0.02, -2.42],
    },
}
DEFAULT["motivos"]["disnea"].update(
    {"edad": [0.4, 0.8, 1.8, 2.4], "franja": [1, 1, 1.2], "estacion": [1.5, 1, 0.7, 1]}
)
DEFAULT["motivos"]["intoxicacion"].update({"franja": [1, 1, 1.8], "dia": [1, 1.7]})
DEFAULT["motivos"]["disnea"]["gravedad"] = {
    "media": 0.9,
    "por_edad": [-0.4, 0.0, 0.2, 0.4],
    "desviacion": 0.8,
}

FACTOR_KEYS = {"edad": 4, "franja": 3, "dia": 2, "estacion": 4}
PERCENT_KEYS = ["reparto_edad", "mujeres", "ambulancia"]


def _toml_value(value) -> str:
    """Write one value as TOML: tomllib can only read."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)  # nan e inf se escriben igual que en TOML
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise TypeError(f"tipo no previsto en el test: {type(value)}")


def _table(lines: list[str], name: str, values: dict) -> None:
    lines.append(f"[{name}]")
    lines += [f"{k} = {_toml_value(v)}" for k, v in values.items() if not isinstance(v, dict)]
    for k, v in values.items():
        if isinstance(v, dict):
            _table(lines, f"{name}.{k}", v)


def write_profiles(tmp_path: Path, changes: dict | None = None, data: dict | None = None) -> Path:
    """Write the default profiles with some keys changed, added or removed (None).

    Keys of ``changes`` are dotted, such as ``"poblacion.mujeres"``,
    ``"motivos.disnea.edad"`` or ``"motivos.disnea"``; a value that is not a
    dict is written as a plain value, also for a whole section.
    """
    data = copy.deepcopy(DEFAULT if data is None else data)
    for dotted, value in (changes or {}).items():
        *parents, key = dotted.split(".")
        target = data
        for parent in parents:
            target = target.setdefault(parent, {})
        if value is None:
            del target[key]
        else:
            target[key] = value

    lines = [f"{k} = {_toml_value(v)}" for k, v in data.items() if not isinstance(v, dict)]
    for section, values in data.items():
        if isinstance(values, dict):
            _table(lines, section, values)
    path = tmp_path / "perfiles.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def load(tmp_path: Path, changes: dict) -> ClinicalProfiles:
    return load_profiles(write_profiles(tmp_path, changes))


@pytest.fixture
def profiles(tmp_path) -> ClinicalProfiles:
    return load_profiles(write_profiles(tmp_path))


# --- Carga y normalización ---------------------------------------------------


def test_carga_del_perfil_de_test(profiles):
    assert profiles.shift_band_starts == (8, 15, 22)
    p = profiles.population
    assert p.band_starts == (15, 45, 65, 80)
    assert p.band_shares == (38.0, 22.0, 22.0, 18.0)
    assert p.band_shift_factors[0] == (1.0, 1.0, 1.3)
    assert p.band_day_factors[0] == (1.0, 1.15)
    assert p.female_pct == (50.0, 50.0, 55.0, 62.0)
    assert p.ambulance_pct == (6.0, 10.0, 21.0, 34.0)

    disnea = profiles.reason("disnea")
    assert disnea.name == "Disnea / respiratorio"
    assert disnea.base_weight == 8.0
    assert disnea.age_factors == (0.4, 0.8, 1.8, 2.4)
    assert disnea.shift_factors == (1.0, 1.0, 1.2)
    assert disnea.day_factors == (1.0, 1.0)  # no lo escribe
    assert disnea.season_factors == (1.5, 1.0, 0.7, 1.0)


def test_factores_ausentes_valen_uno(profiles):
    otros = profiles.reason("otros")

    assert otros.age_factors == (1.0, 1.0, 1.0, 1.0)
    assert otros.shift_factors == (1.0, 1.0, 1.0)
    assert otros.day_factors == (1.0, 1.0)
    assert otros.season_factors == (1.0, 1.0, 1.0, 1.0)


def test_factores_de_poblacion_ausentes_valen_uno(tmp_path):
    p = load(tmp_path, {"poblacion.franja": None, "poblacion.dia": None}).population

    assert p.band_shift_factors == ((1.0, 1.0, 1.0),) * 4
    assert p.band_day_factors == ((1.0, 1.0),) * 4


def test_los_17_motivos_del_catalogo():
    assert len(REASONS) == 17
    assert REASON_KEYS[0] == "traumatismo"
    assert REASON_KEYS[-1] == "otros"
    # El catálogo del diseño: crítico < 1 % (0,5) y otros ~10 %; suma 99,5.
    assert sum(w for _, _, w in REASONS) == pytest.approx(99.5)
    assert all(k.isascii() and k == k.lower() and " " not in k for k in REASON_KEYS)


def test_motivos_en_el_orden_del_catalogo(tmp_path):
    data = copy.deepcopy(DEFAULT)
    data["motivos"] = dict(reversed(data["motivos"].items()))

    profiles = load_profiles(write_profiles(tmp_path, data=data))

    assert profiles.reason_keys == REASON_KEYS
    assert tuple(r.key for r in profiles.reasons) == REASON_KEYS


def test_tipos_normalizados(profiles):
    assert all(type(h) is int for h in profiles.shift_band_starts)
    assert all(type(b) is int for b in profiles.population.band_starts)
    assert all(type(x) is float for x in profiles.population.band_shares)
    assert all(type(x) is float for r in profiles.reasons for x in r.age_factors)
    assert all(type(r.base_weight) is float for r in profiles.reasons)


def test_inmutable(profiles):
    assert isinstance(profiles.reasons, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        profiles.shift_band_starts = (7, 14, 21)
    with pytest.raises(dataclasses.FrozenInstanceError):
        profiles.reasons[0].base_weight = 1.0


def test_replace_idempotente(profiles):
    # Los porcentajes se guardan como se escriben: reconstruir no divide dos veces.
    again = dataclasses.replace(
        profiles,
        population=dataclasses.replace(profiles.population),
        reasons=tuple(dataclasses.replace(r) for r in profiles.reasons),
    )

    assert again == profiles


def test_construccion_directa_tambien_valida(profiles):
    with pytest.raises(ValueError, match=r"motivos\.disnea\.edad must have 4 values, got 3"):
        dataclasses.replace(profiles.reason("disnea"), age_factors=(1, 1, 1))
    with pytest.raises(ValueError, match=r"poblacion\.mujeres\[0\] must be between 0 and 100"):
        dataclasses.replace(profiles.population, female_pct=(101, 50, 50, 50))


def test_construccion_directa_acepta_listas(profiles):
    r = dataclasses.replace(profiles.reason("disnea"), age_factors=[1, 2, 3, 4])

    assert r.age_factors == (1.0, 2.0, 3.0, 4.0)


def test_construccion_directa_sin_un_motivo(profiles):
    with pytest.raises(ValueError, match=r"missing keys: motivos\.parada"):
        dataclasses.replace(profiles, reasons=[r for r in profiles.reasons if r.key != "parada"])


def test_construccion_directa_con_un_motivo_repetido(profiles):
    reasons = (*profiles.reasons, profiles.reason("disnea"))

    with pytest.raises(ValueError, match=r"duplicate keys: motivos\.disnea"):
        dataclasses.replace(profiles, reasons=reasons)


def test_construccion_directa_con_otro_tipo(profiles):
    with pytest.raises(ValueError, match="Population"):
        dataclasses.replace(profiles, population={"mujeres": [50] * 4})
    with pytest.raises(ValueError, match="ReasonProfile"):
        dataclasses.replace(profiles, reasons=(*profiles.reasons[:-1], {"nombre": "Otros"}))


# --- Errores: claves -----------------------------------------------------------


def test_clave_desconocida_en_un_motivo(tmp_path):
    # El mensaje nombra el motivo y la clave: «edades» es una errata de «edad».
    with pytest.raises(ValueError, match=r"unknown keys: motivos\.disnea\.edades"):
        load(tmp_path, {"motivos.disnea.edades": [1, 1, 1, 1]})


def test_falta_el_peso_de_un_motivo(tmp_path):
    with pytest.raises(ValueError, match=r"missing keys: motivos\.fiebre\.peso_base"):
        load(tmp_path, {"motivos.fiebre.peso_base": None})


def test_falta_un_motivo(tmp_path):
    with pytest.raises(ValueError, match=r"missing keys: motivos\.parada\b"):
        load(tmp_path, {"motivos.parada": None})


def test_sobra_un_motivo(tmp_path):
    with pytest.raises(ValueError, match=r"unknown keys: motivos\.gripe\b"):
        load(tmp_path, {"motivos.gripe": {"nombre": "Gripe", "peso_base": 3}})


def test_errata_en_la_clave_de_un_motivo(tmp_path):
    # Falta el bueno y sobra el malo, en el mismo mensaje.
    with pytest.raises(
        ValueError, match=r"missing keys: motivos\.sincope; unknown keys: motivos\.sincope_"
    ):
        load(
            tmp_path, {"motivos.sincope": None, "motivos.sincope_": {"nombre": "x", "peso_base": 4}}
        )


def test_motivo_que_no_es_tabla(tmp_path):
    with pytest.raises(ValueError, match=r"motivos\.disnea must be a table"):
        load(tmp_path, {"motivos.disnea": 8})


@pytest.mark.parametrize("section", ["contexto", "poblacion", "motivos", "triaje"])
def test_falta_una_seccion(tmp_path, section):
    with pytest.raises(ValueError, match=rf"missing keys: {section}\b"):
        load(tmp_path, {section: None})


def test_sobra_una_seccion(tmp_path):
    with pytest.raises(ValueError, match=r"unknown keys: pruebas\b"):
        load(tmp_path, {"pruebas": {"or_mayor": 2.2}})


@pytest.mark.parametrize("section", ["contexto", "poblacion", "motivos", "triaje"])
def test_seccion_que_no_es_tabla(tmp_path, section):
    with pytest.raises(ValueError, match=rf"{section} must be a table"):
        load(tmp_path, {section: [1, 2, 3]})


@pytest.mark.parametrize(
    ("key", "message"),
    [
        ("contexto.franjas", "missing keys: contexto.franjas"),
        ("poblacion.mujeres", "missing keys: poblacion.mujeres"),
        ("poblacion.bandas_edad", "missing keys: poblacion.bandas_edad"),
        ("motivos.otros.nombre", "missing keys: motivos.otros.nombre"),
    ],
)
def test_falta_una_clave(tmp_path, key, message):
    with pytest.raises(ValueError, match=message.replace(".", r"\.")):
        load(tmp_path, {key: None})


@pytest.mark.parametrize("key", ["contexto.turnos", "poblacion.ninos"])
def test_sobra_una_clave(tmp_path, key):
    with pytest.raises(ValueError, match=rf"unknown keys: {key.replace('.', r'\.')}"):
        load(tmp_path, {key: [1, 2, 3]})


# --- Errores: longitudes -------------------------------------------------------


@pytest.mark.parametrize(
    ("factor", "n"), [(f, n + d) for f, n in FACTOR_KEYS.items() for d in (-1, 1)]
)
def test_longitud_de_los_factores_de_un_motivo(tmp_path, factor, n):
    with pytest.raises(
        ValueError, match=rf"motivos\.disnea\.{factor} must have \d values, got {n}"
    ):
        load(tmp_path, {f"motivos.disnea.{factor}": [1.0] * n})


@pytest.mark.parametrize("key", ["bandas_edad", *PERCENT_KEYS])
@pytest.mark.parametrize("n", [3, 5])
def test_longitud_de_la_poblacion(tmp_path, key, n):
    values = list(range(15, 15 + 10 * n, 10)) if key == "bandas_edad" else [10] * n

    with pytest.raises(ValueError, match=rf"poblacion\.{key} must have 4 values, got {n}"):
        load(tmp_path, {f"poblacion.{key}": values})


@pytest.mark.parametrize(("key", "n"), [("franja", 3), ("dia", 2)])
def test_longitud_de_los_factores_de_poblacion(tmp_path, key, n):
    with pytest.raises(ValueError, match=rf"poblacion\.{key} must have 4 values, got 3"):
        load(tmp_path, {f"poblacion.{key}": [[1.0] * n] * 3})
    rows = [[1.0] * n] * 3 + [[1.0] * (n + 1)]
    with pytest.raises(ValueError, match=rf"poblacion\.{key}\[3\] must have {n} values"):
        load(tmp_path, {f"poblacion.{key}": rows})


@pytest.mark.parametrize("n", [2, 4])
def test_longitud_de_las_franjas(tmp_path, n):
    with pytest.raises(ValueError, match=rf"contexto\.franjas must have 3 values, got {n}"):
        load(tmp_path, {"contexto.franjas": list(range(1, n + 1))})


@pytest.mark.parametrize(
    "key",
    ["contexto.franjas", "poblacion.reparto_edad", "poblacion.franja", "motivos.disnea.edad"],
)
def test_no_es_lista(tmp_path, key):
    with pytest.raises(ValueError, match=rf"{key.replace('.', r'\.')} must be a list"):
        load(tmp_path, {key: 7})


# --- Errores: porcentajes ------------------------------------------------------


@pytest.mark.parametrize("key", PERCENT_KEYS)
@pytest.mark.parametrize("value", [-1, 101, -0.01, 100.5])
def test_porcentaje_fuera_de_rango(tmp_path, key, value):
    values = list(DEFAULT["poblacion"][key])
    values[2] = value

    with pytest.raises(ValueError, match=rf"poblacion\.{key}\[2\] must be between 0 and 100"):
        load(tmp_path, {f"poblacion.{key}": values})


@pytest.mark.parametrize("key", PERCENT_KEYS)
def test_porcentajes_limite_validos(tmp_path, key):
    p = load(tmp_path, {f"poblacion.{key}": [0, 100, 50, 100]}).population
    field = {"reparto_edad": "band_shares", "mujeres": "female_pct", "ambulancia": "ambulance_pct"}

    assert getattr(p, field[key]) == (0.0, 100.0, 50.0, 100.0)


def test_reparto_de_edad_todo_ceros(tmp_path):
    with pytest.raises(ValueError, match=r"poblacion\.reparto_edad must have a positive sum"):
        load(tmp_path, {"poblacion.reparto_edad": [0, 0, 0, 0]})


@pytest.mark.parametrize("key", PERCENT_KEYS)
@pytest.mark.parametrize("value", [math.nan, math.inf, True, "50"])
def test_porcentaje_no_numerico(tmp_path, key, value):
    values = list(DEFAULT["poblacion"][key])
    values[1] = value

    with pytest.raises(ValueError, match=rf"poblacion\.{key}\[1\]"):
        load(tmp_path, {f"poblacion.{key}": values})


# --- Errores: factores y pesos -------------------------------------------------


@pytest.mark.parametrize("factor", FACTOR_KEYS)
@pytest.mark.parametrize("value", [0, -1, math.nan, math.inf, True, "1"])
def test_factor_de_motivo_no_valido(tmp_path, factor, value):
    values = [1.0] * FACTOR_KEYS[factor]
    values[1] = value

    with pytest.raises(ValueError, match=rf"motivos\.otros\.{factor}\[1\]"):
        load(tmp_path, {f"motivos.otros.{factor}": values})


@pytest.mark.parametrize("value", [0, -1])
def test_factor_no_positivo_dice_por_que(tmp_path, value):
    with pytest.raises(ValueError, match=r"motivos\.otros\.edad\[0\] must be positive"):
        load(tmp_path, {"motivos.otros.edad": [value, 1, 1, 1]})


@pytest.mark.parametrize(("key", "n"), [("franja", 3), ("dia", 2)])
@pytest.mark.parametrize("value", [0, -0.5, math.nan, True])
def test_factor_de_poblacion_no_valido(tmp_path, key, n, value):
    rows = [[1.0] * n for _ in range(4)]
    rows[2][1] = value

    with pytest.raises(ValueError, match=rf"poblacion\.{key}\[2\]\[1\]"):
        load(tmp_path, {f"poblacion.{key}": rows})


@pytest.mark.parametrize("value", [0, -3, math.nan, True, "8"])
def test_peso_base_no_valido(tmp_path, value):
    with pytest.raises(ValueError, match=r"motivos\.disnea\.peso_base"):
        load(tmp_path, {"motivos.disnea.peso_base": value})


@pytest.mark.parametrize("value", ["", 7, ["Disnea"]])
def test_nombre_no_valido(tmp_path, value):
    with pytest.raises(ValueError, match=r"motivos\.disnea\.nombre must be a non-empty string"):
        load(tmp_path, {"motivos.disnea.nombre": value})


# --- Errores: franjas y bandas -------------------------------------------------


@pytest.mark.parametrize("hours", [[8, 22, 15], [8, 8, 22], [22, 8, 15]])
def test_franjas_no_crecientes(tmp_path, hours):
    with pytest.raises(ValueError, match=r"contexto\.franjas must be strictly increasing"):
        load(tmp_path, {"contexto.franjas": hours})


@pytest.mark.parametrize(("index", "hour"), [(0, -1), (2, 24)])
def test_franjas_fuera_de_rango(tmp_path, index, hour):
    hours = [8, 15, 22]
    hours[index] = hour

    with pytest.raises(ValueError, match=rf"contexto\.franjas\[{index}\] must be between 0 and 23"):
        load(tmp_path, {"contexto.franjas": hours})


@pytest.mark.parametrize("hour", [8.0, 8.5, True, "8"])
def test_franjas_no_enteras(tmp_path, hour):
    with pytest.raises(ValueError, match=r"contexto\.franjas\[0\] must be an integer"):
        load(tmp_path, {"contexto.franjas": [hour, 15, 22]})


def test_franjas_propias_validas(tmp_path):
    assert load(tmp_path, {"contexto.franjas": [0, 12, 23]}).shift_band_starts == (0, 12, 23)


@pytest.mark.parametrize(
    ("bands", "message"),
    [
        ([14, 45, 65, 80], r"poblacion\.bandas_edad\[0\] must be between 15 and 99"),
        ([15, 45, 65, 100], r"poblacion\.bandas_edad\[3\] must be between 15 and 99"),
        ([15, 65, 45, 80], r"poblacion\.bandas_edad must be strictly increasing"),
        ([15, 45, 45, 80], r"poblacion\.bandas_edad must be strictly increasing"),
        ([15, 45.0, 65, 80], r"poblacion\.bandas_edad\[1\] must be an integer"),
    ],
)
def test_bandas_de_edad_no_validas(tmp_path, bands, message):
    with pytest.raises(ValueError, match=message):
        load(tmp_path, {"poblacion.bandas_edad": bands})


def test_tipos_de_las_clases():
    # Las clases se pueden construir a mano, sin TOML, con los factores por defecto.
    r = ReasonProfile(key="otros", name="Otros", base_weight=10, severity=Severity(mean=0, sd=1))
    p = Population(
        band_starts=(15, 45, 65, 80),
        band_shares=(1, 1, 1, 1),
        female_pct=(50,) * 4,
        ambulance_pct=(10,) * 4,
    )

    assert r.age_factors == (1.0,) * 4
    assert r.severity.age_shift == (0.0,) * 4
    assert p.band_day_factors == ((1.0, 1.0),) * 4


# --- Gravedad por motivo -------------------------------------------------------


def test_gravedad_leida(profiles):
    disnea = profiles.reason("disnea").severity

    assert disnea == Severity(mean=0.9, sd=0.8, age_shift=(-0.4, 0.0, 0.2, 0.4))
    assert all(type(x) is float for x in (disnea.mean, disnea.sd, *disnea.age_shift))


def test_por_edad_ausente_vale_cero(profiles):
    assert profiles.reason("otros").severity.age_shift == (0.0, 0.0, 0.0, 0.0)


def test_falta_la_gravedad_de_un_motivo(tmp_path):
    with pytest.raises(ValueError, match=r"missing keys: motivos\.fiebre\.gravedad\b"):
        load(tmp_path, {"motivos.fiebre.gravedad": None})


@pytest.mark.parametrize("key", ["media", "desviacion"])
def test_falta_una_clave_de_la_gravedad(tmp_path, key):
    with pytest.raises(ValueError, match=rf"missing keys: motivos\.fiebre\.gravedad\.{key}"):
        load(tmp_path, {f"motivos.fiebre.gravedad.{key}": None})


def test_clave_desconocida_en_la_gravedad(tmp_path):
    with pytest.raises(ValueError, match=r"unknown keys: motivos\.disnea\.gravedad\.medias"):
        load(tmp_path, {"motivos.disnea.gravedad.medias": 0.5})


def test_gravedad_que_no_es_tabla(tmp_path):
    with pytest.raises(ValueError, match=r"motivos\.disnea\.gravedad must be a table"):
        load(tmp_path, {"motivos.disnea.gravedad": 0.5})


@pytest.mark.parametrize("value", [0, -0.5, math.nan, True, "1"])
def test_desviacion_no_valida(tmp_path, value):
    with pytest.raises(ValueError, match=r"motivos\.disnea\.gravedad\.desviacion"):
        load(tmp_path, {"motivos.disnea.gravedad.desviacion": value})


@pytest.mark.parametrize("value", [0, -0.5])
def test_desviacion_no_positiva_dice_por_que(tmp_path, value):
    with pytest.raises(ValueError, match=r"motivos\.disnea\.gravedad\.desviacion must be positive"):
        load(tmp_path, {"motivos.disnea.gravedad.desviacion": value})


@pytest.mark.parametrize("value", [math.nan, math.inf, True, "0.5"])
def test_media_no_valida(tmp_path, value):
    with pytest.raises(ValueError, match=r"motivos\.disnea\.gravedad\.media"):
        load(tmp_path, {"motivos.disnea.gravedad.media": value})


@pytest.mark.parametrize("n", [3, 5])
def test_longitud_de_por_edad(tmp_path, n):
    with pytest.raises(
        ValueError, match=rf"motivos\.disnea\.gravedad\.por_edad must have 4 values, got {n}"
    ):
        load(tmp_path, {"motivos.disnea.gravedad.por_edad": [0.0] * n})


def test_por_edad_admite_negativos_y_ceros(tmp_path):
    s = load(tmp_path, {"motivos.otros.gravedad.por_edad": [-1, 0, 0.5, 2]}).reason("otros")

    assert s.severity.age_shift == (-1.0, 0.0, 0.5, 2.0)


# --- Triaje --------------------------------------------------------------------


def test_triaje_leido(profiles):
    t = profiles.triage

    assert t == TriageProfile(
        target_pct=(0.4, 12.1, 33.6, 52.6, 1.4),
        under_pct=10.1,
        over_pct=6.3,
        noise=0.32,
        bias=-0.08,
        thresholds=(2.7, 1.13, 0.02, -2.42),
    )


def test_los_umbrales_se_leen_como_se_escriben(tmp_path):
    # Los umbrales se derivan una vez y se escriben: cargar no los recalcula,
    # aunque no den el reparto objetivo.
    t = load(tmp_path, {"triaje.umbrales": [5.0, 4.0, 3.0, 2.0]}).triage

    assert t.thresholds == (5.0, 4.0, 3.0, 2.0)


def test_reparto_objetivo_normalizado(profiles):
    # El reparto de Emergencias 2013 suma 100,1 por el redondeo de la fuente.
    t = profiles.triage

    assert sum(t.target_pct) == pytest.approx(100.1)
    assert sum(t.target_shares) == pytest.approx(1, rel=1e-15)
    assert t.target_shares[0] == pytest.approx(0.4 / 100.1, rel=1e-15)


@pytest.mark.parametrize("values", [[0.4, 12.1, 33.6, 52.6, 1.4], [0, 0, 100, 0, 0]])
def test_reparto_objetivo_valido(tmp_path, values):
    assert load(tmp_path, {"triaje.reparto_objetivo": values}).triage.target_pct == tuple(
        float(v) for v in values
    )


@pytest.mark.parametrize("values", [[0.4, 12.1, 33.6, 50, 1.4], [1, 13, 34, 53, 1.6]])
def test_reparto_que_no_suma_100(tmp_path, values):
    # 97,5 y 102,6: fuera del redondeo de ±0,5 puntos.
    with pytest.raises(ValueError, match=r"triaje\.reparto_objetivo must add up to 100"):
        load(tmp_path, {"triaje.reparto_objetivo": values})


@pytest.mark.parametrize("n", [4, 6])
def test_longitud_del_reparto_objetivo(tmp_path, n):
    with pytest.raises(ValueError, match=rf"triaje\.reparto_objetivo must have 5 values, got {n}"):
        load(tmp_path, {"triaje.reparto_objetivo": [100 / n] * n})


def test_porcentaje_del_reparto_fuera_de_rango(tmp_path):
    message = r"triaje\.reparto_objetivo\[0\] must be between 0 and 100"
    with pytest.raises(ValueError, match=message):
        load(tmp_path, {"triaje.reparto_objetivo": [-1, 13, 34.6, 52, 1.4]})


@pytest.mark.parametrize(
    "thresholds",
    [[2.7, 1.13, 1.13, -2.42], [2.7, 0.02, 1.13, -2.42], [-2.42, 0.02, 1.13, 2.7]],
)
def test_umbrales_no_decrecientes(tmp_path, thresholds):
    with pytest.raises(ValueError, match=r"triaje\.umbrales must be strictly decreasing"):
        load(tmp_path, {"triaje.umbrales": thresholds})


@pytest.mark.parametrize("n", [3, 5])
def test_longitud_de_los_umbrales(tmp_path, n):
    with pytest.raises(ValueError, match=rf"triaje\.umbrales must have 4 values, got {n}"):
        load(tmp_path, {"triaje.umbrales": list(range(n, 0, -1))})


@pytest.mark.parametrize("value", [math.nan, True, "1"])
def test_umbral_no_numerico(tmp_path, value):
    with pytest.raises(ValueError, match=r"triaje\.umbrales\[1\]"):
        load(tmp_path, {"triaje.umbrales": [2.7, value, 0.02, -2.42]})


@pytest.mark.parametrize("value", [0, -0.32, math.nan, True])
def test_ruido_no_valido(tmp_path, value):
    with pytest.raises(ValueError, match=r"triaje\.ruido"):
        load(tmp_path, {"triaje.ruido": value})


@pytest.mark.parametrize("value", [0, 0.5, -0.08])
def test_sesgo_valido(tmp_path, value):
    assert load(tmp_path, {"triaje.sesgo": value}).triage.bias == value


@pytest.mark.parametrize("value", [math.nan, math.inf, True])
def test_sesgo_no_valido(tmp_path, value):
    with pytest.raises(ValueError, match=r"triaje\.sesgo"):
        load(tmp_path, {"triaje.sesgo": value})


@pytest.mark.parametrize("key", ["infratriaje", "sobretriaje"])
@pytest.mark.parametrize("value", [0, 100, -1, math.nan, True])
def test_objetivo_de_error_no_valido(tmp_path, key, value):
    with pytest.raises(ValueError, match=rf"triaje\.{key}"):
        load(tmp_path, {f"triaje.{key}": value})


@pytest.mark.parametrize(
    "key", ["reparto_objetivo", "infratriaje", "sobretriaje", "ruido", "sesgo", "umbrales"]
)
def test_falta_una_clave_del_triaje(tmp_path, key):
    with pytest.raises(ValueError, match=rf"missing keys: triaje\.{key}\b"):
        load(tmp_path, {f"triaje.{key}": None})


@pytest.mark.parametrize("key", ["duracion", "umbral"])
def test_clave_desconocida_en_el_triaje(tmp_path, key):
    # La duración del triaje llega en la tarea 4.4.
    with pytest.raises(ValueError, match=rf"unknown keys: triaje\.{key}\b"):
        load(tmp_path, {f"triaje.{key}": [5, 10]})


def test_triaje_construccion_directa_valida(profiles):
    with pytest.raises(ValueError, match=r"triaje\.ruido must be positive"):
        dataclasses.replace(profiles.triage, noise=0)
    with pytest.raises(ValueError, match="TriageProfile"):
        dataclasses.replace(profiles, triage={"ruido": 0.32})


def test_gravedad_construccion_directa_valida(profiles):
    with pytest.raises(ValueError, match=r"gravedad\.desviacion must be positive"):
        Severity(mean=0, sd=0)
    with pytest.raises(ValueError, match="Severity"):
        dataclasses.replace(profiles.reason("disnea"), severity={"media": 0})


def test_replace_idempotente_con_triaje(profiles):
    again = dataclasses.replace(profiles, triage=dataclasses.replace(profiles.triage))

    assert again == profiles
