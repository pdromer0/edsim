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
- [x] La etiqueta `v0.0-hito0` existe en GitHub.

## Anexo: guía de referencia para montar un entorno similar

Este anexo recoge lo que se hizo en el hito 0, por qué se hizo así, los problemas que aparecieron y cómo se resolvieron. Está pensado para releerlo la próxima vez que haya que montar un entorno de desarrollo parecido: Python en WSL2, GitHub con CI y Claude Code.

### Orden de montaje en una página

1. Comprobar la virtualización en Windows y tener **WSL 2.x estable** con Ubuntu 24.04.
2. **Docker Desktop** con motor WSL 2 e integración con Ubuntu activada.
3. **Cursor** con la extensión Remote WSL de Anysphere y la extensión de Claude Code.
4. En Ubuntu: `apt update && apt upgrade`, después `git curl build-essential jq` (y `wslu`).
5. Identidad de git con el email privado de GitHub y rama por defecto `main`.
6. **GitHub CLI** desde el repositorio oficial de GitHub y `gh auth login`.
7. **uv** y Python 3.13 gestionado por uv.
8. **Claude Code** con el instalador de Linux, canal estable.
9. Proyecto con `uv init --package`, primer commit y `gh repo create --public`.
10. Calidad local (ruff, pytest, pre-commit), CI en GitHub Actions y ruleset de `main`.
11. `CLAUDE.md`, `.claude/settings.json` y `docs/`.
12. ADRs, diario y etiqueta de versión.

### 1. WSL2: Linux dentro de Windows

**Qué es.** WSL2 ejecuta un Linux real (kernel incluido) en una máquina virtual ligera integrada en Windows. Las distribuciones, como Ubuntu, viven en discos virtuales propios.

**Por qué.** El CI de GitHub, los contenedores de Docker y casi todo el ecosistema de datos funcionan en Linux. Desarrollar en WSL2 hace que el entorno local se parezca al del CI, evita problemas de rutas, finales de línea y permisos de Windows, y permite el sandbox de Claude Code, que en Windows nativo no está disponible. El código vive en el sistema de ficheros de Linux (`~/proyectos`), no en `/mnt/c`, por rendimiento y permisos.

**Comandos clave (PowerShell)**

```powershell
wsl --install -d Ubuntu-24.04   # instalar
wsl --version                   # versión de WSL y del kernel
wsl -l -v                       # distribuciones y versión (debe ser 2)
wsl --shutdown                  # apagar WSL por completo
wsl -d Ubuntu -u root           # entrar como root en una distribución
```

**Problema principal: WSL dejó de arrancar**

- **Síntoma:** `wsl --update` instaló la versión 3.0.3 y ninguna distribución arrancaba: `Wsl/Service/CreateInstance/CreateVm/ERROR_FILE_NOT_FOUND`.
- **Diagnóstico, de lo general a lo concreto:**
  1. `wsl -d docker-desktop -- echo ok` también fallaba: el problema era de WSL, no de Ubuntu.
  2. La plataforma de máquina virtual estaba activa (`Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform`, que exige terminal de administrador).
  3. No existía `~/.wslconfig`, una causa frecuente del mismo error cuando apunta a un kernel o fichero que no existe.
  4. La 3.0.3 no figuraba como versión estable en GitHub: había llegado una versión preliminar.
- **Solución:** `winget list wsl` para ver cómo estaba instalado, `winget uninstall --id Microsoft.WSL`, reinicio y `winget install --id Microsoft.WSL --version 2.7.13`. La instalación dio un error al 95 % (`0x80070002`), pero tras reiniciar quedó correcta.
- **Lecciones:**
  - `wsl --update` solo sube de versión; para bajar hay que desinstalar e instalar la versión concreta.
  - Preferir siempre las versiones estables en las herramientas base.
  - Desinstalar el paquete de WSL no borra las distribuciones. Lo que sí las borra es `wsl --unregister`: no usarlo nunca sin copia.
  - Tras actualizar o reinstalar componentes de Windows, reiniciar antes de diagnosticar.
  - Para un solo comando de administrador, mejor `sudo` de Windows (Configuración → Sistema → Para programadores) o una terminal de administrador aparte que trabajar siempre elevado.

**Problema menor: contraseña de Linux olvidada.** Se restablece sin conocer la anterior: `wsl -d Ubuntu -u root`, `ls /home` para ver el usuario y `passwd <usuario>`.

