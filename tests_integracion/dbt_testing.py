"""Lo común de los tests de dbt contra Postgres: lanzar dbt y los datos de la punta a punta.

dbt vive en otro entorno (`analitica/.venv`, con su propio `uv.lock`): se lanza con
`uv run --locked` desde `analitica/`, que lo sincroniza si hace falta, y sin el `VIRTUAL_ENV`
del núcleo. La conexión sale de la URL de la base, en las variables de `profiles.yml`: dbt nunca
prueba contra la base `edsim`.
"""

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

from edsim.live.directo import REPLAY, RecordInfo, RunEnd, RunInfo, RunStart
from edsim.live.messages import run_end_json, run_start_json
from edsim.live.topics import PATIENT_EVENTS, RESOURCE_EVENTS, RUNS
from edsim.runs import RunStore, record_run, simulate_run
from edsim.store.bronze import LOG_APPEND_TIME, KafkaMessage, to_row
from edsim.store.consumer import save_batch
from edsim.store.postgres import PostgresBronze, connect

ROOT = Path(__file__).resolve().parents[1]
ANALITICA = ROOT / "analitica"
CONFIG = ROOT / "config"

DBT_TIMEOUT = 240.0
"""Segundos para `uv run dbt build`, con la sincronización de `analitica/.venv` si falta: 121 s
medidos en frío en el portátil (la descarga de dbt) y 5 s con el entorno ya hecho.
`scripts/tests-integracion.sh` sincroniza antes; el margen es para lanzar un test solo."""


def dbt_env(url: str) -> dict[str, str]:
    """El entorno de dbt: el del proceso, sin `VIRTUAL_ENV` ni las variables `DBT_*` (un
    `DBT_PROFILES_DIR` o un `DBT_TARGET` heredados llevarían dbt a otro perfil o a otra base), y
    con la conexión de `url`."""
    parts = urlsplit(url)
    env = {
        key: value
        for key, value in os.environ.items()
        if key != "VIRTUAL_ENV" and not key.startswith("DBT_")
    }
    env.update(
        EDSIM_PG_HOST=parts.hostname or "localhost",
        EDSIM_PG_PUERTO=str(parts.port or 5432),
        EDSIM_PG_USUARIO=unquote(parts.username or ""),
        EDSIM_PG_CLAVE=unquote(parts.password or ""),
        EDSIM_PG_BASE=parts.path.lstrip("/"),
    )
    return env


@dataclass(frozen=True)
class DbtRun:
    """Lo que dejó una orden de dbt: su salida y el estado de cada nodo de `run_results.json`."""

    returncode: int
    output: str
    status: dict[str, str]

    def of(self, kind: str) -> dict[str, str]:
        """Los nodos de un tipo (`model`, `seed`, `test`, `unit_test`), por su nombre corto."""
        return {
            uid.rsplit(".", 1)[1]: s for uid, s in self.status.items() if uid.startswith(f"{kind}.")
        }


def run_dbt(url: str, args: list[str], folder: Path) -> DbtRun:
    """`uv run --locked dbt <args>` en `analitica/`, con sus ficheros en `folder`.

    Falla el test si no se encuentra `uv`. El código de salida no basta para dar por buena una
    construcción: con un selector mal escrito, dbt no ejecuta nada y sale con 0. Por eso devuelve
    también el estado de cada nodo.
    """
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("No se encuentra uv en el PATH: dbt se lanza con «uv run».")
    target = folder / "target"
    result = subprocess.run(
        [uv, "run", "--locked", "dbt", *args]
        + ["--target-path", str(target), "--log-path", str(folder / "logs")],
        cwd=ANALITICA,
        env=dbt_env(url),
        capture_output=True,
        text=True,
        check=False,
        timeout=DBT_TIMEOUT,
    )
    results = target / "run_results.json"
    status = (
        {r["unique_id"]: r["status"] for r in json.loads(results.read_text())["results"]}
        if results.exists()
        else {}
    )
    return DbtRun(result.returncode, result.stdout[-6000:] + result.stderr[-2000:], status)


