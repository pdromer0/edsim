"""El truco del dado: lo del realista está dentro de lo del hostil con la misma semilla (7.2).

Cada test dice qué error pilla. Se registra el mismo log verdadero (1.500 pacientes, 10.515
eventos, horizonte de 20 días para que ningún despiste caiga más allá del corte) con los perfiles
reales y el dado por defecto de la semilla, y se compara la libreta hecho a hecho.

La inclusión, tal como sale de las tasas del fichero (ver el plan de la 7.2):

- lo olvidado en el realista está olvidado en el hostil;
- entre los hechos escritos en los dos: el retraso, el valor erróneo y el duplicado del realista
  están en el hostil;
- el vacío y el erróneo, en unión: `destino` es el único campo de dos eventos, y donde el hostil
  mete un valor erróneo ya no queda campo que vaciar;
- la corrección va **al revés**: el hostil corrige menos (0,3 frente a 0,5).
"""

import pytest
from registro_factory import PROFILES_FILE, RUN, patient_log

from edsim.clinical_record import (
    CORRECTION,
    CORRECTION_PENDING,
    DUPLICATE,
    LOST,
    load_record_profiles,
    record,
)

HORIZON = 20 * 1440.0
SEEDS = [2026, 7]
MINIMUM = {"olvidado": 25, "erroneo": 30, "vacio": 50, "duplicado": 20, "corregido": 10}
"""Lo que el realista tiene que dar como mínimo en este log: el test no pasa vacío."""


@pytest.fixture(scope="module")
def events():
    return patient_log(1500)


@pytest.fixture(scope="module")
def profiles():
    return load_record_profiles(PROFILES_FILE)


@pytest.fixture(scope="module")
def recordings(events, profiles):
    """`{(perfil, semilla): flags por hecho}` con el dado por defecto de cada semilla."""
    out = {}
    for seed in SEEDS:
        for name in ("limpio", "realista", "hostil"):
            recording = record(events, profiles[name], seed, horizon=HORIZON, run_id=RUN)
            out[name, seed] = flags(recording)
    return out


def flags(recording) -> dict[str, set[str]]:
    """Por hecho verdadero, los despistes que dice la libreta."""
    facts: dict[str, set[str]] = {}
    for row in recording.notebook:
        found = facts.setdefault(row.fact_id, set())
        if row.kind == LOST:
            found.add("olvidado")
        elif row.kind == DUPLICATE:
            found.add("duplicado")
        elif row.kind in (CORRECTION, CORRECTION_PENDING):
            found.add("corregido")
        else:
            if row.delay_min:
                found.add("retraso")
            if row.wrong_field:
                found.add("erroneo")
            if row.empty_field:
                found.add("vacio")
    return facts


def having(facts: dict[str, set[str]], flag: str) -> set[str]:
    return {fact for fact, found in facts.items() if flag in found}


@pytest.mark.parametrize("seed", SEEDS)
def test_el_realista_da_de_cada_despiste_y_el_hostil_mas(recordings, seed):
    """Pilla un test vacío: si el realista no tuviera despistes, toda inclusión sería trivial."""
    realistic, hostile = recordings["realista", seed], recordings["hostil", seed]
    for flag, minimum in MINIMUM.items():
        assert len(having(realistic, flag)) >= minimum, flag
    for flag in ("olvidado", "erroneo", "vacio", "duplicado", "retraso"):
        assert len(having(hostile, flag)) > len(having(realistic, flag)), flag


@pytest.mark.parametrize("seed", SEEDS)
def test_los_mismos_hechos_con_cualquier_perfil(recordings, seed):
    """Pilla un perfil que cambia la verdad: los hechos de la libreta son los del log."""
    assert set(recordings["limpio", seed]) == set(recordings["realista", seed])
    assert set(recordings["realista", seed]) == set(recordings["hostil", seed])


