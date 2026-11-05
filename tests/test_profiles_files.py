"""Los ficheros de perfiles: config/perfiles.toml y su copia fija de ejemplo."""

import dataclasses
import re
from pathlib import Path

import numpy as np
import pytest

from edsim.arrivals.profile import load_profile
from edsim.profiles.config import REASON_KEYS, REASONS, ClinicalProfiles, load_profiles
from edsim.profiles.durations import physician_load
from edsim.profiles.mixing import base_weights_for, catalog_shares, global_reason_shares
from edsim.profiles.population import global_band_shares, share_65_plus
from edsim.profiles.severity import (
    assigned_shares,
    reason_year_means,
    severity_mixture,
    thresholds_for,
    triage_error_for,
    triage_error_rates,
    triage_matrix,
)
from edsim.profiles.workup import workup_model

ROOT = Path(__file__).parents[1]
EXAMPLE = Path(__file__).parent / "data" / "perfiles_ejemplo.toml"
REAL = ROOT / "config" / "perfiles.toml"
ARRIVALS = {
    EXAMPLE: Path(__file__).parent / "data" / "llegadas_ejemplo.toml",
    REAL: ROOT / "config" / "llegadas.toml",
}
FILES = pytest.mark.parametrize("path", [EXAMPLE, REAL], ids=["ejemplo", "real"])


# Grupos de la columna «Gravedad típica» del catálogo de docs/diseno.md, de más a
# menos grave. Los motivos «variable» no tienen sitio en el orden.
SEVERITY_GROUPS = (
    ("parada",),  # muy alta
    ("disnea", "dolor_toracico"),  # media-alta
    ("dolor_abdominal", "malestar", "sincope", "psiquiatrico", "palpitaciones"),  # media
    ("fiebre", "urologico"),  # baja-media
    ("traumatismo", "cutaneo", "orl", "otros"),  # baja
)
VARIABLE = ("neurologico", "digestivo", "intoxicacion")


@pytest.fixture(scope="module")
def example() -> ClinicalProfiles:
    return load_profiles(EXAMPLE)


def mixture_of(path):
    return severity_mixture(load_profiles(path), load_profile(ARRIVALS[path]))


@FILES
def test_carga(path):
    profiles = load_profiles(path)

    assert profiles.reason_keys == REASON_KEYS
    assert profiles.shift_band_starts == (8, 15, 22)


def test_valores_del_ejemplo(example):
    assert example.population.band_shares == (38.0, 22.0, 22.0, 18.0)
    assert example.population.ambulance_pct == (6.0, 10.0, 21.0, 34.0)
    assert example.reason("disnea").base_weight == 7.388
    assert example.reason("disnea").age_factors == (0.4, 0.8, 1.8, 2.4)
    assert example.reason("disnea").severity.mean == 0.94
    assert example.reason("parada").severity.age_shift == (0.0,) * 4
    # Derivados y calibrados escritos: cargar no los recalcula.
    assert example.triage.thresholds == (3.260, 1.140, -0.044, -2.163)
    assert (example.triage.noise, example.triage.bias) == (0.333, -0.081)
    # Motivos sin factores: todos valen 1.
    for key in ("dolor_abdominal", "digestivo", "otros"):
        r = example.reason(key)
        assert r.age_factors + r.shift_factors + r.day_factors + r.season_factors == (1.0,) * 13
    # Pruebas y duraciones (tarea 4.4), en el orden de TEST_TYPES.
    assert example.reason("dolor_toracico").test_pct == (65.0, 56.0, 96.0, 2.0)
    assert example.reason("parada").test_pct == (36.0, 61.0, 83.0, 4.0)
    assert example.reason("traumatismo").duration_factor == 0.85
    assert example.reason("digestivo").duration_factor == 1.0
    assert example.triage.duration == (5.0, 10.0)
    assert example.durations.assessment[0] == (40.0, 90.0)
    assert example.durations.reassessment[4] == (6.0, 12.0)
    ecg = example.diagnostic_test("ecg")
    assert (ecg.turnaround, ecg.turnaround_shift_factors) == ((10.0, 25.0), (1.0, 1.0, 1.0))
    assert (ecg.severity_or, ecg.older_or) == (2.0, 3.0)
    assert (ecg.abnormal_pct, ecg.abnormal_severity_or) == (20.0, 2.0)


