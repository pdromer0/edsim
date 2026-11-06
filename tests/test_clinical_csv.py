"""El CSV del ground truth de episodios con el modelo clínico (tarea 4.5b).

Todo lo que tiene un EpisodeTruth clínico va al CSV, incluidos la z de la gravedad y los
12 sorteos de las pruebas, de modo que leerlo da el mismo EpisodeTruth, floats bit a bit.
El CSV del modelo provisional no cambia: su huella está en test_cli_characterization.py.
"""

import csv
import dataclasses
from dataclasses import asdict
from pathlib import Path

import pytest
from clinical_factory import PLAIN, hand_truth, leaves, ordered_of

from edsim.arrivals.profile import load_profile
from edsim.engine.center import load_center
from edsim.engine.engine import simulate_ed
from edsim.engine.events import MemorySink
from edsim.engine.ground_truth import EpisodeTruth
from edsim.engine.report import (
    CLINICAL_EPISODE_COLUMNS,
    EPISODE_COLUMNS,
    ProfilesParameters,
    RunParameters,
    episode_from_row,
    read_episodes_csv,
    write_episodes_csv,
    write_ground_truth_days_csv,
)
from edsim.profiles.config import load_profiles
from edsim.profiles.context import ArrivalContext

DATA = Path(__file__).parent / "data"
SEED = 2026
DAYS = 3

PARAMETERS = RunParameters(
    center="tests/data/centro_ejemplo.toml",
    center_fingerprint="5b86440058ee",
    profile="tests/data/llegadas_ejemplo.toml",
    profile_fingerprint="63d0ae1fb4f0",
    days=DAYS,
    warmup_days=1,
    seed=SEED,
    run_id="r2026",
)
PROFILES = ProfilesParameters(
    profiles="tests/data/perfiles_ejemplo.toml", profiles_fingerprint="0123456789ab"
)


@pytest.fixture(scope="module")
def runs():
    """La ejecución de ejemplo de 3 días con los dos modelos, la misma semilla."""
    center = load_center(DATA / "centro_ejemplo.toml")
    arrivals = load_profile(DATA / "llegadas_ejemplo.toml")
    profiles = load_profiles(DATA / "perfiles_ejemplo.toml")
    clinical = simulate_ed(center, arrivals, DAYS, SEED, sink=MemorySink(), profiles=profiles)
    provisional = simulate_ed(center, arrivals, DAYS, SEED, sink=MemorySink())
    return clinical.ground_truth, provisional.ground_truth


