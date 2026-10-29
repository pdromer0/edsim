import numpy as np
import pytest

from edsim.seeds import child_streams

SEED = 2026


def states(children) -> list[list[int]]:
    """Primeros números de estado de cada hijo: iguales si y solo si los flujos son iguales."""
    return [c.generate_state(4).tolist() for c in children]


def test_spawn_de_numpy_muta_el_objeto():
    # El motivo de child_streams: spawn avanza un contador interno, así que el mismo
    # SeedSequence da hijos distintos la segunda vez.
    seq = np.random.SeedSequence(SEED)

    assert states(seq.spawn(2)) != states(seq.spawn(2))


@pytest.mark.parametrize("n", [1, 2, 5])
def test_igual_que_spawn_sobre_semilla_nueva(n):
    expected = states(np.random.SeedSequence(SEED).spawn(n))

    assert states(child_streams(SEED, n)) == expected
    assert states(child_streams(np.random.SeedSequence(SEED), n)) == expected


def test_reutilizar_el_mismo_objeto():
    seq = np.random.SeedSequence(SEED)

    first = states(child_streams(seq, 2))
    second = states(child_streams(seq, 2))

    assert first == second
    assert seq.n_children_spawned == 0  # el objeto no se modifica


def test_hijo_de_una_semilla_maestra():
    # Las réplicas pasan hijos de una maestra: sus propios hijos cuelgan de su spawn_key.
    replica = np.random.SeedSequence(SEED).spawn(3)[2]
    expected = states(np.random.SeedSequence(SEED).spawn(3)[2].spawn(2))

    assert states(child_streams(replica, 2)) == expected


def test_semillas_distintas_hijos_distintos():
    assert states(child_streams(1, 2)) != states(child_streams(2, 2))


@pytest.mark.parametrize("n", [0, -1, 1.5, True])
def test_n_invalido(n):
    with pytest.raises(ValueError, match="n must"):
        child_streams(SEED, n)