@pytest.mark.parametrize("seed", SEEDS)
def test_lo_olvidado_en_el_realista_esta_olvidado_en_el_hostil(recordings, seed):
    """Pilla un dado distinto por perfil (V7): el olvido del realista no coincide con el hostil."""
    realistic, hostile = recordings["realista", seed], recordings["hostil", seed]
    assert having(realistic, "olvidado") <= having(hostile, "olvidado")


@pytest.mark.parametrize("flag", ["retraso", "erroneo", "duplicado"])
@pytest.mark.parametrize("seed", SEEDS)
def test_el_retraso_el_erroneo_y_el_duplicado_del_realista_estan_en_el_hostil(
    recordings, seed, flag
):
    """Pilla un dado distinto por perfil (V7), entre los hechos escritos en los dos perfiles."""
    realistic, hostile = recordings["realista", seed], recordings["hostil", seed]
    written_in_both = set(realistic) - having(hostile, "olvidado")
    assert having(realistic, flag) & written_in_both <= having(hostile, flag)


@pytest.mark.parametrize("seed", SEEDS)
def test_un_valor_alterado_del_realista_esta_alterado_en_el_hostil(recordings, seed):
    """Pilla un dado distinto (V7): vacío o erróneo, en unión, porque `destino` es un solo campo."""
    realistic, hostile = recordings["realista", seed], recordings["hostil", seed]
    written_in_both = set(realistic) - having(hostile, "olvidado")

    def altered(facts):
        return having(facts, "vacio") | having(facts, "erroneo")

    assert altered(realistic) & written_in_both <= altered(hostile)


@pytest.mark.parametrize("seed", SEEDS)
def test_el_vacio_del_realista_se_pierde_en_el_hostil_solo_si_ya_hay_un_erroneo(recordings, seed):
    """Pilla una unión que esconde un fallo: si el vacío desaparece, el hostil tiene un erróneo.

    Es la salvedad del criterio: un evento con un solo campo (`destino`) no puede tener a la vez
    un valor erróneo y un campo vacío.
    """
    realistic, hostile = recordings["realista", seed], recordings["hostil", seed]
    written_in_both = set(realistic) - having(hostile, "olvidado")
    lost_empties = (having(realistic, "vacio") & written_in_both) - having(hostile, "vacio")
    assert lost_empties, "la salvedad tiene que ocurrir: el test no puede pasar vacío"
    assert lost_empties <= having(hostile, "erroneo")


@pytest.mark.parametrize("seed", SEEDS)
def test_la_correccion_va_al_reves_el_hostil_corrige_menos(recordings, seed):
    """Pilla una inclusión puesta en el sentido que no es: 0,3 en el hostil y 0,5 en el realista.

    Entre los hechos erróneos en los dos perfiles, lo corregido en el hostil está corregido en el
    realista. Con la misma tirada, `u_correccion` < 0,3 implica `u_correccion` < 0,5.
    """
    realistic, hostile = recordings["realista", seed], recordings["hostil", seed]
    wrong_in_both = having(realistic, "erroneo") & having(hostile, "erroneo")
    corrected_in_hostile = having(hostile, "corregido") & wrong_in_both
    assert corrected_in_hostile, "tiene que haber alguno: el test no puede pasar vacío"
    assert corrected_in_hostile <= having(realistic, "corregido")
    assert len(having(realistic, "corregido") & wrong_in_both) > len(corrected_in_hostile)


@pytest.mark.parametrize("seed", SEEDS)
def test_el_limpio_no_tiene_ningun_despiste(recordings, seed):
    """Pilla un `limpio` que altera algo: la libreta no puede tener más que hechos sin marcas."""
    assert all(not found for found in recordings["limpio", seed].values())


def test_otra_semilla_otros_despistes_y_los_mismos_hechos(recordings):
    """Pilla una semilla que no llega al dado: dos semillas con los mismos despistes."""
    a, b = recordings["realista", 2026], recordings["realista", 7]
    assert set(a) == set(b)
    assert having(a, "erroneo") != having(b, "erroneo")
    assert having(a, "olvidado") != having(b, "olvidado")