### 2. Docker Desktop

**Qué es.** El motor que ejecuta contenedores. En Windows corre dentro de su propia distribución WSL (`docker-desktop`).

**Conceptos:** el **cliente** (`docker`) habla con el **daemon** (el motor); el daemon descarga **imágenes** (plantillas inmutables) de un registro como Docker Hub y crea **contenedores** (instancias en ejecución) a partir de ellas.

**Configuración:** *Settings → General → Use the WSL 2 based engine* y *Settings → Resources → WSL integration*, con la distribución activada. La sección se encuentra rápido escribiendo "WSL" en el buscador de ajustes. Comprobación: `docker run hello-world` desde Ubuntu.

**Lección:** Docker depende de WSL; si WSL falla, Docker también.

### 3. Cursor y Claude Code en el editor

- Cursor corre en Windows y se conecta a Ubuntu con la extensión **Remote WSL de Anysphere** (la de Microsoft no funciona en Cursor). Conectado, la barra inferior muestra *WSL: Ubuntu* y el terminal integrado es el de Linux.
- La extensión de **Claude Code** (de Anthropic) se instala con la ventana conectada a WSL y comparte configuración e historial con la CLI.
- La app de escritorio de Claude también puede abrir sesiones de código dentro de WSL (pestaña Code → entorno WSL), aunque hoy sin terminal integrado ni sugerencias con `@` en ese modo.

**Problema menor: la tecla Windows no respondía.** Causas típicas: bloqueo con `Fn` en el teclado, el Explorador de Windows colgado (reiniciarlo desde el Administrador de tareas) o una política de empresa. No bloquea nada: todo se puede abrir desde el menú Inicio o el terminal.

### 4. Ubuntu: paquetes base y git

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl build-essential jq wslu
git config --global user.name "pdromer0"
git config --global user.email "<id>+pdromer0@users.noreply.github.com"
git config --global init.defaultBranch main
```

- `build-essential` aporta compiladores que algunas librerías de Python necesitan; `jq` lee JSON en el terminal (lo usan los hooks de Claude Code); `wslu` permite abrir el navegador de Windows desde WSL.
- El **email privado de GitHub** (Settings → Emails) evita exponer el correo real en un repositorio público.
- Teclado español: la virgulilla `~` se escribe con `AltGr + 4` (a veces seguido de espacio); `cd` sin argumentos lleva igualmente a la carpeta personal.

### 5. GitHub CLI (gh)

- **No** instalar el paquete `gh` de los repositorios de Ubuntu: la versión que distribuye la comunidad está rota. Usar el repositorio oficial de GitHub (instrucciones en `cli/cli`, documento *install\_linux*).
- `gh auth login`: GitHub.com, HTTPS, *Authenticate Git with your GitHub credentials* = Yes, login por navegador. Esa última opción registra `gh` como gestor de credenciales de git, de modo que `git push` no pide contraseña.
- En WSL el navegador no se abre solo: copiar `https://github.com/login/device` en el navegador de Windows e introducir el código. Con `wslu` instalado se abre automáticamente.

### 6. uv y Python

