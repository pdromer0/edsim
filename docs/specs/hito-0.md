# Hito 0 — Entorno de desarrollo

## Objetivo y alcance

Al terminar el hito 0, Pedro tiene en Windows un entorno de desarrollo reproducible, un repositorio `edsim` en GitHub con todas las comprobaciones de calidad funcionando y Claude Code configurado para el modo de trabajo acordado. El primer pull request se fusiona siguiendo GitHub Flow de principio a fin.

**Dentro del alcance**

- WSL2 con Ubuntu, Docker Desktop, Cursor, uv, git, GitHub CLI y Claude Code.
- Repositorio con estructura de paquete Python, linter, tests, hooks de pre-commit y CI en GitHub Actions.
- `CLAUDE.md`, permisos, hooks y estilo de respuesta de Claude Code.
- Protección de `main` y primer ciclo completo rama → pull request → CI → fusión.
- Documentación inicial en `docs/`: diseño, esta especificación, decisiones y diario.

**Fuera del alcance**

- Código del simulador (empieza en el hito 1).
- Servicios en Docker Compose como Kafka o Postgres (hito 6). Docker Desktop solo se instala y se verifica.

En este hito Pedro ejecuta a mano los comandos de git y GitHub, y Claude Code escribe los ficheros del repositorio en cuanto esté instalado.

## Sesión conceptual

Antes de instalar nada, una sesión para entender qué pieza hace qué. Pedro pregunta hasta tener claro cada punto.

| Tema | Qué hay que entender |
| --- | --- |
| WSL2 | Un Linux real dentro de Windows; por qué el código vive en el sistema de ficheros de Linux (`~/proyectos`) y no en `C:` (`/mnt/c`): rendimiento y permisos |
| uv | Gestor de versiones de Python, entornos virtuales y dependencias; `pyproject.toml`, `uv.lock` y `uv run` |
| Estructura de paquete | Diseño `src/`, paquete instalable y punto de entrada de la CLI |
| ruff, pytest y pre-commit | Tres niveles de comprobación: al editar, al hacer commit y en el CI |
| git y GitHub Flow | Ramas cortas, commits con mensaje estándar, pull requests, `gh` |
| GitHub Actions | Workflow, job y steps; cómo se lee una ejecución fallida |
| Protección de ramas | Qué impide un ruleset y por qué depende de que el repositorio sea público |
| Claude Code | `CLAUDE.md`, permisos, hooks, modo plan y estilos de respuesta |

## Cómo encajan las piezas

Cursor es la única aplicación de trabajo que corre en Windows; el código, Python, git y Claude Code viven dentro de WSL2, igual que en el Linux donde corre el CI.

&#91;embedded content: entorno de desarrollo · Windows y WSL2\]

- **Cursor → WSL:** Cursor se conecta a WSL con su propia extensión Remote WSL, publicada por Anysphere; la de Microsoft no es compatible con Cursor.
- **Claude Code en WSL:** se instala dentro de Ubuntu con el instalador de Linux. En WSL2 admite el sandbox de comandos, que en Windows nativo no está disponible, y no necesita Git for Windows.
- **Extensión de Claude Code en Cursor:** se instala desde el panel de extensiones de Cursor y da el panel gráfico (planes, diffs, menciones de ficheros). La CLI en el terminal integrado sigue disponible para lo que el panel no cubre.
- **Docker:** Docker Desktop corre en Windows y se integra con Ubuntu, de modo que el cliente `docker` funciona desde WSL.

