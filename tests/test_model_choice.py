"""La elección del modelo por los bloques de los dos ficheros (tarea 5.3, decisión 68).

Sin perfiles, el provisional; con perfiles sin el bloque del hito 5 y un centro con
[destino], el del hito 4; con el bloque y un centro con [camas], el del hito 5. Un bloque
a medias es un error que nombra la clave que falta y su fichero: dentro de un fichero lo
da la carga (tarea 5.2), y entre los dos ficheros, ``choose_model``.
"""

from pathlib import Path

import pytest

from edsim.engine.center import load_center
from edsim.engine.clinical_sampler import ModelChoiceError, PatientModel, choose_model
from edsim.profiles.config import load_profiles

DATA = Path(__file__).parent / "data"
CENTER_4 = DATA / "centro_sala_ejemplo.toml"
CENTER_5 = DATA / "centro_h5_ejemplo.toml"
PROFILES_4 = DATA / "perfiles_ejemplo.toml"
PROFILES_5 = DATA / "perfiles_h5_ejemplo.toml"


def choose(center: Path, profiles: Path | None) -> PatientModel:
    return choose_model(
        load_center(center),
        None if profiles is None else load_profiles(profiles),
        center_file=str(center),
        profiles_file=str(profiles),
    )


@pytest.mark.parametrize(
    ("center", "profiles", "model", "schema_version", "n_streams"),
    [
        (CENTER_4, None, PatientModel.PROVISIONAL, 1, 5),
        (DATA / "centro_ejemplo.toml", PROFILES_4, PatientModel.MILESTONE_4, 3, 8),
        (CENTER_4, PROFILES_4, PatientModel.MILESTONE_4, 3, 8),
        (CENTER_5, PROFILES_5, PatientModel.MILESTONE_5, 4, 10),
    ],
)
def test_los_bloques_eligen_el_modelo(center, profiles, model, schema_version, n_streams):
    # La versión del catálogo y el número de flujos, escritos a mano: 1 y 5 del hito 3,
    # 3 y 8 del hito 4 (decisión 43), 4 y 10 del hito 5 (pieza 6 de la especificación).
    chosen = choose(center, profiles)

    assert chosen is model
    assert (chosen.schema_version, chosen.n_streams) == (schema_version, n_streams)


@pytest.mark.parametrize(
    ("center", "profiles", "file", "keys"),
    [
        # Un centro del hito 5 sin perfiles: el provisional necesita [destino].
        (CENTER_5, None, "centro_h5_ejemplo.toml", ["[destino]", "[camas]"]),
        # Perfiles del hito 4 con un centro del hito 5: faltan los bloques en los perfiles.
        (CENTER_5, PROFILES_4, "perfiles_ejemplo.toml", ["[abandono]", "[destinos]", "ingreso"]),
        # Perfiles del hito 5 con un centro del hito 4: falta [camas] en el centro.
        (CENTER_4, PROFILES_5, "centro_sala_ejemplo.toml", ["[camas]"]),
    ],
)
def test_un_bloque_a_medias_entre_los_dos_ficheros_es_un_error(center, profiles, file, keys):
    with pytest.raises(ModelChoiceError) as error:
        choose(center, profiles)

    message = str(error.value)
    assert message.startswith(str(DATA / file) + ":")
    for key in keys:
        assert key in message


def test_el_error_es_un_value_error_con_los_nombres_por_defecto():
    # Los que ya capturan ValueError (la CLI, el servicio) lo siguen capturando.
    assert issubclass(ModelChoiceError, ValueError)
    with pytest.raises(ModelChoiceError, match=r"^centro\.toml: missing \[camas\]"):
        choose_model(load_center(CENTER_4), load_profiles(PROFILES_5))
    with pytest.raises(ModelChoiceError, match=r"^perfiles\.toml: missing \[abandono\]"):
        choose_model(load_center(CENTER_5), load_profiles(PROFILES_4))


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def table(text: str, name: str) -> int:
    """Dónde empieza la tabla ``name``: a principio de línea, no en un comentario."""
    return text.index(f"\n{name}\n") + 1


def profiles_without(text: str, start: str, end: str | None) -> str:
    """El texto de los perfiles sin las tablas de ``start`` a ``end`` (o al final)."""
    i = table(text, start)
    return text[:i] + ("" if end is None else text[table(text, end) :])


def one_admission_less(text: str) -> str:
    """Los perfiles del hito 5 sin el ``ingreso`` del primer motivo que lo lleva."""
    i = text.index("\ningreso = ")
    return text[:i] + text[text.index("\n", i + 1) :]


H5_PROFILES = PROFILES_5.read_text(encoding="utf-8")
H5_CENTER = CENTER_5.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("name", "text", "loader", "key"),
    [
        (
            "sin_destinos.toml",
            profiles_without(H5_PROFILES, "[destinos]", None),
            load_profiles,
            "destinos",
        ),
        (
            "sin_abandono.toml",
            profiles_without(H5_PROFILES, "[abandono]", "[destinos]"),
            load_profiles,
            "abandono",
        ),
        ("un_ingreso_menos.toml", one_admission_less(H5_PROFILES), load_profiles, ".ingreso"),
        (
            "camas_a_medias.toml",
            H5_CENTER.replace("factor_turno = [0.8, 1.0, 1.5]\n", ""),
            load_center,
            "camas.factor_turno",
        ),
        (
            "destino_y_camas.toml",
            CENTER_4.read_text(encoding="utf-8") + "\n" + H5_CENTER[table(H5_CENTER, "[camas]") :],
            load_center,
            "[destino]",
        ),
    ],
)
def test_un_bloque_a_medias_dentro_de_un_fichero_es_un_error(tmp_path, name, text, loader, key):
    # Lo detecta la carga (tarea 5.2), antes de que choose_model vea nada: se comprueba
    # aquí para que la lista de «cada bloque a medias» esté entera en un sitio.
    path = write(tmp_path, name, text)

    with pytest.raises(ValueError) as error:
        loader(path)

    message = str(error.value)
    assert message.startswith(f"{path}:")
    assert key in message
