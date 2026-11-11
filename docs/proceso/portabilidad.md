# Portabilidad: cómo replicar el flujo de EDsim en un proyecto nuevo

> **Estado:** documento vivo. Versión 0.1, del 11 de noviembre de 2026. Se pone al día después de cada paso de la P.2 y de cada piloto del hito 5, y queda cerrado en el balance de la tarea 5.8. Puede acabar convirtiéndose en un repositorio plantilla de GitHub.

Cada pieza lleva su estado:

- **[probado]**: funciona en EDsim desde hace varios hitos.
- **[implantado]**: está en el repositorio desde la P.2 y pendiente de su primer uso real en una tarea.
- **[piloto]**: se prueba en una tarea del hito 5. En la 5.8 se decide si se queda o se descarta.
- **[pendiente]**: decidido, sin implantar todavía.

---

## 1. Para qué sirve y cómo usarlo

Es la receta para montar un proyecto nuevo con el mismo modo de trabajo. Hay tres papeles: una persona que decide y aprende, un chat que hace de arquitecto y profesor, y agentes de código (Claude Code y Codex) que implementan con barandillas. La primera vez se lee en este orden:

- **Sección 2:** las decisiones de fondo.
- **Secciones 3 a 7:** cómo montar cada pieza.
- **Secciones 8 y 9:** el ciclo de trabajo diario y los modelos.
- **Sección 11:** la lista de arranque del primer día.

La sección 12 dice qué cambiar si el proyecto es distinto, y la 13 recoge las lecciones de la implantación.

## 2. Decisiones de fondo

Son las que hacen que el flujo funcione. En un proyecto nuevo se copian tal cual, salvo que haya un motivo para cambiarlas; si se cambia una, se escribe la ADR del cambio.

