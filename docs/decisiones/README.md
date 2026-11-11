# Registro de decisiones (ADR)

Un ADR (*Architecture Decision Record*) es un documento corto que registra una decisión importante: el contexto en que se tomó, qué se decidió, qué alternativas se descartaron y qué consecuencias tiene. Sirve para que, meses después, se entienda por qué el sistema es como es.

Un ADR aceptado no se reescribe. Si la decisión cambia, se escribe un ADR nuevo que la sustituye y se marca el antiguo como `Sustituida por NNNN`.

## Cuándo escribir uno

Cuando una decisión es difícil de revertir, afecta a varias partes del sistema o hubo alternativas razonables. Las decisiones del brainstorming están en [diseno.md](../diseno.md#registro-de-decisiones-y-preguntas-abiertas) y se convierten en ADRs al cerrar el hito 0.

## Nombres

`NNNN-titulo-en-minusculas.md`, numerados de forma correlativa: `0001-simpy-como-motor.md`, `0002-...`. El número es el de la decisión en el [registro del diseño](../diseno.md#registro-de-decisiones-y-preguntas-abiertas), y del 0067 al 0079 están reservados a las decisiones del hito 5: un ADR nuevo toma el número de su decisión (hoy, a partir del 0083), no el primero que falte.

## Plantilla

```markdown
# NNNN. Título de la decisión

- **Estado:** Propuesta | Aceptada | Sustituida por NNNN
- **Fecha:** AAAA-MM-DD

## Contexto

Qué problema hay que resolver y qué restricciones existen.

## Decisión

Qué se decide, en una o dos frases.

## Alternativas consideradas

- Alternativa A: por qué no.
- Alternativa B: por qué no.

## Consecuencias

Qué se gana, qué se pierde y qué queda pendiente.
```

## Índice

- [0001. El laboratorio sirve a tres objetivos a la vez](0001-tres-objetivos-del-laboratorio.md)
- [0002. Tipo y tamaño de centro parametrizables](0002-centro-parametrizable.md)
- [0003. Profesionales como pools anónimos en la v0](0003-profesionales-como-pools-anonimos.md)
- [0004. Motivos de consulta agrupados](0004-motivos-de-consulta-agrupados.md)
- [0005. Simulación de eventos discretos con SimPy y pacer propio](0005-simpy-y-pacer-propio.md)
- [0006. Log de eventos como fuente de verdad y ground truth separado](0006-log-de-eventos-y-ground-truth.md)
- [0007. Un flujo aleatorio por fuente de azar](0007-un-flujo-aleatorio-por-fuente.md)
- [0008. Claude Code escribe el código tras una sesión conceptual](0008-claude-code-escribe-el-codigo.md)
- [0009. Librerías directamente, sin reimplementar fundamentos](0009-librerias-sin-reimplementar.md)
- [0010. Apache Kafka 4 (KRaft) como broker, con Redpanda Console](0010-kafka-kraft-y-redpanda-console.md)
- [0011. GitHub Flow con pull requests, CI obligatorio y fusión reservada a Pedro](0011-github-flow-con-ci-obligatorio.md)
- [0012. Desarrollo en Windows con WSL2, Docker Desktop y Cursor](0012-entorno-windows-con-wsl2.md)
- [0013. Centro base de 300 urgencias al día](0013-centro-base-300-urgencias.md)
- [0014. Repositorio público en GitHub, con ruleset que protege main](0014-repositorio-publico-con-ruleset.md)
- [0015. Idiomas del proyecto](0015-idiomas-del-proyecto.md)
- [0016. Métricas derivadas de los registros por cliente](0016-metricas-derivadas-de-los-registros.md)
- [0017. Tests estadísticos marcados como `slow`](0017-tests-estadisticos-marcados-slow.md)
- [0018. Notebooks de Jupyter sin lógica propia](0018-notebooks-jupyter-sin-logica.md)
- [0019. Perfiles de llegadas en TOML normalizados a media 1](0019-perfiles-de-llegadas-en-toml.md)
- [0020. Tasa λ(t) continua con interpolación lineal periódica](0020-tasa-continua-interpolada.md)
- [0021. *Thinning* de Lewis–Shedler perezoso, con cota por día comprobada](0021-thinning-perezoso-con-cota-por-dia.md)
- [0022. Sobredispersión con un efecto diario gamma parametrizado por el CV](0022-efecto-diario-gamma-por-cv.md)
- [0023. Validación de las llegadas con cinco pruebas al nivel 0,01](0023-validacion-con-cinco-pruebas.md)
- [0024. El paciente como proceso SimPy, con todos sus sorteos al llegar](0024-paciente-como-proceso-con-sorteos-al-llegar.md)
- [0025. Tres pools con prioridad `(nivel, llegada)` y desalojo solo del nivel 1](0025-tres-pools-con-prioridad-y-desalojo-del-nivel-1.md)
- [0026. Plantilla por turnos con reservas de capacidad](0026-plantilla-por-turnos-con-reservas.md)
- [0027. Log de eventos JSONL con sobre común, `sim_time` y `event_id` determinista](0027-log-jsonl-con-sobre-comun.md)
- [0028. Ground truth del motor en ficheros aparte del log](0028-ground-truth-del-motor-aparte.md)
- [0029. Calentamiento y horizonte en días completos](0029-calentamiento-y-horizonte-en-dias-completos.md)
- [0030. Validación del motor por niveles, al nivel 0,01](0030-validacion-del-motor-por-niveles.md)
- [0031. App web incremental](0031-app-web-incremental.md)
- [0032. Ejecuciones en carpetas reproducibles](0032-ejecuciones-en-carpetas-reproducibles.md)
- [0033. Variantes TOML con comentarios](0033-variantes-toml-con-comentarios.md)
- [0034. El hito 4 cubre el paciente clínico; destino, abandono y boarding van al hito 5](0034-alcance-del-hito-4.md)
- [0035. Solo adultos de 15 años o más, con cuatro bandas de edad](0035-solo-adultos-con-cuatro-bandas.md)
- [0036. Perfiles clínicos en `config/perfiles.toml`, aparte del centro](0036-perfiles-clinicos-aparte-del-centro.md)
- [0037. Los 17 motivos desde el principio, cada valor con su estado y pesos base derivados](0037-diecisiete-motivos-con-estado-y-pesos-derivados.md)
- [0038. Gravedad latente y triaje ordinal con ruido y sesgo](0038-gravedad-latente-y-triaje-con-error.md)
- [0039. El nivel 1 asignado se clasifica en la puerta y va directo al box](0039-nivel-1-en-la-puerta.md)
- [0040. Tres relojes hasta el médico y cumplimiento Manchester desde la clasificación](0040-tres-relojes-y-cumplimiento-desde-la-clasificacion.md)
- [0041. Centro base realista, calibrado a lo observado con dos mandos de objetivos separados](0041-centro-realista-calibrado-con-dos-mandos.md)
- [0042. Pruebas de cuatro tipos en una sola ronda](0042-pruebas-de-cuatro-tipos-en-una-ronda.md)
- [0043. Sorteos sincronizados: Gumbel-max, z estándar transformadas y ocho flujos](0043-sorteos-sincronizados-con-gumbel-max.md)
- [0044. Modelo clínico opcional durante el hito y por defecto en el cierre](0044-modelo-clinico-por-defecto-en-el-cierre.md)
- [0045. Con el modelo clínico, los niveles 4 y 5 esperan los resultados fuera del box](0045-espera-de-resultados-fuera-del-box.md)
- [0046. La parada / crítico pesa un 0,3 % con una gravedad alta y poco dispersa](0046-parada-a-la-puerta.md)
- [0047. Tests por niveles según el punto del ciclo](0047-tests-por-niveles.md)
- [0048. El hito 6 (tiempo real) va antes que el 5](0048-hito-6-antes-que-el-5.md)
- [0049. Código en `edsim.live`; `confluent-kafka` como extra opcional importado solo en `live/kafka.py`](0049-subpaquete-live-y-extra-kafka.md)
- [0050. Tres capas de tests: rápidos sin broker, slow e integración aparte](0050-tres-capas-de-tests.md)
- [0051. Motor por pasos con `peek()` y `step()`, sin cambiar las huellas](0051-motor-por-pasos.md)
- [0052. Pacer síncrono con objetivos absolutos y reloj inyectable](0052-pacer-sincrono-con-objetivos-absolutos.md)
- [0053. Control en vivo por el topic `ed.control` y `edsim directo control`](0053-control-en-vivo-por-ed-control.md)
- [0054. Cuatro topics, reparto por `episode_id` y topics creados por EDsim](0054-cuatro-topics-con-reparto-por-episodio.md)
- [0055. Productor idempotente y «al menos una vez» con consumidores idempotentes](0055-productor-idempotente-y-al-menos-una-vez.md)
- [0056. El valor es la línea del JSONL y la hora de llegada es la marca `LogAppendTime`](0056-valor-jsonl-y-hora-de-llegada-del-broker.md)
- [0057. JSON Schema 2020-12 generado del catálogo, un fichero por versión](0057-json-schema-generado-del-catalogo.md)
- [0058. El censo inicial son eventos del log, no una foto del estado](0058-censo-inicial-con-eventos.md)
- [0059. Dos arranques: con la fecha del perfil o anclado al calendario](0059-dos-arranques-fecha-del-perfil-o-anclado.md)
- [0060. Replay de una ejecución guardada con el mismo pacer, censo y productor](0060-replay-con-el-mismo-pacer.md)
- [0061. Horizonte finito y un `fin` que dice por qué terminó](0061-horizonte-finito-y-fin-limpio.md)
- [0062. Versiones fijadas con etiqueta exacta: Kafka, Redpanda Console y confluent-kafka](0062-versiones-fijadas.md)
- [0063. Job `tests-kafka` en el CI con el mismo `compose.yaml`](0063-job-tests-kafka.md)
- [0064. Etiqueta de cierre `v0.6-hito6`](0064-etiqueta-v0-6-hito6.md)
- [0065. El simulador corre fuera de Docker; Compose levanta solo Kafka y la consola](0065-simulador-fuera-de-docker.md)
- [0066. `run_id` del directo con la semilla y la hora de arranque; el replay conserva el suyo](0066-run-id-del-directo.md)
- [0080. El repositorio es la fuente de verdad de la documentación](0080-repositorio-fuente-de-verdad-de-la-documentacion.md)
- [0081. GitHub como gestor del trabajo: issues, milestones, tablero y dependencias nativas](0081-github-como-gestor-del-trabajo.md)
- [0082. El ciclo de cada tarea se escribe una vez en `tarea.md` y lo ejecutan las skills](0082-ciclo-de-cada-tarea-en-tarea-md-y-skills.md)

El número de cada ADR es el de su decisión en el [registro del diseño](../diseno.md#registro-de-decisiones-y-preguntas-abiertas). Por eso falta del 0067 al 0079: son las decisiones del hito 5, reservadas hasta que se cierre.
