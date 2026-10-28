# 0014. Repositorio público en GitHub, con ruleset que protege main

- **Estado:** Aceptada
- **Fecha:** 2026-10-27

## Contexto

GitHub Flow exige que `main` solo cambie por pull request con el CI en verde ([0011](0011-github-flow-con-ci-obligatorio.md)). En el plan gratuito de GitHub, los rulesets solo están disponibles en repositorios públicos ([spec del hito 0](../specs/hito-0.md#github-repositorio-protección-de-main-y-ci)).

## Decisión

El repositorio `edsim` es público. Un ruleset protege `main`:

- exige pull request antes de fusionar, sin aprobaciones obligatorias;
- exige el check `tests` en verde;
- bloquea el push forzado y el borrado de la rama.

Además, el repositorio solo permite *Squash and merge* y borra la rama al fusionar.

Motivo: los rulesets solo están disponibles en repositorios públicos del plan gratuito, y el proyecto usa datos sintéticos, sin secretos.

## Alternativas consideradas

- Repositorio privado sin GitHub Pro: la protección de `main` no se podría aplicar, y quedarían solo la regla de Claude Code y la disciplina del flujo.

## Consecuencias

- Un push directo a `main` es rechazado.
- Todo lo que se sube es público, así que el repositorio no debe contener secretos ni datos reales.
- Sirve además de portfolio.