| # | Decisión | Motivo | En EDsim |
| --- | --- | --- | --- |
| D1 | **La persona decide y el agente implementa.** Hay una sesión conceptual antes de cada hito; el agente propone un plan y lo implementa cuando se aprueba; solo la persona fusiona | El control humano está en los dos puntos que importan: el plan y la fusión | [ADR 0008](../decisiones/0008-claude-code-escribe-el-codigo.md) y [0011](../decisiones/0011-github-flow-con-ci-obligatorio.md) [probado] |
| D2 | **Se usan las librerías, sin reimplementar fundamentos.** Los conceptos se explican y se profundiza bajo demanda | Aprender el estándar de la industria, no a reescribirlo | [ADR 0009](../decisiones/0009-librerias-sin-reimplementar.md) [probado] |
| D3 | **GitHub Flow:** ramas cortas, un PR por tarea, CI obligatorio, *squash and merge* y `main` protegida | Red de seguridad para el código que escribe la IA | [ADR 0011](../decisiones/0011-github-flow-con-ci-obligatorio.md) [probado] |
| D4 | **Repositorio público con ruleset**, o privado con GitHub Pro | En el plan gratuito, los rulesets solo protegen ramas de repositorios públicos | [ADR 0014](../decisiones/0014-repositorio-publico-con-ruleset.md) [probado] |
| D5 | **Idiomas por zona:** el código en inglés; la documentación, los commits y la interfaz en el idioma de la persona; los tests, según su público | El estándar del código, y el aprendizaje en tu idioma | [ADR 0015](../decisiones/0015-idiomas-del-proyecto.md) [probado] |
| D6 | **Tests por niveles:** cada punto del ciclo ejecuta solo lo que el último cambio puede haber roto | De unas 3 horas de espera por tarea a menos de 50 minutos, sin perder la suite completa antes de `main` | [ADR 0047](../decisiones/0047-tests-por-niveles.md) [probado] |
| D7 | **El repositorio es la fuente de verdad** de todo lo que cambia con el código (diseño, especificaciones, anexos, decisiones y diario), y se revisa por PR | Una sola copia que los agentes pueden escribir: nada que exportar ni comparar | Decisión 80 (PR #62) [implantado] |
| D8 | **El trabajo vive en GitHub:** issues, milestones y un tablero de Projects. El PR cierra su issue | El estado se actualiza solo, junto al código | P.2, A3 [implantado] |
| D9 | **Cada cosa en un solo sitio.** Lo que se repite en todas las tareas va a una skill y a un documento común, no a cada prompt | Un cambio de proceso se toca una vez | P.2, A4 [implantado] |
| D10 | **La documentación va en el mismo PR que el código:** la entrada del anexo de la tarea y lo que cambie en diseño o especificaciones | Una documentación desfasada se ve en la revisión, como un test | P.2, A4 [implantado] |
| D11 | **Al cambiar el proceso, una novedad por tarea**, que se mide y se decide al final | Si algo falla, se sabe qué ha sido | P.2 [implantado] |
| D12 | **Varios agentes con papeles distintos:** el chat explica, especifica y revisa; Claude Code implementa; Codex revisa las tareas críticas y hace la interfaz | Revisión por un modelo distinto del que escribió el código | [ADR 0008](../decisiones/0008-claude-code-escribe-el-codigo.md) y APP-0003 [probado] |

**Prácticas de calidad** [probado], que se llevan a cualquier proyecto con cálculos o datos:

- **Tests primero, con valores calculados a mano.** Una referencia que usa la función probada hereda su error. Desde la P.2, cada valor a mano lleva su cálculo escrito en el plan, con aritmética o con código independiente, nunca de memoria.
- **Casos límite como lista explícita en el plan:** enteros enormes, NaN e infinitos, `date` frente a `datetime`, empates y orden de eventos del mismo instante, listas de distinta longitud, vacíos, primer y último elemento.
- **Versiones incorrectas con predicción firme.** Antes de dar un test por bueno, se rompe el código a propósito, se predice qué test debe fallar y se comprueba que falla por esa razón. Es una prueba de mutación hecha a mano.
- **Lo exacto antes que lo simulado.** Semillas, tolerancias y umbrales se fijan antes de medir. Nunca se cambia una semilla para que un test pase.
- **Patrón «derivado y escrito».** Lo que se calcula o se calibra se calcula una vez y se escribe en la configuración, con el comando que lo produce en un comentario. Un test comprueba que lo escrito coincide con lo recalculado.
- **La lógica, en el paquete.** Las capas (CLI, notebooks, app) son finas.
- **El refactor, en un commit aparte**, sin tocar los tests.
- **Cada cifra lleva escrita su medida.**

## 3. Entorno desde cero (Windows con WSL2) [probado]

Todo el trabajo vive dentro de Linux (WSL2), igual que en el CI. En Windows solo corre el editor (Cursor). La guía detallada está en el anexo de la [especificación del hito 0](../specs/hito-0.md), «guía de referencia para montar un entorno similar».

### En Windows

1. **WSL2 con Ubuntu**, en PowerShell como administrador:

   ```powershell
   wsl --install -d Ubuntu-24.04
   wsl -l -v    # debe aparecer con VERSION 2
   ```

2. **Docker.** EDsim usa el motor de Docker instalado dentro de Ubuntu, sin Docker Desktop. Con él, «Docker parado» significa `docker compose down`. Docker Desktop con el motor WSL2 también vale.
3. **Cursor**, con la extensión **Remote WSL de Anysphere** (la de Microsoft no es compatible) y *Connect to WSL*.
4. **Si la red de WSL da cortes** con respuestas largas (sesiones de Claude Code que se quedan en «Waiting for API response»), prueba en `C:\Users\<usuario>\.wslconfig`:

   ```ini
   [wsl2]
   networkingMode=mirrored
   dnsTunneling=true
   ```

### Dentro de Ubuntu

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl build-essential jq     # los hooks necesitan jq
git config --global user.name "…"
git config --global user.email "…"
git config --global init.defaultBranch main
git config --global pull.ff only                    # git pull solo avanza si no hay divergencia
git config --global fetch.prune true                # limpia las referencias de ramas borradas
# GitHub CLI: seguir las instrucciones oficiales para Ubuntu
gh auth login && gh auth status
gh auth refresh -s project                          # permiso para el tablero de Projects
curl -LsSf https://astral.sh/uv/install.sh | sh     # uv: Python, entornos y dependencias
curl -fsSL https://claude.ai/install.sh | bash      # Claude Code, dentro de WSL
claude --version && claude doctor
docker run hello-world
```

Después: la extensión de Claude Code en Cursor (con la ventana conectada a WSL) y, si se usa Codex, su extensión.

**Reglas:**
- El código vive en `~/proyectos/<nombre>`, nunca en `/mnt/c`, por rendimiento y por permisos.
- Si `claude` funciona en la extensión y falla en la terminal, compara con `which -a claude` y las variables de proxy o certificados del shell.

## 4. Repositorio desde cero [probado]

```bash
cd ~/proyectos && uv init --package <nombre> && cd <nombre>
uv python pin 3.13
uv add --dev pytest ruff pre-commit pytest-xdist
gh repo create <nombre> --public --source . --push
```

**Estructura mínima:**

```
src/<paquete>/        # lógica, con tests
tests/
docs/                 # ver la sección 6
scripts/              # tests-rapidos.sh, tests-completos.sh
.claude/              # settings.json, hooks/, skills/
.codex/               # config.toml, hooks.json, rules/ (si se usa Codex)
.github/              # workflows/ci.yml, ISSUE_TEMPLATE/, pull_request_template.md
AGENTS.md  CLAUDE.md  README.md  pyproject.toml  uv.lock  .pre-commit-config.yaml
```

**`pyproject.toml`**, lo esencial:

```toml
[tool.ruff]
line-length = 100
[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--strict-markers"
markers = ["slow: tests largos; el hook Stop no los ejecuta"]
```

**`.pre-commit-config.yaml`:**
- `ruff-check --fix` y `ruff-format`;
- los hooks básicos: espacios al final de línea, salto final, YAML válido y ficheros grandes;
- `nbstripout`, si hay notebooks.

Los tests no van en pre-commit, para que los commits sean rápidos. Se activa con `uv run pre-commit install`.

**CI (`.github/workflows/ci.yml`):**

```yaml
name: CI
on: { pull_request: {}, push: { branches: [main] } }
permissions: { contents: read }
concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.sha }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
jobs:
  tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v10.3.3   # versión completa: Astral no publica etiqueta mayor
      - run: uv sync --locked              # falla si uv.lock no está al día
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run pytest
```

Se añade un job por cada capa que lo necesite: notebooks, app, integración con servicios y, más adelante, `docs`.

**Protección de `main`** (*Settings → Rules → Rulesets*, después del primer CI para que aparezcan los checks): exigir PR, exigir los checks en verde y bloquear el push forzado y el borrado de la rama.

**Ajustes del repositorio** (*Settings → General → Pull Requests*): solo *squash and merge* y **«Automatically delete head branches»**.

**Comprobaciones deliberadas**, para ver las barandillas funcionar: un commit mal formateado que pre-commit para, y un test rojo a propósito que el CI marca.

## 5. Agentes

### Instrucciones: `AGENTS.md` como fuente única [probado]

- **`AGENTS.md`** lo leen Claude Code y Codex. Lleva:
  - el proyecto en una línea, con enlaces al diseño y a la especificación en curso;
  - el modo de trabajo («cada tarea sigue `docs/proceso/tarea.md`»);
  - los comandos y las convenciones;
  - las reglas de git, de shell y edición, y de después de la fusión;
  - las «Review guidelines», que el revisor trata como P1.
- **`CLAUDE.md`** empieza con `@AGENTS.md` y añade solo lo propio de Claude Code. Con `@AGENTS.md`, Claude Code carga los dos ficheros.
- **Corto:** menos de 200 líneas por fichero. Cada instrucción debe pasar la prueba «si la quito, ¿se equivoca?». Nada de historia: los números de tarea («desde la 6.1») no son instrucciones.
- **Sin contradicciones.** Una regla que cambia según la herramienta se escribe con su excepción explícita y en los dos sitios. Por ejemplo: en `AGENTS.md`, «nunca subas sin permiso; Claude Code tiene su excepción en `CLAUDE.md`»; en `CLAUDE.md`, «aprobar el plan cuenta como ese permiso». Los nombres de herramientas que solo tiene un agente («Edit») se cambian por genéricos («la herramienta de edición del agente»).
- **Revisión periódica con `/doctor prompt-audit`** [implantado], en modo plan y sin aplicar nada: el informe se lleva al chat y los cambios entran por PR. Se repite después de cambiar las instrucciones y al cerrar cada hito.
- **`app/AGENTS.md`** (o el de cada subproyecto) para lo propio de esa zona.

**Reglas de shell y edición** [implantado], salidas de errores reales:
- *heredocs* siempre con comillas (`<<'EOF'`);
- la herramienta de edición del agente antes que `sed`, y nunca `sed -i` sobre markdown;
- nada que espere entrada (sin paginador, sin editores, sin `cat` sin argumentos);
- `ruff format` y `ruff check` antes de cada commit;
- `git push` siempre en un comando propio;
- **los ficheros grandes generados o copiados se escriben con un script**: el modelo no reescribe su contenido;
- avisar antes de un comando largo de qué se ejecuta y cuánto tarda.

**Regla de después de la fusión** [implantado]: antes de actualizar `main` o borrar una rama, se comprueba con `gh pr view N --json state,mergedAt` que el PR está fusionado. Si no lo está, se para.

### `.claude/settings.json`: lo que el agente puede hacer

```json
{
  "outputStyle": "Explanatory",
  "permissions": {
    "defaultMode": "plan",
    "allow": [
      "Bash(uv run pytest *)", "Bash(uv run ruff *)", "Bash(uv sync)",
      "Bash(git status)", "Bash(git diff *)", "Bash(git log *)", "Bash(git fetch --prune)",
      "Bash(git switch *)", "Bash(git add *)", "Bash(git commit *)", "Bash(git pull *)",
      "Bash(git merge-base *)", "Bash(git branch -D *)",
      "Bash(git push -u origin feat/*)", "Bash(git push -u origin fix/*)",
      "Bash(git push -u origin docs/*)", "Bash(git push -u origin refactor/*)",
      "Bash(git push -u origin test/*)", "Bash(git push -u origin chore/*)",
      "Bash(git push -u origin ci/*)",
      "Bash(gh pr create *)", "Bash(gh pr view *)", "Bash(gh pr checks *)", "Bash(gh run view *)",
      "Bash(gh issue view *)", "Bash(gh issue list *)",
      "Bash(gh project list *)", "Bash(gh project field-list *)", "Bash(gh project item-list *)",
      "Bash(gh project item-add *)", "Bash(gh project item-edit *)",
      "Bash(scripts/tests-rapidos.sh*)", "Bash(scripts/tests-completos.sh*)"
    ],
    "ask": [
      "Edit(/config/**)", "Write(/config/**)", "Edit(/tests/data/**)", "Write(/tests/data/**)"
    ],
    "deny": [
      "Bash(gh pr merge *)", "Bash(git push *--force*)", "Bash(git push -f*)",
      "Bash(git push * main)", "Bash(git push * main *)", "Read(./.env)"
    ]
  },
  "hooks": {
    "SessionStart": [{ "hooks": [{ "type": "command", "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/session-start.sh" }] }],
    "PostToolUse": [{ "matcher": "Edit|Write", "hooks": [{ "type": "command",
      "command": "command -v jq >/dev/null 2>&1 || { echo 'jq no está instalado; no se formatea.' >&2; exit 1; }; jq -r '.tool_input.file_path' | grep '\\.py$' | xargs -r uv run ruff format" }] }],
    "Stop": [{ "hooks": [{ "type": "command", "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/run-tests.sh",
      "statusMessage": "N2: tests rápidos con sello; solo las suites afectadas, 2-3 min" }] }]
  }
}
```

- **Arranque en modo plan** [probado]. La aprobación del plan se hace con modo auto, así que el agente implementa entera la tarea aprobada.
- **El push a ramas de tarea está permitido; la fusión, el push forzado y el push a `main`, denegados** [probado]. Las reglas `deny` son una barandilla de comportamiento: la frontera real es el ruleset de GitHub.
- **Los permisos de las skills van aquí**, no en el `allowed-tools` de la skill [implantado]: ese campo solo vale durante el turno que la lanza, y una tarea dura muchos turnos.
- **Hook `Stop`** [probado]: ejecuta los tests rápidos al final de cada turno. No hace nada en modo plan y comprueba `stop_hook_active` para no entrar en bucle. **Sin `jq` sale con código 1** [implantado], un error que se ve y no bloquea. Un 0 lo escondería y un 2 entraría en bucle, porque sin `jq` no puede leer `stop_hook_active`. En proyectos grandes, el «sello» (la huella del árbol en el último verde) evita volver a ejecutar las suites sin cambios.
- **Reglas `ask` sobre la configuración calibrada y los datos de referencia** [implantado]: en modo auto siguen preguntando (la documentación dice que una regla `ask` explícita fuerza el aviso y se evalúa antes que el clasificador). Se escriben para `Edit` y para `Write`. La barra inicial (`/config/**`) ancla la ruta a la raíz del proyecto; sin ella, una regla `ask` casa con un directorio de ese nombre a cualquier profundidad. Si en la prueba en vivo alguna de las cuatro combinaciones no preguntara, se pasa a la forma sin barra. **Límite:** solo cubren las herramientas `Edit` y `Write`; un `sed -i` o una redirección desde Bash sobre esos ficheros no las activa. Es una barandilla de comportamiento, como las reglas `deny`.
- **Hook `SessionStart`** [implantado]: su salida entra en el contexto en cada apertura, reanudación, `/clear` y compactación. Rama, última etiqueta (`git describe --tags --abbrev=0`, «ninguna» si no hay), línea «Hito en curso» de `AGENTS.md` y `git status -sb`. Solo `git` y `grep` locales, siempre código 0 y en milisegundos.
- **El `Stop` avisa de que empieza** [implantado] con `statusMessage` (el texto del spinner), y en verde termina con un `systemMessage` corto: las suites que ejecutó, o por qué ninguna. El JSON se construye con `jq -n --arg`, nunca con `printf`, porque la salida de los tests puede llevar comillas.
- **En el equipo de la persona** (`~/.claude/settings.json`; no va al repositorio). El aviso y la línea de estado los comprobó Pedro en una sesión nueva el 11 de noviembre de 2026:
  - **Aviso de Windows** [probado] cuando Claude Code espera: hook `Notification` con matcher `permission_prompt|idle_prompt` que llama a `powershell.exe` desde WSL. Con `[System.Media.SystemSounds]::Asterisk.Play(); Start-Sleep -Milliseconds 800` basta: la pausa evita que el proceso termine antes de sonar.

    ```json
    "hooks": { "Notification": [ { "matcher": "permission_prompt|idle_prompt", "hooks": [ { "type": "command",
      "command": "powershell.exe -NoProfile -Command \"[System.Media.SystemSounds]::Asterisk.Play(); Start-Sleep -Milliseconds 800\"" } ] } ] }
    ```

  - **Línea de estado** [probado]: un `~/.claude/statusline.sh` con `jq` que recibe el JSON de la sesión por stdin y muestra modelo (`model.display_name`), rama (`git branch --show-current`, que el JSON no trae) y porcentaje de contexto (`context_window.used_percentage`). Se activa con `"statusLine": { "type": "command", "command": "~/.claude/statusline.sh" }` en los ajustes.

    ```bash
    #!/usr/bin/env bash
    entrada=$(cat)
    modelo=$(jq -r '.model.display_name // "?"' <<<"$entrada")
    dir=$(jq -r '.workspace.current_dir // "."' <<<"$entrada")
    pct=$(jq -r '(.context_window.used_percentage // 0) | floor' <<<"$entrada")
    rama=$(git -C "$dir" branch --show-current 2>/dev/null)
    printf '[%s] %s | %s%% contexto\n' "$modelo" "${rama:-sin rama}" "$pct"
    ```

  - **Plugin LSP de Python (pyright)** [pendiente]: primero el binario (`uv tool install pyright`) y después el plugin, buscado en `/plugin`.
  - **Remote Control** (`claude --rc`): seguir una sesión desde otro dispositivo. Solo se documenta.

### Codex [probado]

- `.codex/config.toml`: `sandbox_mode = "workspace-write"` y `approval_policy = "on-request"`.
- `.codex/rules/*.rules`: `prefix_rule` con `allow`, `prompt` y `forbidden`. La fusión está prohibida; el push y `uv sync` piden permiso.
- `.codex/hooks.json`: un `Stop` que formatea y llama al mismo script de tests. Sin `jq`, devuelve `{"systemMessage": "…"}` con código 0, que Codex muestra como aviso.
- Codex no lee las skills de Claude Code: sigue `docs/proceso/tarea.md` desde `AGENTS.md`.
- Revisión: `@codex review` en el PR, solo en las tareas críticas.

### Skills [implantado]

- **`/tarea-<proyecto> N [notas efímeras]`**: lleva una tarea del issue al PR, siguiendo `docs/proceso/tarea.md`. Las notas duraderas van como comentario «Notas del chat» del issue. Sus fases:
  - **en modo plan, solo lee:** el issue con sus comentarios, sus dependencias, las secciones enlazadas de la especificación y el plan;
  - **con el plan aprobado:** crea la rama, mueve la ficha e implementa;
  - **antes del push:** `/code-review` con su nivel y su destino (`main...<rama>`); clasifica todos los hallazgos, hace las correcciones con N1 y después lanza una sola N3 en segundo plano mientras escribe el anexo y el PR;
  - **al final:** abre el PR con la plantilla y comprueba que la ficha está en «En revisión».
- **`/sincronizar [N]`**, tras la fusión y después de `/clear`:
  1. comprueba que el PR está fusionado; si no, para;
  2. `git pull --ff-only` en `main` y comprueba que contiene el commit de la fusión;
  3. borra la rama local solo si su punta está contenida en el PR (`refs/pull/N/head`, que GitHub conserva aunque se borre la rama);
  4. `git fetch --prune`, y `uv sync` si cambió `uv.lock`;
  5. comprueba que los issues se cerraron y que sus fichas están en «Hecho»;
  6. muestra la siguiente ficha.
- **Cómo se escriben:**
  - `.claude/skills/<nombre>/SKILL.md`, con `disable-model-invocation: true` para que solo se lancen a mano;
  - los argumentos, con `$ARGUMENTS`;
  - en YAML, un `argument-hint` con corchetes va entre comillas;
  - las reglas que valen toda la tarea van **arriba**, porque tras compactar puede quedar solo el principio de la skill;
  - una skill puede lanzar `/code-review` con la herramienta Skill; se le pasa siempre el nivel, porque si no reutiliza el último tecleado;
  - **los id del tablero se leen en cada uso** (`gh project field-list`), nunca de memoria.
- **`cerrar-hito`** [piloto 5.8] y **`crear-tareas`**, de la especificación a los issues [pendiente, hito 7].
- **Subagente `mutante`** para las versiones incorrectas en worktree [piloto 5.2].
- **Plugins:** solo el LSP del lenguaje (pyright en Python) [implantado, A5]. Superpowers y feature-dev quedan descartados porque chocan con la metodología propia. Para GitHub se usa `gh` en lugar del MCP de GitHub.

## 6. Documentación (docs-as-code) [implantado]

| Tipo | Dónde | Quién la mantiene |
| --- | --- | --- |
| Índice: dónde vive cada cosa | `docs/README.md` | El chat, por PR |
| Diseño (visión, modelo, metodología, QA, registro de decisiones) | `docs/diseno.md` | El chat redacta; entra por PR |
| Especificación de cada hito: el contrato antes del código, con su anexo | `docs/specs/hito-N.md` | Fusionar su PR equivale a aprobarla; la entrada del anexo de cada tarea la añade el PR de esa tarea |
| Decisiones (ADR) | `docs/decisiones/NNNN-titulo.md` | Al cerrar el hito, o con la especificación |
| Proceso: flujo, tarea, lecciones y este documento | `docs/proceso/` | El chat, por PR |
| Seguimiento | Issues, tablero y GitHub Releases | Automático al fusionar |
| Aprendizaje personal | `docs/diario/` | La persona y el chat |

- **Cabecera de estado** en cada especificación, debajo del título: `> **Estado:** en curso`, o `cerrado (<etiqueta>)`, o `documento vivo`.
- **Diátaxis:** no se mezclan en una página la explicación, la guía, la referencia y el contrato.
- **Plantilla de especificación de hito:** objetivo y alcance; conceptos; especificación; valores a mano; estructura del código; tests y versiones incorrectas con su predicción; decisiones; tareas con ramas, orden y dependencias; flujo de git; criterios de aceptación; para versiones posteriores; fuentes; anexo.
- **Los diagramas, en Mermaid** dentro del markdown. Se ven en GitHub y, con la extensión «Markdown Preview Mermaid Support», en la vista previa de Cursor.
  - Se resalta con `classDef`, con una frase de leyenda debajo.
  - Si `linkStyle` colorea flechas por su posición, lleva un comentario `%%` que lo avise.
  - A cualquier bloque generado se le cuentan los delimitadores antes del commit.
- **Los ficheros grandes no se leen enteros:** `grep -n '^#'` y después rangos de líneas.
- **Web de documentación** [piloto 5.8]: Zensical (el sucesor de Material for MkDocs) en GitHub Pages, con un job `docs` que construye en modo estricto y comprueba los enlaces.

### Migrar documentación que vive fuera del repositorio [probado en la P.2]

Si el proyecto empezó con la documentación en un documento online (en EDsim, un Claude Doc con una pestaña por documento):

1. **Comparar antes de mover.** Se exporta cada pestaña y se compara con lo que ya hubiera en el repositorio. Así se sabe qué falta en cada lado.
2. **Exportar con un script.** El agente decodifica la exportación y escribe el fichero. Nunca reescribe el contenido él mismo: en EDsim, intentarlo con 92 KB cortó la respuesta de la API a los 16 minutos.
3. **Diff normalizado:** se quitan firma, cabecera, diagramas y escapes, y se compara. Solo deben quedar las diferencias previstas. Es lo que permite archivar el original sabiendo que no se perdió nada.
4. **Los diagramas, a Mermaid** en lo vivo. En lo cerrado basta un enlace al original archivado.
5. **Una nota de archivo en el original**, debajo del título: «Archivo. Desde <fecha>, el original está en el repositorio: <ruta>. Ya no se edita.» La pone el chat cuando el PR ya está fusionado.

## 7. GitHub como gestor de trabajo [implantado]

**Etiquetas**, en grupos con prefijo, un color por grupo:
- `tipo:tarea`, `tipo:bug`, `tipo:idea`;
- `area:<zona>`; en EDsim: motor, perfiles, live, app, calibracion, notebooks, proceso, ci, docs;
- `quien:claude-code`, `quien:codex`, `quien:pedro`, para filtrar el tablero por quién tiene que hacer cada cosa, incluida la persona;
- `critica`, para las tareas que llevan `@codex review`.

**Milestones:** uno por hito, uno por tarea de proceso con nombre (P.2, P.3) y uno de pendientes (Backlog).

**Plantillas:**
- **Issues** (`.github/ISSUE_TEMPLATE/`, formularios YAML):
  - **tarea:** objetivo, contenido, criterios de aceptación, enlace a la especificación, rama, quién, si es crítica, de qué depende;
  - **bug:** qué pasa, qué debería pasar, cómo reproducirlo, commit, salida;
  - **idea:** qué, por qué, cuándo tendría sentido.
- **PR:** «Closes #», resumen, ajustes de la aprobación, comprobaciones (N1, N2, N3, integración, documentación al día), versiones incorrectas, medidas, métricas de la tarea y ajustes de la revisión. Las plantillas solo se activan cuando llegan a `main`.

**Tablero de Projects:**
1. Créalo en la web con la plantilla *Board* y «Import items from repository», que deja activo el **añadido automático** de issues nuevos.
2. Columnas de Status: **Backlog → Próximo → En curso → En revisión → Hecho**, renombrando las de serie **conservando sus id**, para no desconectar los workflows.
3. Configura los workflows (*⋯ → Workflows*):
   - «Item added» → Backlog;
   - «Pull request linked to issue» → **En revisión** (de serie va a la antigua «In Progress»);
   - «Item closed» y «Pull request merged» → Hecho.
4. Enlázalo al repositorio con `gh project link`.

**Issues:**
- **El issue resume y enlaza la especificación, nunca la copia.** Los criterios de aceptación son de 3 a 6 viñetas que citan la especificación.
- **Dependencias:** manda la **nativa** (*blocked-by*), que GitHub muestra en el tablero y que la skill consulta con `gh issue view N --json blockedBy`. El cuerpo guarda el **motivo**. Un issue nuevo con dependencias lleva las dos.
- **Cuidado con los números:** los issues y los PR comparten numeración, y pueden coincidir con los de las decisiones (en EDsim, issues #63 a #94 y decisiones 67 a 79). Las decisiones se escriben siempre «decisión 69 (H5-3)», sin almohadilla, porque con ella GitHub enlaza un issue.
- **Crear issues por script, de forma idempotente:** se comprueba por título que no existe, y para el tablero se busca la ficha antes de añadirla, porque el añadido automático compite con `gh project item-add`.

**Versiones:** etiqueta por hito y `gh release create <etiqueta> --generate-notes` [piloto 5.8].

**Mantenimiento:** Dependabot para las dependencias [pendiente: comprobar que entiende `uv.lock`].

## 8. El ciclo de trabajo

| Fase | Quién | Qué ocurre | Qué queda |
| --- | --- | --- | --- |
| Idea | La persona, el chat o un agente | Lo que surge en cualquier momento | Issue `tipo:idea` o `tipo:bug` en el Backlog |
| Sesión conceptual | El chat | Conceptos explicados con ejemplos y preguntas hasta entender; decisiones una a una | Borrador de la especificación |
| Especificación | El chat redacta; entra por PR | Fusionar es aprobar | `docs/specs/hito-N.md` |
| Planificación | Claude Code con `gh` | Un issue por tarea, con dependencias, en su milestone | El tablero |
| Priorizar | La persona | Arrastra fichas a «Próximo» | — |
| Implementación | Claude Code (`/tarea-… N`) | Plan en modo plan, revisado por la persona y el chat; aprobación con modo auto; commits por paso lógico | Rama y PR «Closes #N», con código, tests y la entrada del anexo |
| QA | Automático, `/code-review`, Codex y el chat | Tests por niveles, CI, revisión adversaria del propio diff, `@codex review` en las críticas, revisión del chat recalculando, comprobación en vivo de la persona | PR en verde |
| Fusión | La persona | *Squash and merge* | Issue cerrado y ficha en «Hecho» |
| Sincronizar | La persona: `/clear` y `/sincronizar` | `main` al día, rama borrada, la siguiente ficha | Árbol limpio |
| Versión | `cerrar-hito` | ADR, diario, etiqueta y Release | La versión publicada |

El detalle está en [`flujo.md`](flujo.md) (con diagramas) y en [`tarea.md`](tarea.md) (los pasos de cada tarea).

**Métricas de cada tarea** [implantado], en la plantilla del PR:
- idas y vueltas de la persona entre el chat y los agentes;
- tiempo de pared del plan al PR;
- rondas de revisión;
- lo que encontró cada revisor.

## 9. Modelos, sesiones y coste

- **Una sesión por tarea, y `/clear` entre tareas**: también entre la implementación y la revisión o la sincronización. En EDsim, el 93 % del consumo de un día venía de sesiones largas que mezclaban tareas y reenviaban todo el contexto en cada turno. Ponle nombre a cada sesión (`/rename`) y retómala con `/resume`.
- **El modelo según el trabajo:**
  - **Sonnet con esfuerzo medio** para lo mecánico: migrar ficheros, crear issues con `gh`, sincronizar.
  - **Opus con esfuerzo alto** para lo que necesita criterio: instrucciones que leerán todas las sesiones futuras, skills, tareas críticas.
  - **Opus** para `/doctor prompt-audit`.
  - **Sonnet, o un subagente con Sonnet**, para las gráficas.
- **No se cambia de modelo a mitad de una tarea.** La caché de la conversación es por modelo, y cambiar obliga a reenviarlo todo. Si hay que cambiar, al principio de la sesión.
- **Diagnóstico periódico:** `/insights` (dónde se atasca el flujo), `/usage` (dónde se va el consumo) y `/doctor prompt-audit`. Se repiten al cerrar cada hito y se comparan con los anteriores.
- **Conectores de claude.ai en Claude Code:** los que tenga la cuenta aparecen en `/mcp`. En EDsim, el de Claude Docs permitió que el agente exportara él mismo el documento online. Los que no pintan nada no estorban, porque sus herramientas se cargan bajo demanda.
- **Lo que selecciones en el editor se manda como contexto.** Si la terminal de Claude Code dice «N lines selected», quita la selección antes de escribir, o desconecta el editor con `/ide`.

## 10. QA: los niveles de tests [probado]

| Nivel | Cuándo | Qué se ejecuta |
| --- | --- | --- |
| N0 | Al editar | `ruff format` (hook `PostToolUse`) |
| N1 | Antes de cada commit | ruff y los ficheros de test del área tocada; pre-commit |
| N2 | Al final de cada turno | `scripts/tests-rapidos.sh`: la rápida (`-m "not slow"`), con sello y con xdist donde compense |
| N3 | Antes de cada push | `scripts/tests-completos.sh`: lint, la completa, la app y los notebooks; desde la P.2, en segundo plano mientras se redacta el PR; desde el #100, una sola vez, después de la revisión propia y de sus correcciones ([ADR 0083](../decisiones/0083-una-sola-n3-tras-la-revision-propia.md)) [implantado] |
| CI | En cada push y en `main` | Un job por capa, en serie |

**Excepción:** un push que solo lleva plantillas o documentación puede ir sin N3 si la persona lo autoriza, porque el CI lo comprueba igual. Automatizarlo dentro del job es un pendiente de la P.3.

**Lecciones que se llevan a cualquier proyecto:**
- La mayor ganancia de tiempo está en no ejecutar lo que no hace falta, no en paralelizar.
- xdist solo compensa donde la ejecución en paralelo tarda como mucho el 60 % de la serie.
- Las máquinas del CI varían hasta el doble: una comparación limpia mide las dos variantes en el mismo job.

## 11. Lista de arranque de un proyecto nuevo

Es el «hito 0» genérico. Cada línea termina con su comprobación.

1. [ ] **Sesión conceptual del entorno:** qué hace cada pieza (WSL, uv, ruff, pytest, pre-commit, GitHub Flow, Actions, rulesets, Claude Code).
2. [ ] **Entorno** (sección 3), con `pull.ff only`, `fetch.prune true` y el permiso `project` de `gh`. Comprobación: `wsl -l -v`, `docker run hello-world`, `gh auth status`, `claude doctor`.
3. [ ] **Esqueleto con `uv init --package`** y una CLI mínima. Comprobación: `uv run <nombre> --version`.
4. [ ] **Calidad local** (ruff, pytest, pre-commit, test de humo). Comprobación: pre-commit para un commit mal formateado.
5. [ ] **CI.** Comprobación: un rojo a propósito y un verde.
6. [ ] **Ruleset de `main`**, solo *squash* y borrado automático de ramas. Comprobación: un push directo a `main` es rechazado.
7. [ ] **Agentes:** `AGENTS.md` (con las reglas de shell y de después de la fusión), `CLAUDE.md`, `.claude/settings.json`, hooks y `.codex/`. Comprobación: los hooks sin `jq` fallan a la vista, y `/doctor prompt-audit` en modo plan sale limpio.
8. [ ] **Documentación:** la estructura de `docs/` de la sección 6, `docs/README.md` y la primera ADR.
9. [ ] **GitHub:** etiquetas, milestones, plantillas, tablero con sus workflows y enlace al repositorio. Comprobación: un issue nuevo entra solo en Backlog, y la plantilla de PR aparece.
10. [ ] **Skills `/tarea-…` y `/sincronizar`**, con `docs/proceso/tarea.md` y `flujo.md`. Comprobaciones:
    - prueba en seco: una tarea con una dependencia abierta para, y `/sincronizar` sin PR para;
    - después, una tarea pequeña de principio a fin.
11. [ ] **Diseño general y especificación del primer hito** por PR, y sus issues.
12. [ ] **Cierre del hito 0:** ADR de las decisiones de la sección 2, diario, etiqueta `v0.0-hito0` y Release.

## 12. Qué adaptar según el proyecto

- **Otro lenguaje:** se cambian uv, ruff y pytest por los equivalentes del lenguaje, y el plugin LSP por el suyo. El resto del flujo no cambia.
- **Repositorio privado:** hace falta GitHub Pro para el ruleset; sin él, `main` se queda sin protección real. Para los agentes en la nube y `@claude` se instala la GitHub App.
- **Equipo:** aprobaciones obligatorias en el ruleset, un `CODEOWNERS` y el tablero compartido; los secretos de los workflows, a nivel de organización.
- **Sin Codex:** la revisión independiente de las críticas pasa a `/code-review` con esfuerzo alto o a un subagente revisor con contexto limpio.
- **Sin componente didáctico:** se puede prescindir del estilo `Explanatory`, pero no de la sesión conceptual corta antes de cada hito.

## 13. Lecciones de la implantación (P.2)

- **Antes de mover nada, se compara.** El diff normalizado convierte «creo que está todo» en «está todo».
- **El agente escribe ficheros grandes con scripts, no con su propia salida.** Las respuestas muy largas se cortan y cuestan mucho.
- **Las instrucciones se contradicen solas con el tiempo.** Una regla nueva que relaja otra antigua tiene que nombrar la excepción en los dos sitios. `/doctor prompt-audit` lo detecta.
- **Las automatizaciones de GitHub compiten con los scripts.** El añadido automático y `item-add`, o el workflow de PR enlazado y la skill, se pisan si no se coordinan. Lo robusto es comprobar el estado y actuar solo si falta.
- **Un dato del plan puede perderse al ejecutarlo.** Una dependencia prevista que no llegó al issue apareció en la prueba en seco. Por eso la prueba en seco va antes del primer uso real.
- **Los números con el mismo formato se confunden.** Issues y decisiones del mismo rango necesitan una notación distinta.
- **Un fallo de red puede ser del entorno y no de la red.** Si la extensión funciona y la terminal no, el problema está en lo que difiere entre las dos.

## 14. Estado de las piezas en prueba

| Pieza | Se prueba en | Resultado |
| --- | --- | --- |
| Migración de la documentación al repositorio | P.2, A1 | Probado: diff normalizado limpio, original archivado |
| Instrucciones coherentes y `/doctor prompt-audit` | P.2, A2 | Probado: segundo audit limpio |
| GitHub como gestor (issues, tablero, dependencias) | P.2, A3 | Implantado: 32 issues; falta su uso en una tarea |
| `/tarea-edsim` y `/sincronizar` | Prueba en seco (P.2), A5 (prueba de humo) y 5.1 | A5, `/tarea-edsim`: probada de punta a punta. Seis hallazgos en [p2.md](p2.md); los de más peso: la tarea sin fichero de especificación (arreglado), cómo presentar el plan fuera del modo plan y si los scripts de los hooks cuentan para repetir la N3 (los dos, resueltos en la A6). `/sincronizar` ya funcionó con los PR #95 y #96. Falta 5.1 |
| Aviso de Windows y línea de estado (en `~/.claude`) | P.2, A6 | Probado por Pedro en una sesión nueva: suena al pedir permiso y la línea muestra modelo, rama y % de contexto |
| Plugin LSP de Python (pyright) | — | Pendiente: `/plugin` es interactivo y no lo lanza el agente |
| Subagentes para las versiones incorrectas | 5.2 | Probado con cinco versiones incorrectas (cuatro en paralelo), con predicción frente a observado. El worktree parte del `HEAD` local (`worktree.baseRef = "head"`), con su `uv sync --offline --frozen` y `edsim.__file__` comprobado dentro, sin tocar el árbol principal. Claude Code borra los worktrees limpios. Dos avisos: `.claude/agents/` se carga al abrir la sesión (un subagente creado a mitad de sesión no existe hasta la siguiente), y un worktree cuyo subagente deja trabajo en segundo plano sigue bloqueado. Detalle en el anexo de la 5.2 de [hito-5.md](../specs/hito-5.md) |
| `@claude` en el PR | 5.3 | — |
| El chat lee el PR y el CI | 5.4 | — |
| Codex desde el issue | 5.5 | — |
| Sesión en la nube | 5.7 | — |
| `cerrar-hito`, Release y web | 5.8 | — |

## Referencias

- [Especificación del hito 0](../specs/hito-0.md): el entorno y el repositorio en detalle.
- [`docs/diseno.md`](../diseno.md), secciones «Metodología» y «Calidad y tests (QA)».
- [`flujo.md`](flujo.md) y [`tarea.md`](tarea.md).
- ADR [0008](../decisiones/0008-claude-code-escribe-el-codigo.md), [0009](../decisiones/0009-librerias-sin-reimplementar.md), [0011](../decisiones/0011-github-flow-con-ci-obligatorio.md), [0012](../decisiones/0012-entorno-windows-con-wsl2.md), [0014](../decisiones/0014-repositorio-publico-con-ruleset.md), [0015](../decisiones/0015-idiomas-del-proyecto.md) y [0047](../decisiones/0047-tests-por-niveles.md); APP-0003.
- Documentación de Claude Code: [buenas prácticas](https://code.claude.com/docs/en/best-practices.md), [skills](https://code.claude.com/docs/en/skills.md), [subagentes](https://code.claude.com/docs/en/sub-agents.md), [hooks](https://code.claude.com/docs/en/hooks-guide.md), [memoria, AGENTS.md y reglas](https://code.claude.com/docs/en/memory.md), [GitHub Actions](https://code.claude.com/docs/en/github-actions.md), [sesiones en la nube](https://code.claude.com/docs/en/claude-code-on-the-web.md).