[Instalación de Claude Code](https://code.claude.com/docs/en/setup.md) · [Claude Code en VS Code y Cursor](https://code.claude.com/docs/en/vs-code.md) · [Cursor con WSL](https://forum.cursor.com/t/cant-connect-to-my-wsl/145537)

## Instalación paso a paso

Primero lo que se instala en Windows, después lo que se instala dentro de Ubuntu. Cada paso termina con una comprobación.

### En Windows

1. **WSL2 con Ubuntu.** En PowerShell como administrador:

   ```powershell
   wsl --install -d Ubuntu-24.04
   wsl -l -v   # Ubuntu-24.04 debe aparecer con VERSION 2
   ```

   Al terminar, Ubuntu pide crear un usuario y contraseña de Linux.
2. **Docker Desktop** para Windows, con el motor WSL2. En *Settings → Resources → WSL integration*, activar Ubuntu-24.04.
3. **Cursor** para Windows. Instalar la extensión **Remote WSL de Anysphere** y abrir *Connect to WSL*; la barra inferior debe mostrar "WSL: Ubuntu-24.04".

### Dentro de Ubuntu (terminal de WSL)

4. **Paquetes base:**

   ```bash
   sudo apt update && sudo apt upgrade -y
   sudo apt install -y git curl build-essential jq
   ```

   `jq` lo usan los hooks de Claude Code para leer el JSON que reciben.
5. **Identidad de git:**

   ```bash
   git config --global user.name "Pedro …"
   git config --global user.email "…"
   git config --global init.defaultBranch main
   ```
6. **GitHub CLI**, siguiendo las instrucciones oficiales de GitHub para Debian y Ubuntu, y después:

   ```bash
   gh auth login   # GitHub.com, HTTPS, autenticación por navegador
   gh auth status
   ```
7. **uv:**

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   uv --version   # en un terminal nuevo
   ```
8. **Claude Code** con el instalador de Linux, dentro de WSL:

   ```bash
   curl -fsSL https://claude.ai/install.sh | bash
   claude --version
   claude doctor
   ```

   El primer `claude` abre el inicio de sesión en el navegador; requiere un plan Pro, Max, Team, Enterprise o una cuenta de Console.
9. **Extensión de Claude Code en Cursor**, desde el panel de extensiones, con la ventana conectada a WSL.
10. **Comprobación de Docker desde WSL:**

    ```bash
    docker run hello-world
    ```

[Instalación de uv](https://docs.astral.sh/uv/getting-started/installation/) · [Instalación de Claude Code](https://code.claude.com/docs/en/setup.md)

## Estructura inicial del repositorio

El repositorio nace con diseño `src/`: el motor vive en el paquete `edsim`, y las carpetas del resto del stack (`dbt/`, `docker/`, `notebooks/`…) se crean en el hito que las necesita.

```
~/proyectos/edsim/
├── src/edsim/
│   ├── __init__.py          # versión del paquete
│   └── cli.py               # punto de entrada: `edsim --version`
├── tests/
│   └── test_smoke.py        # el paquete importa y la CLI responde
├── docs/
│   ├── diseno.md            # documento de diseño exportado
│   ├── specs/hito-0.md      # esta especificación
│   ├── decisiones/          # un ADR por decisión: 0001-....md
│   └── diario/              # notas de aprendizaje por hito
├── .claude/
│   ├── settings.json        # permisos, hooks y estilo, compartidos
│   └── hooks/run-tests.sh   # hook de tests al terminar un turno
├── .github/workflows/ci.yml
├── CLAUDE.md
├── pyproject.toml
├── uv.lock
├── .python-version          # 3.13
├── .pre-commit-config.yaml
├── .gitignore
└── README.md
```

El documento de diseño y esta especificación se exportan a Markdown desde este documento y se versionan en `docs/`, para que Claude Code los lea como contexto.

## Calidad local: uv, ruff, pytest y pre-commit

Tres herramientas cubren la calidad local; las mismas comprobaciones se repiten en el CI.

| Herramienta | Papel | Comando |
| --- | --- | --- |
| uv | Python 3.13, entorno virtual y dependencias bloqueadas en `uv.lock` | `uv sync` |
| ruff | Linter y formateador en una sola herramienta | `uv run ruff check .` y `uv run ruff format .` |
| pytest | Tests | `uv run pytest` |
| pre-commit | Ejecuta ruff antes de cada commit; si falla, no hay commit | `uv run pre-commit install` (una vez) |

**Configuración en `pyproject.toml`**

- `[project]`: nombre `edsim`, `requires-python = ">=3.13"` y el script `edsim = "edsim.cli:main"`.
- Grupo de desarrollo (`uv add --dev`): `pytest`, `ruff`, `pre-commit`.
- `[tool.ruff]`: longitud de línea 100; reglas `E`, `F`, `I` (orden de imports), `B` (errores probables) y `UP` (sintaxis moderna).
- `[tool.pytest.ini_options]`: `testpaths = ["tests"]`.

**`.pre-commit-config.yaml`**

- Hooks de ruff (`ruff check --fix` y `ruff format`) del repositorio oficial de ruff para pre-commit.
- Hooks básicos: espacios al final de línea, salto de línea final, YAML válido y bloqueo de ficheros grandes.
- Los tests no van en pre-commit, para que los commits sean rápidos: los ejecutan el hook de Claude Code y el CI.

## CLAUDE.md y configuración de Claude Code

Tres piezas fijan cómo trabaja Claude Code en el proyecto: `CLAUDE.md` dice lo que debe saber, `.claude/settings.json` fija lo que puede hacer, y el estilo de respuesta decide cómo explica.

### CLAUDE.md

Corto y concreto, porque se carga en cada sesión:

- **Proyecto:** una línea sobre EDsim y enlaces a `docs/diseno.md` y a la especificación del hito en curso.
- **Modo de trabajo:** explicar el concepto antes de implementar; usar modo plan para cualquier cambio no trivial; pasos pequeños; explicar cada decisión en la revisión.
- **Comandos:** `uv sync`, `uv run pytest`, `uv run ruff check .`, `uv run ruff format .`, `uv run edsim`.
- **Convenciones:** código, nombres y docstrings en inglés; documentación, especificaciones y mensajes de commit en español; claves de los YAML de configuración en español, como en el diseño; commits con prefijo `feat`, `fix`, `docs`, `test`, `chore` o `ci`.
- **Reglas de git:** nunca trabajar en `main`; nunca subir sin permiso; nunca fusionar pull requests.

### .claude/settings.json

Se versiona con el repositorio. Los permisos dejan pasar sin preguntar los comandos de lectura y de comprobación, piden permiso para subir y bloquean la fusión:

```json
{
  "outputStyle": "Explanatory",
  "permissions": {
    "allow": [
      "Bash(uv sync)",
      "Bash(uv run pytest *)",
      "Bash(uv run ruff *)",
      "Bash(git status)",
      "Bash(git diff *)",
      "Bash(git log *)",
      "Bash(gh pr view *)",
      "Bash(gh pr checks *)",
      "Bash(gh run view *)"
    ],
    "ask": [
      "Bash(git push *)",
      "Bash(gh pr create *)"
    ],
    "deny": [
      "Bash(gh pr merge *)",
      "Read(./.env)"
    ]
  },
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "jq -r '.tool_input.file_path' | grep '\\.py$' | xargs -r uv run ruff format"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/run-tests.sh"
          }
        ]
      }
    ]
  }
}
```

- **Permisos:** las reglas `deny` se evalúan antes que `ask` y `allow`. Coinciden con el texto del comando, así que son una barandilla de comportamiento, no una frontera de seguridad; la protección de `main` en GitHub es la que de verdad impide fusionar sin revisión.
- **Hook `PostToolUse`:** formatea con ruff cada fichero Python que Claude edita.
- **Hook `Stop`:** al terminar cada turno ejecuta `uv run pytest -q`. Si hay tests rojos, sale con código 2 y Claude ve el fallo y lo corrige. El script comprueba `stop_hook_active` para no entrar en bucle.
- **Estilo `Explanatory`:** Claude añade bloques `Insight` que explican las decisiones detrás del código que escribe. Encaja con el modo de trabajo acordado; el estilo `Learning`, que deja trozos de código para que los escriba Pedro, no.

### Prácticas que se estrenan en este hito

- Modo plan para la primera tarea que Claude Code implementa.
- Revisar los diffs en Cursor antes de cada commit.
- `/hooks` y `/permissions` para comprobar que la configuración está cargada.

Los comandos personalizados y *skills* del proyecto (empezar y cerrar hito) se introducen en los hitos 1 y 2.

[Permisos](https://code.claude.com/docs/en/permissions.md) · [Hooks](https://code.claude.com/docs/en/hooks-guide.md) · [Estilos de respuesta](https://code.claude.com/docs/en/output-styles.md)

## GitHub: repositorio, protección de main y CI

El repositorio se crea público: en el plan gratuito de GitHub, los rulesets que protegen una rama solo están disponibles en repositorios públicos. EDsim no contiene secretos ni datos reales, así que hacerlo público no tiene coste y además sirve de portfolio.

> Si Pedro prefiere un repositorio privado sin pagar GitHub Pro, la protección de `main` no se puede aplicar; quedaría solo la regla de Claude Code y la disciplina del flujo.

### Creación

```bash
gh repo create edsim --public --source . --push
```

### Ruleset de main

Se crea en *Settings → Rules → Rulesets* después de la primera ejecución del CI, para que el nombre del check aparezca en la lista:

- Rama objetivo: `main`.
- Exigir pull request antes de fusionar (sin aprobaciones obligatorias, porque Pedro es el único revisor).
- Exigir que el check `tests` del CI esté en verde.
- Bloquear push forzado y borrado de la rama.
- Ajustes del repositorio: permitir solo *Squash and merge* y borrar la rama automáticamente tras fusionar.

### CI: .github/workflows/ci.yml

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v10.3.3
      - run: uv sync --locked
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run pytest
```

