"""Cifras del SAS (CMBD 2013) y su conversión a adultos.

Valores a mano con los recuentos de la página 30 (30 457 / 208 635 / 989 622 /
1 312 906 / 731 808 urgencias de los niveles 1 a 5) y los menores de cada nivel
(2,65 / 9,60 / 10,38 / 23,78 / 35,90 %). Los adultos de cada nivel son el recuento por
(1 − menores / 100): 29 650 / 188 606 / 886 899 / 1 000 697 / 469 089, en total
2 574 941, y su reparto es 1,15 / 7,32 / 34,44 / 38,86 / 18,22 %. Con niños, 0,93 /
6,37 / 30,23 / 40,11 / 22,36 %.
"""

from pathlib import Path

import pytest

from edsim.calibration import sas
from edsim.calibration.targets import load_targets


def test_reparto_de_adultos_a_mano():
    adults = sas.adult_level_counts()

    assert [round(x) for x in adults] == [29_650, 188_606, 886_899, 1_000_697, 469_089]
    assert round(sum(adults)) == 2_574_941
    assert sas.level_pct(adults) == pytest.approx([1.15, 7.32, 34.44, 38.86, 18.22], abs=0.005)


def test_reparto_con_niños_a_mano():
    shares = sas.level_pct(sas.LEVEL_COUNTS)
    assert shares == pytest.approx([0.93, 6.37, 30.23, 40.11, 22.36], abs=0.005)


def test_quitar_menores_no_es_restar_puntos():
    # Los menores pesan distinto en cada nivel: restar sus puntos al reparto con niños
    # daría otra cosa (y ni siquiera sumaría 100).
    with_children = sas.level_pct(sas.LEVEL_COUNTS)
    subtracted = [p - m for p, m in zip(with_children, sas.MINOR_PCT, strict=True)]

    assert sum(subtracted) != pytest.approx(100, abs=1)
    assert sas.level_pct(sas.adult_level_counts()) != pytest.approx(subtracted, abs=0.5)


def test_los_repartos_suman_cien():
    assert sum(sas.level_pct(sas.adult_level_counts())) == pytest.approx(100, abs=1e-12)


def test_tiempo_hasta_el_medico_por_nivel():
    assert sas.TPAM_BY_LEVEL == (31.7, 35.6, 59.0, 59.8, 68.5)
    assert sas.TPAM_TOTAL == 59.7


def test_el_enlace_es_el_de_los_objetivos():
    targets = load_targets(Path(__file__).parent.parent / "config" / "objetivos.toml")
    assert {t.link for t in targets} == {sas.LINK}
    assert {t.source for t in targets} == {sas.SOURCE}


@pytest.mark.parametrize(
    ("counts", "minors", "message"),
    [
        ((1, 2, 3), sas.MINOR_PCT, "must have 5 values"),
        ((1, 2, 3, 4, -5), sas.MINOR_PCT, "non-negative"),
        (sas.LEVEL_COUNTS, (0, 0, 0, 0, 101), r"in \[0, 100\]"),
    ],
)
def test_argumentos_no_validos(counts, minors, message):
    with pytest.raises(ValueError, match=message):
        sas.adult_level_counts(counts, minors)


def test_reparto_sin_pacientes():
    with pytest.raises(ValueError, match="positive total"):
        sas.level_pct((0, 0, 0, 0, 0))
