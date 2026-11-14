"""La carga y la validación de `config/registro_clinico.toml` (tarea 7.2).

Cada test dice qué error pilla. Los ficheros de los tests se escriben desde un diccionario con
`toml_text` (la biblioteca estándar no escribe TOML) y se rompen de uno en uno: cada caso cambia
una sola clave y exige que el error diga su perfil y su clave.
"""

import copy
import re
from datetime import date, datetime

import pytest
from registro_factory import SYSTEMS

from edsim.clinical_record import (
    PROFILE_NAMES,
    RecordProfile,
    RecordProfiles,
    Timed,
    load_record_profiles,
)


class Raw(str):
    """Texto que va al TOML tal cual (`nan`, `inf`, un entero de 400 cifras)."""


DELETE = object()


def timed(rate, minutes):
    return {"tasa": rate, "minutos": list(minutes)}


def valid_data() -> dict:
    """Los tres perfiles, válidos: el limpio a 0 y los otros dos con valores distintos."""
    zero = timed(0.0, (1, 2))
    clean = {
        "olvido": 0.0,
        "vacio": 0.0,
        "erroneo": 0.0,
        "duplicado": zero,
        "correccion": zero,
        "retraso": dict.fromkeys(SYSTEMS, zero),
        "reloj": dict.fromkeys(SYSTEMS, 0),
    }
    realistic = {
        "olvido": 0.005,
        "vacio": 0.01,
        "erroneo": 0.02,
        "duplicado": timed(0.005, (0.5, 2)),
        "correccion": timed(0.5, (120, 720)),
        "retraso": {
            "admision": timed(0.1, (1, 5)),
            "triaje": timed(0.6, (5, 15)),
            "his": timed(0.7, (10, 45)),
            "lab": timed(0.05, (1, 3)),
        },
        "reloj": {"admision": 0, "triaje": 2, "his": 0.5, "lab": -1},
    }
    hostile = copy.deepcopy(realistic)
    hostile["olvido"] = 0.05
    hostile["reloj"]["his"] = -5
    return {"limpio": clean, "realista": realistic, "hostil": hostile}


def toml_value(value) -> str:
    if isinstance(value, Raw):
        return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, str):
        return '"' + value + '"'
    return repr(value)


def toml_text(data: dict, prefix: str = "") -> str:
    """El TOML de un diccionario: las claves sueltas primero y cada subtabla con su cabecera."""
    scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in data.items() if isinstance(v, dict)}
    lines = [f"[{prefix[:-1]}]"] if prefix else []
    lines += [f"{key} = {toml_value(value)}" for key, value in scalars.items()]
    text = "\n".join(lines) + "\n"
    for key, table in tables.items():
        text += "\n" + toml_text(table, f"{prefix}{key}.")
    return text


def change(data: dict, path: str, value) -> dict:
    """Una copia con la clave `perfil.a.b` cambiada, o quitada con `DELETE`."""
    data = copy.deepcopy(data)
    *parents, last = path.split(".")
    table = data
    for key in parents:
        table = table[key]
    if value is DELETE:
        del table[last]
    else:
        table[last] = value
    return data


def write(tmp_path, data: dict) -> str:
    path = tmp_path / "registro_clinico.toml"
    path.write_text(toml_text(data), encoding="utf-8")
    return str(path)


def test_un_fichero_valido_carga_los_tres_perfiles(tmp_path):
    """Pilla un perfil que no es el escrito: el cargador pierde, cambia o reordena un valor."""
    profiles = load_record_profiles(write(tmp_path, valid_data()))
    assert isinstance(profiles, RecordProfiles)
    assert list(profiles) == list(PROFILE_NAMES) == ["limpio", "realista", "hostil"]
    expected = RecordProfile(
        name="realista",
        forget=0.005,
        empty=0.01,
        wrong=0.02,
        duplicate=Timed(0.005, (0.5, 2.0)),
        correction=Timed(0.5, (120.0, 720.0)),
        delay={
            "admision": Timed(0.1, (1.0, 5.0)),
            "triaje": Timed(0.6, (5.0, 15.0)),
            "his": Timed(0.7, (10.0, 45.0)),
            "lab": Timed(0.05, (1.0, 3.0)),
        },
        clock={"admision": 0.0, "triaje": 2.0, "his": 0.5, "lab": -1.0},
    )
    assert profiles["realista"] == expected
    assert profiles["hostil"].forget == 0.05
    assert profiles["hostil"].clock["his"] == -5.0
    assert profiles["limpio"].name == "limpio"