# --- Los datos de la punta a punta ---------------------------------------------------------------

RUN_ID = "e2e"
DAYS = 3
WARMUP_DAYS = 1
SEED = 2026
"""La semilla de la ejecución y de lo registrado. La del registro realista se eligió en el plan de
la 8.5 porque deja llegadas duplicadas dentro de la ventana (con la 3 o la 7 no las hay, y V11 no
se vería); `test_punta_a_punta.py` comprueba que las hay."""
START_DATE = date(2026, 1, 5)
"""`fecha_inicio` de `config/llegadas.toml`: el minuto 0 de la ejecución."""
PROFILES = ("limpio", "realista")
FIRST_MS = (
    1_767_225_600_000  # 2026-01-01T00:00:00Z: la marca LogAppendTime de la primera publicación
)


def derived(profile: str) -> str:
    return f"{RUN_ID}_{profile}_s{SEED}"


def simulate_and_record(root: Path) -> RunStore:
    """La ejecución de 3 días con la configuración de `config/` y lo registrado con dos perfiles."""
    simulate_run(
        CONFIG / "centro.toml",
        CONFIG / "llegadas.toml",
        DAYS,
        SEED,
        output_dir=root / RUN_ID,
        run_id=RUN_ID,
        warmup_days=WARMUP_DAYS,
        origin="cli",
        profiles=CONFIG / "perfiles.toml",
    )
    store = RunStore(root)
    for profile in PROFILES:
        record_run(store, RUN_ID, profile, SEED, profiles_file=CONFIG / "registro_clinico.toml")
    return store


def recorded_lines(store: RunStore, profile: str) -> list[str]:
    path = store.root / RUN_ID / "registros" / f"{profile}-s{SEED}" / "registrado.jsonl"
    return [line for line in path.read_text(encoding="utf-8").split("\n") if line]


def publish(url: str, store: RunStore, profile: str, started_ms: int) -> int:
    """Mete en bronce, sin Kafka, lo registrado de un perfil como lo dejaría el consumidor.

    Un `inicio` completo, el de una reemisión (`replay`, W = 1440 y H = 4320, con el bloque
    `registro`), una fila por línea de `registrado.jsonl` y un `fin`, cada mensaje con la marca
    `started_ms` más su posición. A diferencia de una reemisión, escribe lo registrado entero,
    también el calentamiento: los cinco indicadores van por la ventana (D1 de la 8.5).
    Devuelve las líneas escritas.
    """
    lines = recorded_lines(store, profile)
    run_id = derived(profile)
    info = RunInfo(
        run_id=run_id,
        mode=REPLAY,
        schema_version=json.loads(lines[0])["schema_version"],
        seed=SEED,
        start_date=START_DATE,
        anchored=False,
        record=RecordInfo(RUN_ID, profile, SEED),
    )
    start = RunStart(info, WARMUP_DAYS * 1440.0, DAYS * 1440.0, "max", 0, 0)
    end = RunEnd(run_id, "horizonte", DAYS * 1440.0, json.loads(lines[-1])["event_id"], len(lines))
    messages = [
        KafkaMessage(
            RUNS, 0, started_ms, LOG_APPEND_TIME, started_ms, run_start_json(start).encode()
        )
    ]
    for position, line in enumerate(lines, start=1):
        topic = RESOURCE_EVENTS if json.loads(line)["episode_id"] is None else PATIENT_EVENTS
        stamp = started_ms + position
        messages.append(KafkaMessage(topic, 0, stamp, LOG_APPEND_TIME, stamp, line.encode()))
    stamp = started_ms + len(lines) + 1
    messages.append(
        KafkaMessage(RUNS, 0, stamp, LOG_APPEND_TIME, stamp, run_end_json(end).encode())
    )
    batch = [(message, to_row(message)) for message in messages]
    with connect(url) as connection:
        for at in range(0, len(batch), 1000):
            save_batch(PostgresBronze(connection), batch[at : at + 1000])
    return len(lines)
