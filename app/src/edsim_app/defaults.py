"""Default horizons for the catalog's base-center simulation."""

from pathlib import Path

BASE_DAYS = 14
BASE_WARMUP_DAYS = 2

CENTER_PATH = Path("config/centro.toml")
COMPLIANT_CENTER_PATH = Path("config/centro_cumplidor.toml")
PROFILE_PATH = Path("config/llegadas.toml")
CLINICAL_PROFILES_PATH = Path("config/perfiles.toml")
VARIANTS_DIR = Path("resultados/variantes")
SIMULATION_DAYS = 14
SIMULATION_WARMUP_DAYS = 2