def test_enteros_y_decimales_valen_igual_y_los_bordes_valen(tmp_path):
    """Pilla un cargador que rechaza `tasa = 1` o `reloj = 2` por ser enteros, o el 0 y el 1."""
    data = change(valid_data(), "realista.olvido", 1)
    data = change(data, "realista.vacio", 0)
    data = change(data, "realista.reloj.triaje", 2)
    profile = load_record_profiles(write(tmp_path, data))["realista"]
    assert (profile.forget, profile.empty, profile.clock["triaje"]) == (1.0, 0.0, 2.0)
    assert isinstance(profile.forget, float)


def test_un_perfil_no_conocido_por_nombre_da_un_error_claro(tmp_path):
    """Pilla un `KeyError` mudo al pedir un perfil que no existe."""
    profiles = load_record_profiles(write(tmp_path, valid_data()))
    with pytest.raises(KeyError, match="unknown profile 'caotico'"):
        profiles["caotico"]


NOT_A_NUMBER = [
    ("string", "0.1"),
    ("bool", True),
    ("lista", [0.1]),
    ("fecha", date(2026, 1, 5)),
    ("fecha_y_hora", datetime(2026, 1, 5, 7, 30)),
]
INVALID_RATES = [
    ("negativa", -0.1, "must be in [0, 1]"),
    ("mayor_que_uno", 1.5, "must be in [0, 1]"),
    ("nan", Raw("nan"), "must be finite"),
    ("inf", Raw("inf"), "must be finite"),
    ("menos_inf", Raw("-inf"), "must be finite"),
    ("entero_enorme", Raw("1" + "0" * 400), "is too large"),
]
RATE_PATHS = [
    "realista.olvido",
    "realista.vacio",
    "realista.erroneo",
    "hostil.duplicado.tasa",
    "hostil.correccion.tasa",
    "realista.retraso.triaje.tasa",
]


@pytest.mark.parametrize("path", RATE_PATHS)
@pytest.mark.parametrize(("name", "value"), NOT_A_NUMBER, ids=[n for n, _ in NOT_A_NUMBER])
def test_una_tasa_que_no_es_un_numero_dice_su_perfil_y_su_clave(tmp_path, path, name, value):
    """Pilla un tipo que se cuela (`True` pasa por 1, una fecha o una cadena por un número)."""
    with pytest.raises(ValueError, match=rf"{path}: must be a number"):
        load_record_profiles(write(tmp_path, change(valid_data(), path, value)))


@pytest.mark.parametrize("path", RATE_PATHS)
@pytest.mark.parametrize(
    ("name", "value", "message"), INVALID_RATES, ids=[n for n, _, _ in INVALID_RATES]
)
def test_una_tasa_fuera_de_rango_o_no_finita_dice_su_perfil_y_su_clave(
    tmp_path, path, name, value, message
):
    """Pilla una tasa de 1,5, NaN o infinita, y el entero de 400 cifras que `isfinite` no traga."""
    with pytest.raises(ValueError, match=re.escape(f"{path}: {message}")):
        load_record_profiles(write(tmp_path, change(valid_data(), path, value)))


MINUTES_PATHS = [
    "realista.retraso.his.minutos",
    "hostil.duplicado.minutos",
    "hostil.correccion.minutos",
]
INVALID_MINUTES = [
    ("mediana_mayor_que_p90", [15, 5], "p90 must be greater than the median"),
    ("mediana_igual_al_p90", [5, 5], "p90 must be greater than the median"),
    ("mediana_cero", [0, 5], "median must be positive"),
    ("mediana_negativa", [-1, 5], "median must be positive"),
    ("un_solo_valor", [5], r"must be \[median, p90\]"),
    ("tres_valores", [1, 2, 3], r"must be \[median, p90\]"),
    ("no_es_una_lista", "5", r"must be \[median, p90\]"),
    ("nan_dentro", [1, Raw("nan")], "must be finite"),
    ("p90_enorme", [1, Raw("1" + "0" * 400)], "too large"),
    ("texto_dentro", [1, "5"], "must be a number"),
]


@pytest.mark.parametrize("path", MINUTES_PATHS)
@pytest.mark.parametrize(
    ("name", "value", "message"), INVALID_MINUTES, ids=[n for n, _, _ in INVALID_MINUTES]
)
def test_un_minutos_no_valido_dice_su_perfil_y_su_clave(tmp_path, path, name, value, message):
    """Pilla `[mediana, p90]` mal formado: orden, ceros, longitud y valores no finitos."""
    with pytest.raises(ValueError, match=rf"{path}: .*{message}"):
        load_record_profiles(write(tmp_path, change(valid_data(), path, value)))