@FILES
def test_reparto_global_dentro_de_medio_punto(path):
    # Con los pesos base escritos (redondeados a 3 decimales), el reparto de un año
    # queda a menos de 0,5 puntos del catálogo; en la tarea 4.2, a 0,00065.
    shares = global_reason_shares(load_profiles(path), load_profile(ARRIVALS[path]))
    deviation = 100 * np.abs(shares - catalog_shares())

    assert deviation.max() < 0.5, dict(zip(REASON_KEYS, deviation.round(3), strict=True))


@FILES
def test_pesos_escritos_iguales_a_los_derivados(path):
    # Si se cambia un factor sin volver a ejecutar base_weights_for, falla.
    profiles = load_profiles(path)
    derived = base_weights_for(profiles, load_profile(ARRIVALS[path]))

    for r in profiles.reasons:
        # Con 3 decimales el redondeo llega a 5e-4 (0,000486 en la tarea 4.2): margen de 1e-3.
        assert r.base_weight == pytest.approx(derived[r.key], abs=1e-3), r.key


@FILES
def test_sin_derivar_se_saldria_del_catalogo(path):
    # Comprueba que el test del reparto global no pasa de forma vacía: con el
    # catálogo como peso base, los factores alejan la intoxicación más de 0,5 puntos.
    profiles = load_profiles(path)
    catalog = {key: weight for key, _, weight in REASONS}
    naive = dataclasses.replace(
        profiles,
        reasons=tuple(dataclasses.replace(r, base_weight=catalog[r.key]) for r in profiles.reasons),
    )
    shares = global_reason_shares(naive, load_profile(ARRIVALS[path]))
    i = REASON_KEYS.index("intoxicacion")

    assert 100 * abs(shares[i] - catalog_shares()[i]) > 0.5


@FILES
def test_mayores_de_65_en_la_horquilla(path):
    # 34-44 % de mayores de 65 años sobre adultos (Gaceta Sanitaria 2018: 27-35 %
    # sobre todas las edades, dividido por 0,79).
    share = share_65_plus(load_profiles(path), load_profile(ARRIVALS[path]))

    assert 0.34 <= share <= 0.44
    assert share == pytest.approx(0.3855, abs=5e-4)


@FILES
def test_ambulancia_en_mayores_de_65(path):
    # 27 % de los mayores de 65 años llega en ambulancia (cohorte EDEN).
    profiles = load_profiles(path)
    shares = global_band_shares(profiles, load_profile(ARRIVALS[path]))
    pct = np.asarray(profiles.population.ambulance_pct)

    older = (shares[2:] * pct[2:]).sum() / shares[2:].sum()

    assert older == pytest.approx(27, abs=0.5)


# --- Gravedad y triaje -----------------------------------------------------------


@FILES
def test_mezcla_de_gravedad_de_media_0_y_desviacion_1(path):
    # La tabla de gravedad se desplazó y escaló para esto (ver el comentario del TOML).
    m = mixture_of(path)

    assert m.mean == pytest.approx(0, abs=0.05)
    assert m.sd == pytest.approx(1, abs=0.05)


@FILES
def test_reparto_asignado_con_los_umbrales_recalculados(path):
    profiles = load_profiles(path)
    t = profiles.triage
    thresholds = thresholds_for(profiles, load_profile(ARRIVALS[path]))

    shares = assigned_shares(mixture_of(path), thresholds, t.noise, t.bias)

    np.testing.assert_allclose(shares, t.target_shares, atol=1e-9)


@FILES
def test_reparto_asignado_con_los_umbrales_escritos(path):
    # Redondeados a 3 decimales: a menos de 0,05 puntos del objetivo (0,015 en la 4.3).
    t = load_profiles(path).triage
    shares = assigned_shares(mixture_of(path), t.thresholds, t.noise, t.bias)

    np.testing.assert_allclose(100 * shares, 100 * np.array(t.target_shares), atol=0.05)