def read_rows(path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


# --- Cabeceras literales ----------------------------------------------------------------


def test_cabecera_literal_del_csv_clinico():
    assert CLINICAL_EPISODE_COLUMNS == (
        "episodio",
        "llegada",
        "minuto_llegada",
        "nivel",
        "triaje",
        "valoracion",
        "reevaluacion",
        "pruebas",
        "respuesta_pruebas",
        "destino",
        "franja",
        "tipo_dia",
        "estacion",
        "banda",
        "edad",
        "sexo",
        "medio",
        "motivo",
        "z_gravedad",
        "gravedad",
        "nivel_real",
        "calidad_triaje",
        "salto",
        "pedida_analitica",
        "pedida_radiografia",
        "pedida_ecg",
        "pedida_imagen",
        "alterada_analitica",
        "alterada_radiografia",
        "alterada_ecg",
        "alterada_imagen",
        "respuesta_base_analitica",
        "respuesta_base_radiografia",
        "respuesta_base_ecg",
        "respuesta_base_imagen",
        "sorteo_pedida_analitica",
        "sorteo_alterada_analitica",
        "sorteo_respuesta_analitica",
        "sorteo_pedida_radiografia",
        "sorteo_alterada_radiografia",
        "sorteo_respuesta_radiografia",
        "sorteo_pedida_ecg",
        "sorteo_alterada_ecg",
        "sorteo_respuesta_ecg",
        "sorteo_pedida_imagen",
        "sorteo_alterada_imagen",
        "sorteo_respuesta_imagen",
        "centro",
        "huella_centro",
        "llegadas",
        "huella_llegadas",
        "dias",
        "calentamiento",
        "semilla",
        "run_id",
        "perfiles",
        "huella_perfiles",
    )
    assert len(CLINICAL_EPISODE_COLUMNS) == 57


def test_cabecera_literal_del_csv_provisional_sin_cambios(runs, tmp_path):
    # La del hito 3, sin las columnas de los perfiles.
    expected = (
        "episodio,llegada,minuto_llegada,nivel,triaje,valoracion,reevaluacion,pruebas,"
        "respuesta_pruebas,destino,centro,huella_centro,llegadas,huella_llegadas,dias,"
        "calentamiento,semilla,run_id"
    )
    _, provisional = runs
    path = tmp_path / "episodios.csv"
    write_episodes_csv(provisional.episodes, path, PARAMETERS)

    assert path.read_text(encoding="utf-8").splitlines()[0] == expected
    assert ",".join(EPISODE_COLUMNS) == expected


# --- Una fila a mano --------------------------------------------------------------------


def hand_episode():
    """Un paciente de tarde con analítica (alterada) y ECG, sorteos distintos entre sí."""
    truth = hand_truth(
        level=3,
        true_level=2,
        ordered=ordered_of("analitica", "ecg"),
        abnormal=ordered_of("analitica"),
        reason="dolor_toracico",
        age=67,
        female=False,
        ambulance=True,
    )
    truth = dataclasses.replace(
        truth,
        context=ArrivalContext(shift_band=1, day_type=0, season=0),
        workup=dataclasses.replace(
            truth.workup,
            draws=(0.125, 0.5, -1.25, 0.75, 0.875, 0.5, 0.0625, 0.25, 2.0, 0.9375, 0.375, -0.5),
        ),
    )
    return EpisodeTruth(
        episode_id="EP-000007",
        arrival_id=7,
        arrival_time=901.5,
        level=3,
        triage_time=6.25,
        assessment_time=31.5,
        reassessment_time=12.75,
        needs_tests=True,
        test_turnaround=None,
        admitted=True,
        clinical=truth,
    )


def test_fila_a_mano(tmp_path):
    path = tmp_path / "episodios.csv"
    write_episodes_csv([hand_episode()], path, PARAMETERS, PROFILES)

    (header, row) = read_rows(path)
    assert tuple(header) == CLINICAL_EPISODE_COLUMNS
    # Las bases son las de hand_truth (75, 70, 12 y 200 minutos): factor 1, sin la franja
    # de la llegada (tarde) ni la del pedido.
    assert ",".join(row) == (
        "EP-000007,7,901.5,3,6.25,31.5,12.75,True,,ingreso,"
        "tarde,laborable,invierno,2,67,hombre,ambulancia,dolor_toracico,"
        "0.25,0.5,2,infratriaje,1,"
        "True,False,True,False,"
        "True,False,False,False,"
        "75.0,70.0,12.0,200.0,"
        "0.125,0.5,-1.25,0.75,0.875,0.5,0.0625,0.25,2.0,0.9375,0.375,-0.5,"
        "tests/data/centro_ejemplo.toml,5b86440058ee,tests/data/llegadas_ejemplo.toml,"
        "63d0ae1fb4f0,3,1,2026,r2026,tests/data/perfiles_ejemplo.toml,0123456789ab"
    )
    assert read_episodes_csv(path) == (hand_episode(),)


# --- Ida y vuelta -----------------------------------------------------------------------


def test_ida_y_vuelta_del_csv_clinico(runs, tmp_path):
    clinical, _ = runs
    path = tmp_path / "episodios.csv"
    write_episodes_csv(clinical.episodes, path, PARAMETERS, PROFILES)

    read = read_episodes_csv(path)

    assert read == clinical.episodes
    assert len(read) == 1101
    # Guardas: la ida y vuelta cubre las tres franjas y pacientes con y sin pruebas, con
    # una prueba y con varias.
    assert {e.clinical.context.shift_band for e in read} == {0, 1, 2}
    rounds = [sum(e.clinical.workup.ordered) for e in read]
    assert 0 in rounds and 1 in rounds and max(rounds) >= 2


def test_lo_leido_solo_tiene_tipos_de_python(runs, tmp_path):
    # type(x), no isinstance: un np.float64 o un np.bool_ leídos pasarían por iguales.
    clinical, _ = runs
    path = tmp_path / "episodios.csv"
    write_episodes_csv(clinical.episodes, path, PARAMETERS, PROFILES)

    workup = set()
    for e in read_episodes_csv(path):
        for where, value in leaves(asdict(e)):
            assert type(value) in PLAIN, (e.episode_id, where, type(value))
            if where[:2] == ("clinical", "workup"):
                workup.add(where[2:])
    # Guarda: el recorrido llega a los 12 sorteos de las pruebas.
    assert {p for p in workup if p[0] == "draws"} == {("draws", i) for i in range(12)}


def test_ida_y_vuelta_del_csv_provisional(runs, tmp_path):
    _, provisional = runs
    path = tmp_path / "episodios.csv"
    write_episodes_csv(provisional.episodes, path, PARAMETERS)

    assert read_episodes_csv(path) == provisional.episodes


def test_el_csv_de_dias_es_el_mismo_con_los_dos_modelos(runs, tmp_path):
    # Las llegadas no dependen de los perfiles: los registros de los días tampoco.
    clinical, provisional = runs
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    write_ground_truth_days_csv(clinical.days, a, PARAMETERS)
    write_ground_truth_days_csv(provisional.days, b, PARAMETERS)

    assert a.read_bytes() == b.read_bytes()


# --- Errores del escritor, antes de crear el fichero -------------------------------------


@pytest.mark.parametrize(
    "case, message",
    [
        ("clinico_sin_perfiles", "needs the profiles"),
        ("provisional_con_perfiles", "provisional model"),
        ("respuesta_inventada", "test_turnaround must be None"),
        ("otro_nivel", "not the assigned one"),
        ("pruebas_incoherentes", "needs_tests"),
    ],
)
def test_errores_del_escritor_sin_crear_el_fichero(runs, tmp_path, case, message):
    _, provisional = runs
    episode = hand_episode()
    profiles = PROFILES
    match case:
        case "clinico_sin_perfiles":
            episodes, profiles = [provisional.episodes[0], episode], None
        case "provisional_con_perfiles":
            episodes = [episode, provisional.episodes[0]]
        case "respuesta_inventada":
            episodes = [dataclasses.replace(episode, test_turnaround=75.0)]
        case "otro_nivel":
            episodes = [dataclasses.replace(episode, level=4)]
        case "pruebas_incoherentes":
            episodes = [dataclasses.replace(episode, needs_tests=False)]
    path = tmp_path / "episodios.csv"

    with pytest.raises(ValueError, match=message):
        write_episodes_csv(episodes, path, PARAMETERS, profiles)
    assert not path.exists()


# --- Errores del lector -----------------------------------------------------------------


def hand_row():
    return dict(
        zip(
            CLINICAL_EPISODE_COLUMNS,
            (
                "EP-000007,7,901.5,3,6.25,31.5,12.75,True,,ingreso,"
                "tarde,laborable,invierno,2,67,hombre,ambulancia,dolor_toracico,"
                "0.25,0.5,2,infratriaje,1,True,False,True,False,True,False,False,False,"
                "75.0,70.0,12.0,200.0,"
                "0.125,0.5,-1.25,0.75,0.875,0.5,0.0625,0.25,2.0,0.9375,0.375,-0.5,"
                "c,h,l,h,3,1,2026,r2026,p,h"
            ).split(","),
            strict=True,
        )
    )


def test_la_fila_a_mano_se_lee():
    assert episode_from_row(hand_row()) == hand_episode()


@pytest.mark.parametrize(
    "column, value, message",
    [
        ("respuesta_pruebas", "75.0", "must be empty"),
        ("franja", "mañana", "franja"),
        ("tipo_dia", "festivo", "tipo_dia"),
        ("sexo", "Mujer", "sexo"),
        ("medio", "ambulance", "medio"),
        ("motivo", "otro", "motivo"),
        ("pedida_ecg", "true", "pedida_ecg"),
        ("alterada_imagen", "1", "alterada_imagen"),
        ("edad", "67.0", "edad"),
        ("banda", "4", "banda"),
        ("nivel_real", "6", "nivel_real"),
        ("calidad_triaje", "correcto", "do not match"),
        ("salto", "2", "do not match"),
        ("pruebas", "False", "pedida_"),
        ("z_gravedad", "nan", "z_gravedad"),
        ("respuesta_base_ecg", "-1.0", "respuesta_base_ecg"),
        ("sorteo_respuesta_imagen", "inf", "sorteo_respuesta_imagen"),
        ("episodio", "EP-000008", "episodio"),
    ],
)
def test_errores_del_lector(column, value, message):
    row = hand_row() | {column: value}

    with pytest.raises(ValueError, match=message):
        episode_from_row(row)


def test_el_lector_exige_la_cabecera_y_los_mismos_parametros(runs, tmp_path):
    clinical, _ = runs
    path = tmp_path / "episodios.csv"
    write_episodes_csv(clinical.episodes[:3], path, PARAMETERS, PROFILES)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)

    other = tmp_path / "otro.csv"
    other.write_text(lines[0].replace("huella_perfiles", "huella"), encoding="utf-8")
    with pytest.raises(ValueError, match=f"{other}:1: invalid episode ground truth header"):
        read_episodes_csv(other)
    other.write_text(
        "".join([*lines[:3], lines[3].replace("0123456789ab", "ba9876543210")]), encoding="utf-8"
    )
    with pytest.raises(ValueError, match=f"{other}:4: the run parameters change"):
        read_episodes_csv(other)