@pytest.mark.parametrize("system", SYSTEMS)
@pytest.mark.parametrize(
    ("name", "value"),
    [("nan", Raw("nan")), ("inf", Raw("inf")), ("bool", True), ("string", "dos")],
)
def test_un_desfase_no_valido_dice_su_sistema(tmp_path, system, name, value):
    """Pilla un desfase de reloj que no es un número finito."""
    path = f"hostil.reloj.{system}"
    with pytest.raises(ValueError, match=rf"{path}: must "):
        load_record_profiles(write(tmp_path, change(valid_data(), path, value)))


def test_un_desfase_negativo_o_decimal_es_valido(tmp_path):
    """Pilla un cargador que exige desfases positivos o enteros (el de laboratorio es -1)."""
    data = change(valid_data(), "hostil.reloj.lab", -2.5)
    assert load_record_profiles(write(tmp_path, data))["hostil"].clock["lab"] == -2.5


STRUCTURE = [
    ("falta_un_perfil", "hostil", DELETE, "hostil: missing profile"),
    ("sobra_un_perfil", "caotico", valid_data()["hostil"], "caotico: unknown profile"),
    ("falta_una_clave", "realista.vacio", DELETE, "realista.vacio: missing key"),
    ("sobra_una_clave", "realista.extra", 1, "realista.extra: unknown key"),
    (
        "falta_un_sistema_de_retraso",
        "realista.retraso.lab",
        DELETE,
        "realista.retraso.lab: missing",
    ),
    (
        "sobra_un_sistema_de_retraso",
        "hostil.retraso.rrhh",
        timed(0.1, (1, 2)),
        "hostil.retraso.rrhh: unknown",
    ),
    ("falta_un_sistema_de_reloj", "hostil.reloj.his", DELETE, "hostil.reloj.his: missing"),
    ("sobra_un_sistema_de_reloj", "limpio.reloj.rrhh", 0, "limpio.reloj.rrhh: unknown"),
    (
        "sobra_una_clave_en_duplicado",
        "realista.duplicado.extra",
        1,
        "realista.duplicado.extra: unknown",
    ),
    (
        "falta_minutos_en_correccion",
        "hostil.correccion.minutos",
        DELETE,
        "hostil.correccion.minutos: missing",
    ),
    ("retraso_no_es_una_tabla", "realista.retraso", 3, "realista.retraso: must be a table"),
    ("un_perfil_no_es_una_tabla", "hostil", 7, "hostil: must be a table"),
    (
        "un_sistema_no_es_una_tabla",
        "realista.retraso.his",
        0.5,
        "realista.retraso.his: must be a table",
    ),
]


@pytest.mark.parametrize(
    ("path", "value", "message"), [c[1:] for c in STRUCTURE], ids=[c[0] for c in STRUCTURE]
)
def test_una_clave_que_falta_o_sobra_dice_su_perfil_y_su_clave(tmp_path, path, value, message):
    """Pilla un perfil con claves de menos o de más: las claves desconocidas están prohibidas."""
    with pytest.raises(ValueError, match=message):
        load_record_profiles(write(tmp_path, change(valid_data(), path, value)))


LIMPIO_NOT_ZERO = (
    [("limpio.olvido", 0.1), ("limpio.vacio", 0.1), ("limpio.erroneo", 0.1)]
    + [("limpio.duplicado.tasa", 0.2), ("limpio.correccion.tasa", 0.2)]
    + [(f"limpio.retraso.{s}.tasa", 0.3) for s in SYSTEMS]
    + [(f"limpio.reloj.{s}", v) for s in SYSTEMS for v in (1, -0.5)]
)


@pytest.mark.parametrize(
    ("path", "value"), LIMPIO_NOT_ZERO, ids=[f"{p}={v}" for p, v in LIMPIO_NOT_ZERO]
)
def test_un_limpio_con_algo_distinto_de_cero_es_un_error(tmp_path, path, value):
    """Pilla un `limpio` que no es limpio: cada tasa y cada desfase tiene que valer 0."""
    with pytest.raises(ValueError, match=rf"{path}: must be 0 in the clean profile"):
        load_record_profiles(write(tmp_path, change(valid_data(), path, value)))


def test_un_limpio_acepta_cero_en_todo_con_cualquier_minutos(tmp_path):
    """Pilla un `limpio` rechazado por sus minutos: solo se les pide 0 < mediana < p90."""
    data = change(valid_data(), "limpio.retraso.his.minutos", [10, 45])
    assert load_record_profiles(write(tmp_path, data))["limpio"].delay["his"].minutes == (
        10.0,
        45.0,
    )