**Qué es.** Un único gestor que sustituye a pyenv (versiones de Python), venv (entornos virtuales) y pip/pip-tools (dependencias y fichero de bloqueo).

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env      # o abrir un terminal nuevo
uv python install 3.13
```

**Problema: `uv: command not found` justo después de instalar.** El instalador añade `~/.local/bin` al `PATH` (la lista de carpetas donde el terminal busca programas), pero solo para terminales nuevos. Solución: `source $HOME/.local/bin/env`. No instalar la versión de snap que sugiere Ubuntu.

### 7. Claude Code

```bash
curl -fsSL https://claude.ai/install.sh | bash
claude --version
claude doctor
```

- Requiere un plan Pro, Max, Team, Enterprise o una cuenta de Console.
- **Confianza de carpeta:** al arrancar en una carpeta nueva pregunta si confiar en ella, porque un proyecto puede traer hooks y permisos propios. Trabajar siempre dentro de la carpeta del proyecto, no en la carpeta personal.
- **Modos de permisos** (`Shift + Tab`): Manual (pregunta cada acción), Plan (solo explora y propone), Accept edits y Auto (un clasificador aprueba lo de bajo riesgo). Las reglas `deny` y `ask` del proyecto se aplican en todos los modos.
- **Canal de actualizaciones:** `/config` → *Auto-update channel* → `stable`, eligiendo quedarse en la versión actual hasta que el canal estable la alcance (no bajar de versión sin motivo).

### 8. El proyecto Python

```bash
mkdir -p ~/proyectos && cd ~/proyectos
uv init --package edsim --python 3.13
cd edsim
uv run edsim
```

- `--package` crea un paquete instalable con diseño `src/` y un comando de terminal propio definido en `[project.scripts]` de `pyproject.toml`.
- `uv run` crea `.venv`, instala el paquete en modo editable y genera `uv.lock`. `.venv` no se sube al repositorio; `uv.lock` sí.
- CLI mínima con `argparse` (biblioteca estándar) y la versión leída con `importlib.metadata`, para que la versión viva solo en `pyproject.toml`.

### 9. git y GitHub Flow

| Concepto | Qué es | Comando |
| --- | --- | --- |
| Área de preparación | Selección de cambios que entrarán en el commit | `git add` |
| Commit | Instantánea guardada en el historial con un mensaje | `git commit -m "tipo: mensaje"` |
| Rama | Línea de trabajo aislada de `main` | `git switch -c <rama>` |
| Remoto | Copia del repositorio en GitHub (`origin`) | `git push -u origin <rama>` |
| Pull request | Propuesta de fusión revisable, donde corre el CI | `gh pr create` |
| Squash and merge | Fusiona todos los commits de la rama como uno solo en `main` | Botón en la pestaña *Conversation* del PR |
| Revert | Deshace un commit creando otro nuevo, sin reescribir historial | `git revert --no-edit HEAD` |
| Reset | Mueve la rama local y descarta cambios (usar con cuidado) | `git reset --hard origin/main` |
| Etiqueta | Marca un punto del historial, por ejemplo el cierre de un hito | `git tag -a v0.0-hito0 -m "..."` |

- `git diff` compara con el último commit: antes del primer commit no muestra nada.
- Tras un *squash*, la rama local se borra con `git branch -D` (con mayúscula), porque git no reconoce sus commits dentro de `main`.
- **Repositorio público:** en el plan gratuito, los rulesets solo protegen ramas en repositorios públicos. Público implica que todo el historial es visible y permanente: nunca subir secretos.

### 10. Calidad local: tres niveles

| Nivel | Cuándo actúa | Herramienta |
| --- | --- | --- |
| Al editar | Tras cada cambio de Claude Code | Hooks de Claude Code (formato y tests) |
| Al hacer commit | Antes de crear el commit; si falla, no hay commit | pre-commit con ruff y hooks básicos |
| Al subir | En una máquina limpia de GitHub | CI en GitHub Actions |

- **ruff** es linter y formateador a la vez: el estilo lo decide la herramienta, no las personas ni el agente.
- **pytest** con un test de humo: el paquete se importa, la versión coincide y la CLI responde.
- **uv.lock crece mucho** al añadir herramientas, porque fija también todas sus dependencias con su hash. Es normal y se versiona.
- Prueba realizada: un fichero mal formateado hizo fallar el commit; `ruff format` lo corrigió y el commit no se creó.

### 11. CI con GitHub Actions

- Vocabulario: **workflow** (fichero en `.github/workflows/`), **disparador** (`on`), **job** (pasos en una máquina o *runner*), **step** (`run` para comandos, `uses` para acciones reutilizables).
- `uv sync --locked` falla si `uv.lock` no coincide con `pyproject.toml`; `--frozen` usaría el lock sin comprobarlo.
- `permissions: contents: read`: mínimo privilegio.
- Sin `--fix` en el CI: el CI detecta y falla; corregir es trabajo local.
- Versiones de acciones: `actions/checkout@v7` (etiqueta mayor) y `astral-sh/setup-uv@v10.3.3` (versión exacta, porque Astral no publica etiqueta mayor).
- Lectura de un fallo: `gh pr checks --watch` y `gh run view --log-failed`; leer de abajo arriba: código de salida, resumen `FAILED`, y la línea marcada con `>` y la explicación con `E`.
- **Lección:** el asistente del chat dudó de que existiera `setup-uv@v10.3.3` y el CI demostró que sí. Cualquier afirmación de un modelo sobre versiones, URLs o APIs se verifica con una herramienta (`gh release view`, la documentación o la propia ejecución).

### 12. Protección de main

Ruleset en *Settings → Rules → Rulesets*: rama por defecto, lista de excepciones vacía, impedir borrado y push forzado, exigir pull request (0 aprobaciones, porque GitHub no permite aprobar los propios PR), solo *squash*, y exigir el check `tests`. Se crea después de la primera ejecución del CI para que el check aparezca en la lista.

Comprobación: un `git push` directo a `main` fue rechazado con `GH013: Repository rule violations`. El rechazo ocurre en el servidor, así que se aplica con cualquier herramienta.

### 13. Configuración de Claude Code en el proyecto

- **`CLAUDE.md`:** lo que Claude debe saber (proyecto, modo de trabajo, comandos, convenciones, reglas de git). Corto, porque se carga en cada sesión; enlaza a `docs/` en lugar de copiar.
- **`.claude/settings.json`:** lo que Claude puede hacer, aplicado por Claude Code y no por el modelo. Permisos `allow`, `ask` y `deny` (se evalúan deny → ask → allow), hooks y `outputStyle: "Explanatory"` (con mayúscula).
- **Hook `PostToolUse`:** formatea con ruff cada fichero Python editado.
- **Hook `Stop`:** ejecuta `uv run pytest -q -x` al final de cada turno; si falla, devuelve las últimas líneas con código 2 para que Claude lo corrija, y comprueba `stop_hook_active` para no entrar en bucle.
- **Modo Plan por defecto:** `defaultMode: "plan"` en el proyecto solo afecta al terminal; para el panel de Cursor hace falta `"claudeCode.initialPermissionMode": "plan"` en los ajustes de usuario del editor.
- Las reglas de permisos coinciden con el texto del comando: son una barandilla de comportamiento. La protección real de `main` es el ruleset de GitHub.

### Lecciones aprendidas

| Problema | Causa | Solución | Lección |
| --- | --- | --- | --- |
| WSL no arrancaba (`CreateVm/ERROR_FILE_NOT_FOUND`) | Versión preliminar 3.0.3 de WSL | Desinstalar con winget e instalar la 2.7.13 | Usar versiones estables; `wsl --update` no baja de versión |
| Instalación de WSL falló al 95 % (`0x80070002`) | Limpieza pendiente de la desinstalación | Reiniciar Windows | Reiniciar tras desinstalar o actualizar componentes del sistema |
| `Get-WindowsOptionalFeature` pedía elevación | Terminal sin permisos de administrador | Terminal de administrador o `sudo` de Windows | Elevar solo los comandos que lo necesitan |
| Contraseña de Linux olvidada | — | `wsl -d Ubuntu -u root` y `passwd` | Apuntar las credenciales en un gestor de contraseñas |
| `gh` no abría el navegador | WSL no tiene navegador propio | Copiar la URL a mano; instalar `wslu` | Instalar `wslu` desde el principio |
| `uv: command not found` | `PATH` sin recargar | `source $HOME/.local/bin/env` | Abrir un terminal nuevo tras instalar herramientas |
| `git diff` vacío en el primer cambio | No había ningún commit con el que comparar | Revisar los ficheros directamente | `git diff` compara con el último commit |
| No se encontraba *Squash and merge* | El botón está al final de la pestaña *Conversation* | Usar el desplegable del botón de fusión | Configurar el repositorio con solo *squash* |
| Duda sobre la versión de `setup-uv` | Información desactualizada del asistente | El CI confirmó la versión | Verificar con herramientas, no con afirmaciones |
| Modo Plan no aplicaba en el panel de Cursor | La extensión lee el modo de los ajustes de usuario | `claudeCode.initialPermissionMode` | Distinguir configuración del proyecto y configuración personal |

### Referencia rápida de comandos

| Tarea | Comando |
| --- | --- |
| Sincronizar el entorno | `uv sync` |
| Ejecutar tests | `uv run pytest` |
| Linter y formato | `uv run ruff check .` · `uv run ruff format .` |
| Instalar hooks de git | `uv run pre-commit install` |
| Empezar una tarea | `git switch main && git pull && git switch -c <rama>` |
| Subir y abrir PR | `git push -u origin <rama>` · `gh pr create` |
| Seguir el CI | `gh pr checks --watch` · `gh run view --log-failed` |
| Volver a main tras fusionar | `git switch main && git pull && git branch -D <rama>` |
| Diagnóstico de Claude Code | `claude doctor` |
| Estado de WSL | `wsl --version` · `wsl -l -v` |
