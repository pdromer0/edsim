# El ejemplo a mano de la tarea 1.3; ver test_mm1_metrics.py.
from test_mm1_metrics import HAND_RECORDS

from edsim.queueing.report import format_records


def test_format_records_ejemplo_a_mano():
    lines = format_records(HAND_RECORDS).splitlines()

    assert lines[0].split() == [
        "cliente",
        "llegada",
        "servicio",
        "inicio",
        "fin",
        "espera",
        "estancia",
    ]
    assert len(lines) == 1 + len(HAND_RECORDS)
    assert lines[2].split() == ["1", "2.500", "2.000", "3.000", "5.000", "0.500", "2.500"]
    # El cliente 3 está en servicio al final: no tiene fin ni estancia.
    assert lines[4].split() == ["3", "7.000", "4.000", "7.000", "—", "0.000", "—"]


def test_format_records_limite():
    lines = format_records(HAND_RECORDS, limit=2).splitlines()

    assert len(lines) == 1 + 2 + 1
    assert lines[-1] == "… (2 clientes más)"