def test_los_errores_se_dan_juntos_cada_uno_con_su_clave(tmp_path):
    """Pilla un cargador que para en el primer error: hay que arreglar el fichero de una vez."""
    data = change(valid_data(), "realista.olvido", 2)
    data = change(data, "hostil.retraso.lab.minutos", [3, 1])
    data = change(data, "limpio.reloj.triaje", 4)
    with pytest.raises(ValueError) as error:
        load_record_profiles(write(tmp_path, data))
    message = str(error.value)
    for key in ("realista.olvido", "hostil.retraso.lab.minutos", "limpio.reloj.triaje"):
        assert key in message


def test_el_mensaje_empieza_por_la_ruta_del_fichero(tmp_path):
    """Pilla un error que no dice qué fichero lo causó."""
    path = write(tmp_path, change(valid_data(), "realista.olvido", 2))
    with pytest.raises(ValueError, match=rf"^{path}: realista.olvido"):
        load_record_profiles(path)


def test_un_fichero_vacio_pide_los_tres_perfiles(tmp_path):
    """Pilla un fichero vacío que carga sin perfiles."""
    path = tmp_path / "vacio.toml"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError) as error:
        load_record_profiles(path)
    for name in PROFILE_NAMES:
        assert f"{name}: missing profile" in str(error.value)


def test_un_toml_roto_es_un_value_error(tmp_path):
    """Pilla un TOML ilegible que escapa como otra excepción: la CLI espera `ValueError`."""
    path = tmp_path / "roto.toml"
    path.write_text("[limpio\nolvido = ", encoding="utf-8")
    with pytest.raises(ValueError):
        load_record_profiles(path)


def test_un_fichero_que_no_existe_es_un_os_error(tmp_path):
    """Pilla un fichero ausente que se convierte en otro error: la CLI espera `OSError`."""
    with pytest.raises(OSError):
        load_record_profiles(tmp_path / "no_existe.toml")


# --- El fichero real, config/registro_clinico.toml -----------------------------------------

REAL = {
    "realista": {
        "forget": 0.005, "empty": 0.01, "wrong": 0.01,
        "duplicate": (0.005, (0.5, 2.0)), "correction": (0.5, (120.0, 720.0)),
        "delay": {
            "admision": (0.10, (1.0, 5.0)), "triaje": (0.60, (5.0, 15.0)),
            "his": (0.70, (10.0, 45.0)), "lab": (0.05, (1.0, 3.0)),
        },
        "clock": {"admision": 0.0, "triaje": 2.0, "his": 0.0, "lab": -1.0},
    },
    "hostil": {
        "forget": 0.05, "empty": 0.07, "wrong": 0.07,
        "duplicate": (0.04, (0.5, 5.0)), "correction": (0.3, (240.0, 1440.0)),
        "delay": {
            "admision": (0.30, (2.0, 15.0)), "triaje": (0.90, (10.0, 40.0)),
            "his": (0.90, (20.0, 120.0)), "lab": (0.20, (2.0, 10.0)),
        },
        "clock": {"admision": 3.0, "triaje": 7.0, "his": -5.0, "lab": -3.0},
    },
}  # fmt: skip
"""Los valores de «Valores orientativos de partida» de la especificación: la 7.2 no encontró
fuentes que los cambien, y este test los fija para que cambiarlos sea una decisión visible."""


@pytest.mark.parametrize("name", ["realista", "hostil"])
def test_el_fichero_real_tiene_los_valores_de_la_especificacion(name):
    """Pilla un valor del fichero que se aparta de la tabla de la especificación sin decirlo."""
    from registro_factory import PROFILES_FILE

    profile = load_record_profiles(PROFILES_FILE)[name]
    expected = REAL[name]
    assert (profile.forget, profile.empty, profile.wrong) == (
        expected["forget"],
        expected["empty"],
        expected["wrong"],
    )
    for key in ("duplicate", "correction"):
        rate, minutes = expected[key]
        assert (getattr(profile, key).rate, getattr(profile, key).minutes) == (rate, minutes), key
    for system in SYSTEMS:
        rate, minutes = expected["delay"][system]
        assert (profile.delay[system].rate, profile.delay[system].minutes) == (rate, minutes)
    assert dict(profile.clock) == expected["clock"]


def test_el_limpio_real_no_tiene_nada_distinto_de_cero():
    """Pilla un `limpio` del fichero real con un despiste (la carga ya lo exige: doble cierre)."""
    from registro_factory import PROFILES_FILE

    clean = load_record_profiles(PROFILES_FILE)["limpio"]
    rates = [clean.forget, clean.empty, clean.wrong, clean.duplicate.rate, clean.correction.rate]
    rates += [t.rate for t in clean.delay.values()] + list(clean.clock.values())
    assert rates == [0.0] * len(rates)