`--locked` hace fallar el CI si `uv.lock` no está al día con `pyproject.toml`, una comprobación que también detecta dependencias añadidas a mano. `permissions: contents: read` limita el job a leer el repositorio (mínimo privilegio). `setup-uv` se fija con la versión completa porque Astral no publica etiqueta mayor; habrá que actualizarla a mano o con Dependabot.

[Rulesets disponibles por plan](https://docs.github.com/enterprise-cloud@latest/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)

## Tareas, ramas y orden de ejecución

El hito se divide en ocho tareas. Las dos primeras preparan la máquina; desde la tercera, cada tarea es una rama y un pull request, salvo el commit inicial.

| # | Tarea | Rama | Quién escribe | Resultado |
| --- | --- | --- | --- | --- |
| 0.1 | Preparar Windows: WSL2, Docker Desktop, Cursor | — | Pedro | Pasos 1–3 de la instalación |
| 0.2 | Herramientas en Ubuntu: git, gh, uv, Claude Code | — | Pedro | Pasos 4–10 de la instalación |
| 0.3 | Esqueleto del proyecto con `uv init --package`, Python 3.13 y CLI mínima; repositorio en GitHub | `main` (commit inicial) | Claude Code, guiado por Pedro | `uv run edsim --version` responde |
| 0.4 | Calidad local: ruff, pytest, pre-commit, test de humo | `chore/h0-calidad` | Claude Code | Primer pull request |
| 0.5 | CI en GitHub Actions | `ci/h0-github-actions` | Claude Code | Check `tests` visible en el pull request |
| 0.6 | Ruleset de `main` | — | Pedro, en la web de GitHub | Un push directo a `main` es rechazado |
| 0.7 | Configuración de Claude Code y documentación: `CLAUDE.md`, `.claude/`, `docs/` | `chore/h0-claude-code` | Claude Code | Hooks y permisos activos; diseño y spec en `docs/` |
| 0.8 | Cierre: ADRs de las decisiones del diseño, entrada del diario, etiqueta `v0.0-hito0` | `docs/h0-cierre` | Claude Code redacta, Pedro valida | Hito cerrado |

Dos comprobaciones deliberadas durante el hito, para ver las barandillas funcionando:

- En la tarea 0.4, intentar un commit con un fichero mal formateado y ver cómo pre-commit lo para.
- En la tarea 0.5, subir un test que falla a propósito, ver el CI en rojo, leer el log y corregirlo.

## Criterios de aceptación

El hito 0 está cerrado cuando se cumplen todos:

- [x] `wsl -l -v` muestra Ubuntu-24.04 con VERSION 2.
- [x] `docker run hello-world` funciona desde Ubuntu.
- [x] Cursor abre `~/proyectos/edsim` conectado a WSL.
- [x] `uv --version`, `gh auth status`, `claude --version` y `claude doctor` responden sin errores.
- [x] `uv run edsim --version` imprime la versión del paquete.
- [x] `uv run pytest`, `uv run ruff check .` y `uv run ruff format --check .` pasan.
- [x] pre-commit bloquea un commit mal formateado.
- [x] El CI se ejecuta en cada pull request y ha mostrado al menos un rojo y un verde.
- [x] Un push directo a `main` es rechazado por el ruleset.
- [x] En Claude Code, `/hooks` lista los hooks del proyecto, el estilo activo es `Explanatory` y `gh pr merge` aparece denegado en `/permissions`.
- [x] `docs/` contiene el diseño, esta especificación, los ADRs y la entrada del diario del hito.
- [ ] La etiqueta `v0.0-hito0` existe en GitHub.
