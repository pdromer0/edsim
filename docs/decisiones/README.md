# Registro de decisiones (ADR)

Un ADR (*Architecture Decision Record*) es un documento corto que registra una decisión importante: el contexto en que se tomó, qué se decidió, qué alternativas se descartaron y qué consecuencias tiene. Sirve para que, meses después, se entienda por qué el sistema es como es.

Un ADR aceptado no se reescribe. Si la decisión cambia, se escribe un ADR nuevo que la sustituye y se marca el antiguo como `Sustituida por NNNN`.

## Cuándo escribir uno

Cuando una decisión es difícil de revertir, afecta a varias partes del sistema o hubo alternativas razonables. Las decisiones del brainstorming están en [diseno.md](../diseno.md#registro-de-decisiones-y-preguntas-abiertas) y se convierten en ADRs al cerrar el hito 0.

## Nombres

`NNNN-titulo-en-minusculas.md`, numerados de forma correlativa: `0001-simpy-como-motor.md`, `0002-...`.

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
