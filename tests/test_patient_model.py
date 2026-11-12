"""El modelo que eligen un centro y sus perfiles, para la app (tarea 5.5, H5-2).

Simular pregunta el modelo antes de calcular la carga prevista, que aún no existe con el
hito 5 (issue #103). Si los dos ficheros no casan, el error es el de simular.
"""

from pathlib import Path

import pytest

from edsim.runs import (
    PatientModel,
    RunConfigurationError,
    load_center,
    load_profiles,
    patient_model,
)

DATA = Path(__file__).parent / "data"


@pytest.mark.parametrize(
    ("center", "profiles", "model"),
    [
        ("centro_h5_ejemplo.toml", "perfiles_h5_ejemplo.toml", PatientModel.MILESTONE_5),
        ("centro_ejemplo.toml", "perfiles_ejemplo.toml", PatientModel.MILESTONE_4),
        ("centro_ejemplo.toml", None, PatientModel.PROVISIONAL),
    ],
)
def test_el_modelo_de_los_dos_ficheros(center, profiles, model):
    loaded = None if profiles is None else load_profiles(DATA / profiles)
    assert patient_model(load_center(DATA / center), loaded) is model


def test_un_bloque_del_hito_5_en_un_solo_fichero_es_un_error():
    center = load_center(DATA / "centro_h5_ejemplo.toml")
    with pytest.raises(RunConfigurationError, match="perfiles.toml"):
        patient_model(center, load_profiles(DATA / "perfiles_ejemplo.toml"))


def test_el_error_nombra_los_ficheros_elegidos():
    """Simular pasa sus rutas: el error dice qué ficheros no casan, no «centro.toml»."""
    center = load_center(DATA / "centro_h5_ejemplo.toml")
    with pytest.raises(RunConfigurationError, match="variantes/h5.toml") as error:
        patient_model(
            center,
            load_profiles(DATA / "perfiles_ejemplo.toml"),
            center_file="variantes/h5.toml",
            profiles_file="mis_perfiles.toml",
        )
    assert "mis_perfiles.toml" in str(error.value)