@FILES
def test_infra_y_sobretriaje_en_su_objetivo(path):
    # Con los valores escritos: 10,10 % y 6,28 % en la 4.3.
    t = load_profiles(path).triage
    under, over = triage_error_rates(triage_matrix(mixture_of(path), t.thresholds, t.noise, t.bias))

    assert 100 * under == pytest.approx(t.under_pct, abs=0.05)
    assert 100 * over == pytest.approx(t.over_pct, abs=0.05)


@FILES
def test_umbrales_escritos_iguales_a_los_derivados(path):
    # Si cambia la gravedad, un factor, el ruido o el sesgo sin volver a
    # ejecutar thresholds_for, falla. Con 3 decimales, el redondeo llega a 5e-4.
    profiles = load_profiles(path)
    derived = thresholds_for(profiles, load_profile(ARRIVALS[path]))

    np.testing.assert_allclose(profiles.triage.thresholds, derived, atol=1e-3)


@FILES
def test_ruido_y_sesgo_escritos_iguales_a_los_calibrados(path):
    profiles = load_profiles(path)
    noise, bias = triage_error_for(profiles, load_profile(ARRIVALS[path]))

    assert profiles.triage.noise == pytest.approx(noise, abs=1e-3)
    assert profiles.triage.bias == pytest.approx(bias, abs=1e-3)


@FILES
def test_orden_clinico_de_gravedad(path):
    # La G media de cada motivo en el año (con su mezcla de edades) respeta el
    # orden de los grupos del catálogo: el menos grave de un grupo está por
    # encima del más grave del siguiente.
    means = dict(zip(REASON_KEYS, reason_year_means(mixture_of(path)), strict=True))

    for upper, lower in zip(SEVERITY_GROUPS, SEVERITY_GROUPS[1:], strict=False):
        assert min(means[k] for k in upper) > max(means[k] for k in lower), (upper, lower)


@FILES
def test_los_variables_tienen_mas_desviacion(path):
    sds = {r.key: r.severity.sd for r in load_profiles(path).reasons}
    median = float(np.median(list(sds.values())))

    assert all(sds[k] > median for k in VARIABLE), (median, {k: sds[k] for k in VARIABLE})


def test_shock_con_los_umbrales_escritos(tmp_path):
    # Protege la decisión de escribir los umbrales: un escenario con la disnea
    # ×1,5 (peso base 7,388 → 11,082) se carga con los umbrales del perfil base,
    # y la proporción asignada de nivel 2 sube del 12,09 % al 13,10 %. Si los
    # umbrales se recalcularan al cargar, volvería al 12,09 % y el shock
    # desaparecería.
    text = EXAMPLE.read_text(encoding="utf-8")
    assert text.count("peso_base = 7.388") == 1
    shocked = tmp_path / "perfiles_gripe.toml"
    shocked.write_text(text.replace("peso_base = 7.388", "peso_base = 11.082"), encoding="utf-8")
    profiles = load_profiles(shocked)
    t = profiles.triage
    arrivals = load_profile(ARRIVALS[EXAMPLE])

    base = assigned_shares(mixture_of(EXAMPLE), t.thresholds, t.noise, t.bias)
    shock = assigned_shares(severity_mixture(profiles, arrivals), t.thresholds, t.noise, t.bias)

    assert 100 * base[1] == pytest.approx(12.0852, abs=1e-4)
    assert 100 * shock[1] == pytest.approx(13.0953, abs=1e-4)
    assert 100 * shock[0] == pytest.approx(0.4074, abs=1e-4)  # también más niveles 1


# --- Pruebas: la tabla por motivo (ajuste 1 de la aprobación de la tarea 4.4) ----

