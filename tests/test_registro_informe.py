"""Los textos de `edsim registro comparar` (tarea 7.3).

Cada test dice qué error pilla. El informe solo formatea: aquí se fija, con el escenario L, que
cada número de la especificación sale en su sitio y con su signo, y que lo que falta se escribe
como una raya, no como `None`.
"""

from registro_factory import HORIZON, run_l, scenario_l

from edsim.clinical_record import compare
from edsim.clinical_record.report import format_comparison, format_indicators


def report_l(source="ficheros") -> str:
    recording = run_l()
    comparison = compare(scenario_l(), recording.records, recording.notebook, horizon=HORIZON)
    return format_comparison(
        comparison,
        run_id="r2026",
        derived_run_id="r2026_prueba_s7",
        profile="prueba",
        seed=7,
        source=source,
    )


def test_el_informe_del_escenario_l_entero():
    """El texto completo: la cuenta de la especificación (6 hechos, 7 registros), el retraso del
    triaje, y la tabla con 4,2 frente a 6,2, la media 1/3 frente a 13/24 y el nivel 3 frente a 4.
    Pilla una cifra en la fila equivocada, un signo que falta o una frase que se pierde."""
    assert report_l() == (
        "Comparación de r2026 · perfil prueba · semilla 7\n"
        "Ejecución derivada: r2026_prueba_s7 · lo registrado sale de ficheros\n"
        "\n"
        "Conciliación (la cuenta cuadra):\n"
        "  hechos de la verdad 6 = 4 bien + 1 con despistes + 1 perdidos + 0 pendientes al corte\n"
        "  registros escritos 7 = 4 bien + 1 con despistes + 1 duplicados + 1 correcciones\n"
        "  correcciones pendientes al corte: 0\n"
        "  con despistes (1): reloj 1 · retraso 1 · valor erróneo 1 · campo vacío 0 "
        "(se solapan) · solo reloj 0 (0.0 %)\n"
        "\n"
        "Retraso por sistema (registro menos hecho, de lo escrito para su propio hecho):\n"
        "    admisión: n = 3 · mediana 0 min · p90 0 min\n"
        "    triaje: n = 1 · mediana 7 min · p90 7 min\n"
        "    HIS: n = 1 · mediana 0 min · p90 0 min\n"
        "    laboratorio: n = 0\n"
        "\n"
        "Indicadores ingenuos (primer registro de cada tipo, sin vacíos ni correcciones):\n"
        "  Indicador                                  Verdad  Registrado  Diferencia\n"
        "  Tiempo hasta el triaje (mediana, min)         4.2         6.2          +2\n"
        "  Tiempo hasta el médico (mediana, min)          40          40           0\n"
        "  Pacientes en urgencias (media por hora)  0.333333    0.541667   +0.208333\n"
        "  Llegadas (registros de llegada)                 2           2           0\n"
        "  Nivel 1 en el triaje (%)                        0           0           0\n"
        "  Nivel 2 en el triaje (%)                        0           0           0\n"
        "  Nivel 3 en el triaje (%)                      100           0        -100\n"
        "  Nivel 4 en el triaje (%)                        0         100        +100\n"
        "  Nivel 5 en el triaje (%)                        0           0           0\n"
    ).rstrip("\n")


def test_el_origen_de_lo_registrado_sale_en_la_cabecera():
    """Con `--postgres` el informe dice que lo registrado sale de Postgres: quien lo lee sabe
    de dónde vienen los números."""
    assert "lo registrado sale de Postgres (postgresql://u:***@h/db)" in report_l(
        "Postgres (postgresql://u:***@h/db)"
    )


def test_lo_que_no_se_puede_calcular_se_escribe_como_una_raya():
    """Una ejecución sin triajes: los indicadores sin valor salen como «—», nunca «None», y su
    diferencia también."""
    comparison = compare([], [], [], horizon=120.0)

    table = format_indicators(comparison)

    assert "None" not in table
    first = next(line for line in table.splitlines() if "Tiempo hasta el triaje" in line)
    assert first.split()[-3:] == ["—", "—", "—"]
    assert "Llegadas (registros de llegada)" in table