# Marginal de un año de cada prueba en cada motivo (% de los pacientes del motivo
# a los que se pide: analítica, radiografía, ECG, imagen), con los p enteros
# escritos en config/perfiles.toml y config/llegadas.toml. Los p del TOML son el
# % para un adulto con G = 0 y se eligieron por esta marginal: si cambian los odds
# ratios, la gravedad, la mezcla o el perfil de llegadas, esta tabla y los
# comentarios del TOML se actualizan juntos.
MARGINALS = {
    "traumatismo": (8.12, 69.71, 4.60, 6.42),
    "dolor_abdominal": (74.96, 19.52, 14.87, 35.05),
    "fiebre": (69.81, 49.61, 10.17, 5.40),
    "disnea": (84.83, 84.95, 65.04, 7.29),
    "malestar": (79.92, 35.37, 59.93, 8.41),
    "dolor_toracico": (84.86, 69.94, 98.18, 5.89),
    "neurologico": (59.66, 7.34, 30.54, 54.64),
    "sincope": (64.89, 14.47, 94.91, 14.94),
    "urologico": (59.99, 20.01, 5.01, 35.46),
    "cutaneo": (9.89, 2.90, 3.20, 1.64),
    "orl": (5.15, 3.72, 2.02, 3.08),
    "digestivo": (69.63, 15.21, 15.59, 15.18),
    "psiquiatrico": (19.75, 2.53, 12.19, 2.89),
    "palpitaciones": (70.05, 25.32, 98.00, 3.70),
    "intoxicacion": (74.66, 8.28, 49.74, 8.44),
    "parada": (97.97, 90.13, 98.97, 40.38),
    "otros": (19.66, 10.40, 8.54, 3.91),
}
GLOBAL_TESTS = (48.08, 37.32, 28.09, 13.14)  # % de los pacientes del año, por tipo
ANY_TEST = 72.79  # % con alguna prueba (frente al 55,41 % del modelo provisional)


@pytest.fixture(scope="module")
def real_workup():
    return workup_model(load_profiles(REAL), load_profile(ARRIVALS[REAL]))


def test_marginales_de_las_pruebas_por_motivo(real_workup):
    # Las 68 marginales (motivo × tipo), exactas, a 0,05 puntos de la tabla.
    exact = 100 * real_workup.order_by_reason()

    assert list(MARGINALS) == list(REASON_KEYS)
    assert exact == pytest.approx(np.array(list(MARGINALS.values())), abs=0.05)


def test_pruebas_globales_y_alguna_prueba(real_workup):
    assert 100 * real_workup.order_shares() == pytest.approx(GLOBAL_TESTS, abs=0.05)
    assert 100 * real_workup.any_test_share() == pytest.approx(ANY_TEST, abs=0.05)


@FILES
def test_comentarios_de_las_marginales_al_dia(path):
    # Cada línea «pruebas = {...}» del TOML lleva su marginal de un año con un
    # decimal; debe ser la exacta de los p enteros escritos, redondeada.
    exact = 100 * workup_model(load_profiles(path), load_profile(ARRIVALS[path])).order_by_reason()
    text = path.read_text(encoding="utf-8")
    pattern = (
        r"\[motivos\.(\w+)\](?:.*\n)*?pruebas = .*# orientativo, elegido por su marginal: (.*) %"
    )
    found = dict(re.findall(pattern, text))

    assert list(found) == list(REASON_KEYS)
    for i, key in enumerate(REASON_KEYS):
        written = [float(x.replace(",", ".")) for x in found[key].split(" / ")]
        assert written == pytest.approx(exact[i], abs=0.05 + 1e-9), key


# --- Duraciones: la regla de los k --------------------------------------------


@FILES
def test_los_k_no_cambian_la_carga_de_valoracion(path):
    # Los k reparten la duración entre motivos sin cambiar la carga de valoración
    # de un año: con los k, a 1 ± 0,05 de la carga sin ellos (regla de la tarea 4.4).
    load = physician_load(load_profiles(path), load_profile(ARRIVALS[path]))

    assert abs(load.k_ratio - 1) <= 0.05
    # Valores escritos en el comentario de config/perfiles.toml.
    assert load.k_ratio == pytest.approx(1.0052, abs=5e-5)
    assert load.mean_k == pytest.approx(0.9905, abs=5e-5)
