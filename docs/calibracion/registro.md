# Registro de calibración

Cada cambio de un parámetro calibrado, con su valor de antes y de después, el KPI que lo
decide, el motivo y el comando que reproduce cada tabla (regla 1 de la calibración,
[docs/specs/hito-4.md](../specs/hito-4.md), «Calibración»). Los CSV que escriben los
comandos van a `resultados/`, que no se sube.

## Tarea 4.6b: enfermería de triaje y médicos (6 de noviembre de 2026)

Rama `feat/h4-calibracion`. Modelo clínico con `config/llegadas.toml`,
`config/perfiles.toml` y `config/objetivos.toml`; boxes (30), duraciones y
`espera_resultados_fuera` (`[4, 5]`) fijos.

> **Desde la tarea 4.6c**, la calibración usa la ventana anual y la plantilla de `config/`
> es otra (ver «Tarea 4.6c» abajo). Las tablas de esta sección se reproducen con
> `--ventana inicio` y el centro de entonces, fijado en `tests/data/centro_4_6b.toml`, por
> ejemplo `uv run edsim calibracion evaluar --ventana inicio --centro
> tests/data/centro_4_6b.toml`. El cumplidor de entonces ([15, 15, 6]) sale igual con la
> regla de días enteros de la 4.6c (12 de 120 días fuera en los niveles 4 y 5, justo el
> 10 %).

### Cambios

| Parámetro | Antes | Después | KPI | Motivo |
| --- | --- | --- | --- | --- |
| `recursos.enfermeria_triaje` | [3, 3, 2] | [3, 2, 1] (u de 0,795 a 0,8325) | Pretriaje medio, niveles 2 a 5: 1,37 → 10,65 min (horquilla 6–15; SAS 12,4) | Con [3, 3, 2] el pretriaje quedaba muy por debajo de la horquilla; [3, 2, 1] es la única plantilla de la regla que la cumple |
| `recursos.medicos` | [12, 12, 7] | [12, 11, 5] (u de 0,81 a 0,8475) | Reloj A, niveles 2 a 5: 25,0 → 54,5 min (horquilla 35–70) | Con la enfermería ya fija, la que pasa y queda más cerca del centro de la horquilla (52,5), porque el objetivo no tiene referencia única |
| `objetivos.tiempo_medico_nivel_3.uso` | ajuste | comprobación | Reloj A del nivel 3: como mucho 22,9 min con cualquier plantilla de la regla (horquilla 45–75) | Discrepancia estructural (ver «El nivel 3, de ajuste a comprobación»); el cambio se decidió después de medir la sensibilidad |
| Centro cumplidor (`config/centro_cumplidor.toml`) | — | médicos [15, 15, 6] (u de 0,625 a 0,635) | Días fuera de Manchester con el reloj C, niveles 2 a 5: 0,8 / 0 / 10,0 / 10,0 % | El u más alto con todos los niveles 2 a 5 a un máximo del 10 % de días fuera, de media entre réplicas |

### Método

- **Regla de la plantilla equivalente.** Personal del turno = ⌈carga del turno / u⌉, con
  un u por mando. Carga de enfermería = llegadas por hora × (1 − p₁) × media del triaje
  / 60 (p₁ = 0,40 %, media 5,79 min); carga de médicos = llegadas por hora × 32,37 min /
  60. Llegadas por hora del día medio: 17,36 / 16,5 / 6,3 (turnos de 8, 15 y 22 h).
  Cargas: enfermería 1,668 / 1,585 / 0,605; médicos 9,365 / 8,903 / 3,399. Con u de 0,55
  a 0,99 en pasos de 0,0025 salen 5 plantillas de enfermería y 20 de médicos.
- **Réplicas.** 10 réplicas con números aleatorios comunes (el hijo i de la semilla es
  la réplica i para todas las plantillas), 14 días con 2 de calentamiento.
- **Día de vaciado.** Cada réplica simula un día más, con llegadas (horizonte de 15
  días), y solo se mide a los llegados en la ventana [2, 14). Así, los que llegan al
  final de la ventana y más esperan no quedan fuera de las medias. Los llegados en la
  ventana sin salida al final del horizonte (censurados) se cuentan por réplica: 0 en
  todas las plantillas que pasan, como mucho un 0,23 % hasta u = 0,935, y un 1,9 % y un
  8,6 % en las dos de médicos más apretadas.
- **Regla 4.** Un objetivo pasa si la media entre réplicas cae dentro de la horquilla y
  la anchura de su IC al 95 % (t de Student, t₉ = 2,262) no supera la de la horquilla.
- **Semillas.** Ajuste con 2026; comprobación con 2027, sin reajustar.
- **Orden (decisión 41 revisada).** Primero la enfermería contra el pretriaje; con ella
  fija, los médicos contra el reloj A.

### Sensibilidad de la enfermería (médicos [12, 12, 7])

`git show 341ec2f:config/centro.toml > centro_antes.toml` y
`uv run edsim calibracion sensibilidad --mando enfermeria_triaje --centro centro_antes.toml`
(5 min 44 s, en paralelo con otras seis ejecuciones). ✓ pasa, ✗ no pasa. Medias entre
réplicas, en minutos o en %.

| Plantilla | u | Pretriaje | A 2–5 | A nivel 3 | % sobre Manchester (A) | % pretriaje > 5 | Censurados (máx.) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [4, 3, 2] | 0,5500–0,5550 | 0,78 ✗ | 24,35 ✗ | 9,74 ✗ | 8,29 ✗ | 4,75 ✗ | 0,00 % |
| [3, 3, 2] | 0,5575–0,6050 | 1,37 ✗ | 24,99 ✗ | 10,29 ✗ | 9,02 ✗ | 9,34 ✗ | 0,00 % |
| [3, 3, 1] | 0,6075–0,7925 | 5,04 ✗ | 26,65 ✗ | 13,53 ✗ | 10,54 ✓ | 20,51 ✗ | 0,00 % |
| [3, 2, 1] **(elegida)** | 0,7950–0,8325 | 10,65 ✓ | 28,73 ✗ | 18,99 ✗ | 12,67 ✓ | 39,98 ✓ | 0,00 % |
| [2, 2, 1] | 0,8350–0,9900 | 26,83 ✗ | 40,40 ✓ | 35,00 ✗ | 19,76 ✓ | 67,51 ✗ | 0,00 % |

La enfermería mueve el pretriaje y, a través de él, el reloj A; los médicos de esta
tabla no cambian. Con el centro calibrado,
`uv run edsim calibracion sensibilidad --mando enfermeria_triaje` (3 min 32 s) da la
misma columna de pretriaje, bit a bit: el pretriaje no depende de los médicos mientras
no haya censurados.

Frente a un anticipo independiente (una cola de triaje sola, 8 semanas, 5 réplicas:
1,3 / 4,4 / 10,4 / 19,8 min con [3, 3, 2], [3, 3, 1], [3, 2, 1] y [2, 2, 1]), el motor se
aparta un +5 %, +15 %, +2 % y +36 %. La última fila es la más cargada (dos enfermeras de
mañana con una carga de 1,67), y la ventana es de enero, cuyo factor mensual (1,10)
eleva la ocupación de 0,83 a 0,92: cerca de la saturación, la espera crece como
ρ/(1 − ρ).

### Sensibilidad de los médicos (enfermería [3, 3, 2])

`uv run edsim calibracion sensibilidad --mando medicos --centro centro_antes.toml`
(15 min 20 s, en paralelo).

| Plantilla | u | Pretriaje | A 2–5 | A nivel 3 | % sobre Manchester (A) | % pretriaje > 5 | Censurados (máx.) | Días fuera de Manchester (C), niveles 2 / 3 / 4 / 5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [18, 17, 7] | 0,5500–0,5500 | 1,37 ✗ | 13,00 ✗ | 8,58 ✗ | 4,70 ✗ | 9,34 ✗ | 0,00 % | 0,0 / 0,0 / 4,2 / 6,7 |
| [17, 17, 7] | 0,5525–0,5550 | 1,37 ✗ | 13,04 ✗ | 8,58 ✗ | 4,69 ✗ | 9,34 ✗ | 0,00 % | 0,0 / 0,0 / 4,2 / 6,7 |
| [17, 16, 7] (cumplidor) | 0,5575–0,5650 | 1,37 ✗ | 13,18 ✗ | 8,60 ✗ | 4,72 ✗ | 9,34 ✗ | 0,00 % | 0,0 / 0,0 / 4,2 / 7,5 |
| [17, 16, 6] | 0,5675–0,5850 | 1,37 ✗ | 16,94 ✗ | 9,72 ✗ | 6,41 ✗ | 9,34 ✗ | 0,00 % | 1,7 / 0,8 / 10,0 / 13,3 |
| [16, 16, 6] | 0,5875–0,5925 | 1,37 ✗ | 17,00 ✗ | 9,74 ✗ | 6,42 ✗ | 9,34 ✗ | 0,00 % | 1,7 / 0,8 / 10,0 / 13,3 |
| [16, 15, 6] | 0,5950–0,6225 | 1,37 ✗ | 17,38 ✗ | 9,81 ✗ | 6,49 ✗ | 9,34 ✗ | 0,00 % | 1,7 / 0,8 / 10,0 / 13,3 |
| [15, 15, 6] | 0,6250–0,6350 | 1,37 ✗ | 17,60 ✗ | 9,88 ✗ | 6,61 ✗ | 9,34 ✗ | 0,00 % | 1,7 / 0,8 / 10,0 / 13,3 |
| [15, 14, 6] | 0,6375–0,6675 | 1,37 ✗ | 18,24 ✗ | 9,98 ✗ | 6,82 ✗ | 9,34 ✗ | 0,00 % | 1,7 / 1,7 / 12,5 / 14,2 |
| [14, 14, 6] | 0,6700–0,6775 | 1,37 ✗ | 18,82 ✗ | 10,10 ✗ | 6,88 ✗ | 9,34 ✗ | 0,00 % | 2,5 / 1,7 / 11,7 / 14,2 |
| [14, 14, 5] | 0,6800–0,6825 | 1,37 ✗ | 26,73 ✗ | 12,63 ✗ | 10,71 ✓ | 9,34 ✗ | 0,00 % | 11,7 / 3,3 / 43,3 / 29,2 |
| [14, 13, 5] | 0,6850–0,7200 | 1,37 ✗ | 28,45 ✗ | 12,91 ✗ | 11,21 ✓ | 9,34 ✗ | 0,00 % | 11,7 / 5,0 / 45,0 / 30,0 |
| [13, 13, 5] | 0,7225–0,7400 | 1,37 ✗ | 30,21 ✗ | 13,16 ✗ | 11,73 ✓ | 9,34 ✗ | 0,00 % | 12,5 / 4,2 / 47,5 / 31,7 |
| [13, 12, 5] | 0,7425–0,7800 | 1,37 ✗ | 34,81 ✗ | 13,67 ✗ | 13,09 ✓ | 9,34 ✗ | 0,00 % | 16,7 / 5,8 / 50,0 / 35,0 |
| [12, 12, 5] | 0,7825–0,8075 | 1,37 ✗ | 40,76 ✓ | 14,20 ✗ | 14,95 ✓ | 9,34 ✗ | 0,00 % | 19,2 / 5,8 / 52,5 / 38,3 |
| [12, 11, 5] **(elegida)** | 0,8100–0,8475 | 1,37 ✗ | 52,83 ✓ | 15,05 ✗ | 17,76 ✓ | 9,34 ✗ | 0,00 % | 20,8 / 8,3 / 60,0 / 50,0 |
| [12, 11, 4] | 0,8500–0,8500 | 1,37 ✗ | 84,86 ✗ | 21,55 ✗ | 26,00 ✓ | 9,34 ✗ | 0,15 % | 45,8 / 24,2 / 86,7 / 65,0 |
| [11, 11, 4] | 0,8525–0,8900 | 1,37 ✗ | 135,53 ✗ | 22,97 ✗ | 33,84 ✗ | 9,33 ✗ | 0,23 % | 55,8 / 22,5 / 89,2 / 73,3 |
| [11, 10, 4] | 0,8925–0,9350 | 1,37 ✗ | 253,92 ✗ | 25,43 ✗ | 44,88 ✗ | 9,33 ✗ | 0,23 % | 68,3 / 28,3 / 95,8 / 87,5 |
| [10, 10, 4] | 0,9375–0,9875 | 1,37 ✗ | 541,66 ✗ | 26,82 ✗ | 57,84 ✗ | 9,35 ✗ | 1,92 % | 83,3 / 31,7 / 99,2 / — |
| [10, 9, 4] | 0,9900–0,9900 | 1,38 ✗ | 998,20 ✗ | 29,72 ✗ | 62,53 ✗ | 9,37 ✗ | 8,61 % | 87,5 / 37,5 / 100,0 / — |

Los médicos no mueven el pretriaje (1,37 en todas las filas sin censurados). Con la
enfermería de antes, ninguna plantilla pasa los objetivos de ajuste: hacía falta mover
primero la enfermería.

### Ajuste de los médicos (enfermería [3, 2, 1])

`uv run edsim calibracion sensibilidad --mando medicos` con el centro calibrado (15 min 20
s, en paralelo): la plantilla de médicos del centro no cuenta, porque cada fila la
sustituye, así que reproduce esta tabla.

| Plantilla | u | Pretriaje | A 2–5 | A nivel 3 | % sobre Manchester (A) | % pretriaje > 5 | Censurados (máx.) | Días fuera de Manchester (C), niveles 2 / 3 / 4 / 5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [18, 17, 7] | 0,5500–0,5500 | 10,65 ✓ | 19,61 ✗ | 17,52 ✗ | 9,66 ✗ | 39,98 ✓ | 0,00 % | 0,0 / 0,0 / 2,5 / 3,3 |
| [17, 17, 7] | 0,5525–0,5550 | 10,65 ✓ | 19,64 ✗ | 17,53 ✗ | 9,66 ✗ | 39,98 ✓ | 0,00 % | 0,0 / 0,0 / 2,5 / 3,3 |
| [17, 16, 7] | 0,5575–0,5650 | 10,65 ✓ | 19,73 ✗ | 17,54 ✗ | 9,69 ✗ | 39,98 ✓ | 0,00 % | 0,0 / 0,0 / 2,5 / 4,2 |
| [17, 16, 6] | 0,5675–0,5850 | 10,65 ✓ | 23,05 ✗ | 18,44 ✗ | 11,10 ✓ | 39,98 ✓ | 0,00 % | 0,8 / 0,0 / 7,5 / 9,2 |
| [16, 16, 6] | 0,5875–0,5925 | 10,65 ✓ | 23,13 ✗ | 18,47 ✗ | 11,13 ✓ | 39,98 ✓ | 0,00 % | 0,8 / 0,0 / 7,5 / 9,2 |
| [16, 15, 6] | 0,5950–0,6225 | 10,65 ✓ | 23,34 ✗ | 18,49 ✗ | 11,19 ✓ | 39,98 ✓ | 0,00 % | 0,8 / 0,0 / 10,0 / 10,0 |
| [15, 15, 6] (cumplidor) | 0,6250–0,6350 | 10,65 ✓ | 23,54 ✗ | 18,57 ✗ | 11,30 ✓ | 39,98 ✓ | 0,00 % | 0,8 / 0,0 / 10,0 / 10,0 |
| [15, 14, 6] | 0,6375–0,6675 | 10,65 ✓ | 23,95 ✗ | 18,63 ✗ | 11,36 ✓ | 39,98 ✓ | 0,00 % | 1,7 / 0,0 / 10,8 / 10,0 |
| [14, 14, 6] | 0,6700–0,6775 | 10,65 ✓ | 24,46 ✗ | 18,77 ✗ | 11,47 ✓ | 39,98 ✓ | 0,00 % | 0,8 / 0,0 / 10,8 / 10,0 |
| [14, 14, 5] | 0,6800–0,6825 | 10,65 ✓ | 32,62 ✗ | 20,97 ✗ | 15,04 ✓ | 39,98 ✓ | 0,00 % | 10,0 / 3,3 / 36,7 / 27,5 |
| [14, 13, 5] | 0,6850–0,7200 | 10,65 ✓ | 33,70 ✗ | 21,17 ✗ | 15,34 ✓ | 39,98 ✓ | 0,00 % | 13,3 / 2,5 / 37,5 / 26,7 |
| [13, 13, 5] | 0,7225–0,7400 | 10,65 ✓ | 35,04 ✓ | 21,46 ✗ | 15,66 ✓ | 39,98 ✓ | 0,00 % | 11,7 / 2,5 / 40,0 / 29,2 |
| [13, 12, 5] | 0,7425–0,7800 | 10,65 ✓ | 38,65 ✓ | 21,85 ✗ | 16,64 ✓ | 39,98 ✓ | 0,00 % | 16,7 / 3,3 / 40,8 / 33,3 |
| [12, 12, 5] | 0,7825–0,8075 | 10,65 ✓ | 43,79 ✓ | 22,25 ✗ | 18,08 ✓ | 39,98 ✓ | 0,00 % | 16,7 / 2,5 / 45,0 / 35,8 |
| [12, 11, 5] **(elegida)** | 0,8100–0,8475 | 10,65 ✓ | 54,51 ✓ | 22,91 ✗ | 21,08 ✓ | 39,98 ✓ | 0,00 % | 17,5 / 2,5 / 52,5 / 43,3 |
| [12, 11, 4] | 0,8500–0,8500 | 10,64 ✓ | 88,44 ✗ | 29,22 ✗ | 29,16 ✓ | 39,96 ✓ | 0,20 % | 46,7 / 22,5 / 86,7 / 63,3 |
| [11, 11, 4] | 0,8525–0,8900 | 10,64 ✓ | 136,82 ✗ | 30,35 ✗ | 37,04 ✗ | 39,96 ✓ | 0,23 % | 54,2 / 25,0 / 88,3 / 73,3 |
| [11, 10, 4] | 0,8925–0,9350 | 10,64 ✓ | 253,07 ✗ | 32,45 ✗ | 47,67 ✗ | 39,96 ✓ | 0,23 % | 65,0 / 25,0 / 94,2 / 86,7 |
| [10, 10, 4] | 0,9375–0,9875 | 10,65 ✓ | 534,32 ✗ | 33,85 ✗ | 60,70 ✗ | 39,98 ✓ | 1,78 % | 83,3 / 27,5 / 99,2 / — |
| [10, 9, 4] | 0,9900–0,9900 | 10,77 ✓ | 994,18 ✗ | 36,85 ✗ | 65,24 ✗ | 39,94 ✓ | 8,07 % | 86,7 / 30,8 / 100,0 / — |

Pasan el reloj A de los niveles 2 a 5 las plantillas de [13, 13, 5] a [12, 11, 5]; la
elegida es la más cercana a 52,5 (54,5, a 2,0). Con un médico menos de noche
([12, 11, 4]) el reloj A salta a 88 min: la noche, con 4 médicos y una carga de 3,4
(más en enero), se acerca a la saturación.

### El nivel 3, de ajuste a comprobación

Ninguna plantilla de la regla lleva el reloj A del nivel 3 por encima de 22,9 min, y los
dos objetivos del reloj A no se pueden cumplir a la vez: cuando los niveles 2 a 5 suben
hasta su horquilla, el nivel 3 sigue en 22–23 min. Es una discrepancia estructural: con
prioridad estricta en un solo grupo de médicos, el nivel 3 casi no espera box ni médico
(reloj C de 4,4 min en el centro calibrado) y las esperas recaen en los niveles 4 y 5.
En los hospitales reales, los niveles 4 y 5 suelen tener circuito propio (consultas o vía
rápida) y el nivel 3 compite con el 2. Por eso `tiempo_medico_nivel_3` pasó a
comprobación el 6 de noviembre de 2026, después de medir la sensibilidad (regla 5) y no
antes, con la nota en `config/objetivos.toml`. Una comprobación no decide el ajuste:
los médicos se eligen solo con los niveles 2 a 5. Calibrar el nivel 3 pide circuitos
separados para los niveles 4 y 5 (ver «Para versiones posteriores» de la especificación).

### Ajuste (2026) y comprobación (2027) del centro calibrado

`uv run edsim calibracion evaluar` y `uv run edsim calibracion evaluar --semilla 2027`
(1 min 50 s cada una, en paralelo; 48 s sola).

| Objetivo | Uso | Horquilla | ajuste-2026: media [IC 95 %], días fuera | comprobacion-2027: media [IC 95 %], días fuera |
| --- | --- | --- | --- | --- |
| pretriaje_medio | ajuste | 6–15 | 10,65 [8,92; 12,37], 39,2 % ✓ | 11,99 [9,71; 14,26], 43,3 % ✓ |
| tiempo_medico_niveles_2_5 | ajuste | 35–70 | 54,51 [46,95; 62,07], 69,2 % ✓ | 49,91 [41,91; 57,92], 63,3 % ✓ |
| tiempo_medico_nivel_3 | comprobacion | 45–75 | 22,91 [20,69; 25,13], 97,5 % ✗ | 24,21 [21,05; 27,37], 93,3 % ✗ |
| porcentaje_sobre_manchester | comprobacion | 10–30 | 21,08 [18,52; 23,65], 40,0 % ✓ | 19,97 [17,25; 22,70], 28,3 % ✓ |
| porcentaje_pretriaje_mas_5 | comprobacion | 30–60 | 39,98 [38,03; 41,92], 30,8 % ✓ | 39,36 [36,81; 41,91], 24,2 % ✓ |

Con la semilla de comprobación, los dos objetivos de ajuste siguen dentro y la
comprobación del porcentaje sobre Manchester y del pretriaje de más de 5 minutos también;
solo falla el nivel 3, por la discrepancia de arriba. Sin censurados en ninguna réplica.

**Porcentaje sobre Manchester (reloj A) por nivel.** El nivel 2 tiene un máximo de 10 min
y el pretriaje y el triaje ya suman más: queda por encima en más de la mitad de sus
pacientes. La contribución es la parte de la cifra global que aporta cada nivel.

| Nivel | ajuste-2026: % del nivel / contribución | comprobacion-2027: % del nivel / contribución |
| --- | --- | --- |
| 2 | 57,4 % / 7,46 puntos | 56,7 % / 7,53 puntos |
| 3 | 8,3 % / 2,82 puntos | 9,2 % / 3,15 puntos |
| 4 | 20,4 % / 10,47 puntos | 17,5 % / 8,97 puntos |
| 5 | 23,9 % / 0,33 puntos | 24,4 % / 0,33 puntos |

### Centro cumplidor

`uv run edsim calibracion evaluar --centro config/centro_cumplidor.toml` (y con
`--semilla 2027`). No es un centro calibrado: el reloj A de los niveles 2 a 5 queda por
debajo de la horquilla, como se espera de un centro que cumple Manchester.

| Objetivo | Uso | Horquilla | cumplidor-2026: media [IC 95 %], días fuera | cumplidor-2027: media [IC 95 %], días fuera |
| --- | --- | --- | --- | --- |
| pretriaje_medio | ajuste | 6–15 | 10,65 [8,92; 12,37], 39,2 % ✓ | 11,99 [9,71; 14,26], 43,3 % ✓ |
| tiempo_medico_niveles_2_5 | ajuste | 35–70 | 23,54 [20,71; 26,37], 88,3 % ✗ | 24,32 [21,39; 27,24], 89,2 % ✗ |
| tiempo_medico_nivel_3 | comprobacion | 45–75 | 18,57 [16,60; 20,54], 99,2 % ✗ | 19,77 [17,21; 22,33], 95,8 % ✗ |
| porcentaje_sobre_manchester | comprobacion | 10–30 | 11,30 [9,57; 13,03], 55,0 % ✓ | 11,31 [10,02; 12,59], 58,3 % ✓ |
| porcentaje_pretriaje_mas_5 | comprobacion | 30–60 | 39,98 [38,03; 41,92], 30,8 % ✓ | 39,36 [36,81; 41,91], 24,2 % ✓ |

| Nivel | cumplidor-2026: % del nivel / contribución | cumplidor-2027: % del nivel / contribución |
| --- | --- | --- |
| 2 | 49,8 % / 6,48 puntos | 48,8 % / 6,49 puntos |
| 3 | 6,0 % / 2,06 puntos | 6,5 % / 2,25 puntos |
| 4 | 5,2 % / 2,69 puntos | 4,9 % / 2,50 puntos |
| 5 | 5,2 % / 0,08 puntos | 4,9 % / 0,07 puntos |

### Fila reproducible

`uv run edsim calibracion evaluar --replicas 3 --dias 5 --calentamiento 1` con el centro
calibrado (8,6 s; código 1, porque con 3 réplicas el IC de los niveles 2 a 5 es más ancho
que la horquilla). Medias: pretriaje 10,94; reloj A de los niveles 2 a 5, 94,56; nivel
3, 24,58; sobre Manchester, 29,98 %; pretriaje de más de 5 minutos, 41,78 %; sin
censurados. El test slow `test_reproduce_la_fila_corta_del_registro` la comprueba.

### Observaciones

- **El pretriaje de noche.** En el centro calibrado (una ejecución, semilla 2026), el
  pretriaje de la noche es de 18,6 min de media, con p90 de 58,9, con una sola enfermera.
  La regla reparte con la carga media del turno (0,605), pero las primeras horas de la
  noche tienen casi la carga de la tarde: a las 22 h llegan 12,6 pacientes por hora (una
  carga de enfermería de 1,21, más de lo que una enfermera puede absorber) y a las 23 h,
  10,2 (0,98), frente a 16,5 de media de la tarde. La cola se forma entre las 22 y las
  24 h y no se vacía hasta las 3 h: los llegados a las 0 h esperan 35,3 min de media
  (p90 79,8), y los de las 4 h, 4,5. Una regla por horas, o un turno de noche partido,
  lo evitaría; queda fuera de esta tarea, que no amplía la regla.
- **Las esperas de los niveles 4 y 5.** Con prioridad estricta, cargan con las colas:
  reloj A de 57,7 y 107,3 min en el centro calibrado, y cumplimiento Manchester con el
  reloj C del 86 % y el 83 %, con 6 días fuera de 12 en cada uno. Es el centro «realista»
  de la decisión 41, que incumple a veces.
- **Sin colas que crezcan de un día a otro.** A las 8:00, la cola de box solo tiene
  pacientes el primer día después del calentamiento (14); el resto de días está vacía.

### El reloj A según el horizonte (tarea 4.7, revisión del PR #49)

El reloj A de los niveles 2 a 5 del centro calibrado parecía crecer con el horizonte: 54,5
min en la calibración (10 réplicas, días 2 a 13), 57,1 en la sección 9 del notebook 04 (5
réplicas), 73,5 en una ejecución de 28 días de la sección 12 y, en el nivel 5, de 107 min
a 229 en la ejecución de 91 días. Se midió si era sesgo de inicialización (cada réplica
empieza vacía) o acumulación en días malos, sin tocar la calibración ni `config/`. Todo con
las funciones del paquete (`clinical_run`, `replica_values`, `step_curves` y
`summarize`); el script está en la descripción del PR #49.

**(a) Ejecución principal del notebook 04: 91 días, semilla 2026, centro calibrado.** Por semana de calendario (lunes a domingo; la primera, sin los 2 días de calentamiento). Medias por paciente llegado en la semana; censo y cola de box a las 8:00, media de los días de la semana (y máximo de la cola).

| Semana | Días | Reloj A, niveles 2 a 5 | Reloj A, nivel 4 | Reloj A, nivel 5 (pacientes) | Espera de box, nivel 5 | Censo a las 8:00 | Cola de box a las 8:00 (máx.) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 7/1–11/1 | 41,7 | 59,4 | 71,7 (22) | 31,7 | 20,6 | 2,8 (14) |
| 2 | 12/1–18/1 | 38,6 | 56,5 | 131,8 (32) | 49,5 | 11,0 | 0,0 (0) |
| 3 | 19/1–25/1 | 131,8 | 183,3 | 984,5 (46) | 1060,3 | 43,1 | 14,3 (51) |
| 4 | 26/1–1/2 | 62,8 | 86,8 | 284,9 (33) | 227,2 | 25,0 | 4,1 (29) |
| 5 | 2/2–8/2 | 34,7 | 44,0 | 83,3 (35) | 15,2 | 13,0 | 0,0 (0) |
| 6 | 9/2–15/2 | 36,4 | 50,9 | 130,6 (32) | 45,0 | 15,0 | 0,0 (0) |
| 7 | 16/2–22/2 | 50,5 | 69,1 | 57,0 (31) | 23,1 | 22,1 | 3,9 (27) |
| 8 | 23/2–1/3 | 37,3 | 52,6 | 73,7 (29) | 14,6 | 16,1 | 0,4 (3) |
| 9 | 2/3–8/3 | 32,5 | 42,4 | 70,0 (31) | 14,2 | 11,6 | 0,0 (0) |
| 10 | 9/3–15/3 | 28,7 | 36,8 | 95,4 (34) | 38,7 | 11,4 | 0,0 (0) |
| 11 | 16/3–22/3 | 46,7 | 68,5 | 189,6 (35) | 123,8 | 19,1 | 1,4 (10) |
| 12 | 23/3–29/3 | 47,2 | 61,4 | 306,2 (35) | 291,5 | 17,1 | 3,7 (26) |
| 13 | 30/3–5/4 | 35,7 | 49,0 | 84,0 (25) | 51,5 | 12,3 | 0,0 (0) |
| Total | 7/1–5/4 | 49,3 | | 229,4 | | | |

**(b) 5 semillas × 56 días, centro calibrado, `config/llegadas.toml`.** Semillas: los hijos 0 a 4 de `child_streams(2026, 5)`, las 5 primeras réplicas de la calibración; 2 días de calentamiento y uno de vaciado; sin censurados. Media entre semillas e IC al 95 % (t₄ = 2,776).

| Bloque (días medidos) | Fechas | Reloj A, niveles 2 a 5 | Reloj A, nivel 5 | Por semilla (niveles 2 a 5) |
| --- | --- | --- | --- | --- |
| 2–13 | 7/1–18/1 | 57,1 [46,2; 68,0] | 236,4 [189,9; 282,9] | 65,4 / 49,4 / 58,4 / 46,9 / 65,7 |
| 14–27 | 19/1–1/2 | 61,8 [33,9; 89,7] | 265,1 [45,9; 484,3] | 67,9 / 53,5 / 97,3 / 52,3 / 38,1 |
| 28–41 | 2/2–15/2 | 34,3 [30,2; 38,3] | 87,7 [69,9; 105,5] | 34,5 / 33,5 / 35,4 / 38,5 / 29,5 |
| 42–55 | 16/2–1/3 | 43,4 [26,1; 60,8] | 189,3 [18,4; 360,1] | 40,6 / 31,9 / 38,4 / 67,7 / 38,6 |

**(c) Lo mismo con el factor mensual neutro** (todos los meses a 1, con `dataclasses.replace` en memoria; la media de los doce factores reales es 1,0008). Semillas: los hijos 0 a 4 de `child_streams(2026, 5)`, las 5 primeras réplicas de la calibración; 2 días de calentamiento y uno de vaciado; sin censurados. Media entre semillas e IC al 95 % (t₄ = 2,776).

| Bloque (días medidos) | Fechas | Reloj A, niveles 2 a 5 | Reloj A, nivel 5 | Por semilla (niveles 2 a 5) |
| --- | --- | --- | --- | --- |
| 2–13 | 7/1–18/1 | 28,3 [25,6; 30,9] | 56,7 [41,8; 71,5] | 26,6 / 31,2 / 28,2 / 29,3 / 25,9 |
| 14–27 | 19/1–1/2 | 33,9 [23,1; 44,7] | 129,2 [67,7; 190,8] | 35,3 / 45,0 / 36,6 / 31,3 / 21,1 |
| 28–41 | 2/2–15/2 | 28,4 [21,7; 35,1] | 75,1 [36,7; 113,6] | 21,8 / 28,0 / 27,3 / 36,9 / 27,8 |
| 42–55 | 16/2–1/3 | 26,8 [22,2; 31,4] | 58,8 [35,4; 82,2] | 26,3 / 21,8 / 31,4 / 25,2 / 29,4 |

**Conclusión.** No es sesgo de inicialización: con el factor mensual neutro, los cuatro
bloques de 14 días quedan entre 26,8 y 33,9 min y el primero (28,3) no queda por debajo de
los demás, así que los 2 días de calentamiento bastan; la primera semana medida (días 2 a
6) da 25,2 min frente a 26,3–35,1 de las siguientes, dentro del ruido. Lo que mueve las
cifras es el mes (con los factores reales, enero da 57,1 y 61,8 min y febrero, 34,3 y 43,4)
y la acumulación en días malos: en la semilla 2026, del 19 al 22 de enero llegan cuatro
días seguidos más pacientes de lo esperado (efecto diario de 1,03 a 1,18; 390, 369, 404 y
363 llegadas frente a unas 320), la cola de box de la noche pasa al día siguiente (19, 51,
15 y 15 pacientes a las 8:00) y no se vacía hasta el viernes 23. Esa semana sola da 131,8
min de reloj A a los niveles 2 a 5 y 985 al nivel 5, el 47 % de los minutos de espera del
nivel 5 en los 89 días (sin ella, 137 min).

**Resuelto en la tarea 4.6c.** La ventana de la calibración pasa a cubrir el año: una
réplica por mes, desde el primer lunes de cada mes. Con ella, el centro de la 4.6b da 27,75
min de reloj A (fuera de 35–70 por abajo) y la plantilla se recalibra: médicos [12, 11, 4]
(ver «Tarea 4.6c»).

## Tarea 4.6c: recalibración con la ventana anual (6 de noviembre de 2026)

Rama `feat/h4-recalibracion-anual`. Mismo modelo clínico, mismos `config/llegadas.toml`,
`config/perfiles.toml` y `config/objetivos.toml`, boxes, duraciones y
`espera_resultados_fuera` que en la 4.6b. Solo cambian la ventana de la calibración, la
regla del cumplidor (días enteros) y la de elección (veto de la semilla de comprobación).

### Cambios

| Parámetro | Antes (4.6b) | Después (4.6c) | KPI | Motivo |
| --- | --- | --- | --- | --- |
| Ventana de la calibración | 10 réplicas, todas desde el 5/1/2026 (primera quincena de enero) | 12 réplicas, la m desde el primer lunes del mes m+1 | Reloj A de los niveles 2 a 5 del centro de la 4.6b: 54,51 → 27,75 min | Los objetivos del SAS son medias anuales; enero es el mes de más carga (factor 1,10) |
| `recursos.enfermeria_triaje` | [3, 2, 1] | [3, 2, 1] (u de 0,795 a 0,8325) | Pretriaje medio: 6,78 min [5,49; 8,06] (horquilla 6–15; SAS 12,4) | La regla elige [2, 2, 1] (13,21), pero la semilla 2027 la veta (15,16) y se toma la siguiente |
| `recursos.medicos` | [12, 11, 5] | [12, 11, 4] (u de 0,85) | Reloj A, niveles 2 a 5: 27,75 → 42,10 min [28,02; 56,18] (horquilla 35–70) | La única plantilla de la regla que pasa con la ventana anual |
| Centro cumplidor (`config/centro_cumplidor.toml`) | médicos [15, 15, 6] | médicos [14, 14, 6] (u de 0,67 a 0,6775) | Días fuera de Manchester con el reloj C, niveles 2 a 5: 1/144, 0/144, 2/144, 6/142 | El u más alto con como mucho un 10 % de días fuera, con los días sumados |
| Regla del cumplidor | media de los % de días fuera por réplica ≤ 10 % | días fuera sumados ≤ 10 % de los días medidos sumados, con enteros | — | Exacta, sin decimales; ver «Método» |
| Regla de elección (decisión 41) | la semilla 2027 solo comprueba | la semilla 2027 puede vetar, no elegir; después de un veto, la comprobación independiente es 2028 | — | Ver «El veto de la semilla 2027» |

### Método

- **Ventana anual.** 12 réplicas: la m (m = 0…11) empieza a las 00:00 del primer lunes
  del mes m+1 del año de `fecha_inicio` (en 2026: 5/1, 2/2, 2/3, 6/4, 4/5, 1/6, 6/7, 3/8,
  7/9, 5/10, 2/11 y 7/12) y usa el hijo m de `child_streams(semilla, 12)`. Cada réplica
  tiene el factor mensual, los días de la semana y el contexto clínico (mes y estación)
  de su mes. Igual que antes: 14 días con 2 de calentamiento, un día de vaciado, la
  ventana [2, 14) y números aleatorios comunes entre candidatos. La réplica de enero es,
  bit a bit, la réplica 0 de la 4.6b (test slow `test_la_replica_de_enero_reproduce_la_replica_0_de_la_ventana_de_la_4_6b`).
  Las cargas de la regla son las del día medio y no dependen de la fecha: las plantillas
  candidatas no cambian.
- **Regla 4.** Igual, con t₁₁ = 2,201. El IC entre réplicas incluye la variación entre
  meses, así que es conservador: la regla pide que la media del año caiga en la horquilla
  y que los meses no se separen más que su anchura.
- **Media por paciente del año.** `edsim calibracion evaluar` informa también de la media
  de todos los pacientes de las 12 réplicas, que pondera cada mes por sus pacientes. No
  decide: la regla 4 usa la media entre réplicas. La diferencia es pequeña (reloj A de los
  niveles 2 a 5 del centro elegido: 42,10 entre réplicas y 42,99 por paciente).
- **Cumplidor con días enteros.** Pasa si en cada nivel de 2 a 5 los días fuera de
  Manchester con el reloj C, sumados en las réplicas, no superan el 10 % de los días con
  pacientes de ese nivel, también sumados: fuera × 10 ≤ medidos, con enteros. Con 12
  réplicas de 12 días medidos (144), pasan 14 días fuera y no 15. **Cambia la definición**
  cuando las réplicas tienen distinto número de días con pacientes de un nivel (el nivel 5,
  con 1,4 % de los pacientes, tiene días sin ninguno): antes, una réplica con 6 días
  medidos pesaba lo mismo que una con 12; ahora pesa cada día. Con `--ventana inicio` y la
  semilla 2026, la regla con enteros sigue eligiendo [15, 15, 6], como en la 4.6b: 12 de
  120 días fuera en los niveles 4 y 5, justo el 10 %, pasa; [15, 14, 6] tiene 13 de 120 en
  el nivel 4 y no pasa (`uv run edsim calibracion sensibilidad --mando medicos --ventana
  inicio`, 11 min 36 s).
- **Veto de la semilla de comprobación (decisión 41, revisada).** La semilla de
  comprobación puede vetar, no elegir: si la plantilla elegida con 2026 falla un objetivo
  de ajuste con 2027 (regla 4), se descarta y se toma la siguiente candidata de la regla
  de elección (la siguiente más cercana a la referencia o al centro de la horquilla) que
  pase los objetivos de ajuste con 2026 y con 2027. Si ninguna pasa con las dos, no se
  elige. Como 2027 ha intervenido en la elección, la comprobación independiente pasa a la
  semilla 2028. En el paquete, `choose_staffing(filas, mando, check=…)`; en la CLI,
  `calibracion sensibilidad --comprobacion 2027`, que evalúa con 2027, con la misma ventana
  y el resto de opciones, solo las candidatas que hagan falta, en el orden de la elección
  (revisión del PR #50).
- **Orden.** Como en la 4.6b: la enfermería contra el pretriaje, con los médicos del
  centro; con ella fija, los médicos contra el reloj A.

### El centro de la 4.6b con la ventana anual

`uv run edsim calibracion evaluar --centro tests/data/centro_4_6b.toml` (36 s). Con la
carga del año, el reloj A de los niveles 2 a 5 queda por debajo de la horquilla.

| Objetivo | Uso | Horquilla | Media [IC 95 %] | Por paciente |
| --- | --- | --- | --- | --- |
| pretriaje_medio | ajuste | 6–15 | 6,78 [5,49; 8,06] ✓ | 6,87 |
| tiempo_medico_niveles_2_5 | ajuste | 35–70 | 27,75 [19,12; 36,38] ✗ | 28,31 |
| tiempo_medico_nivel_3 | comprobacion | 45–75 | 15,65 [13,87; 17,44] ✗ | 15,80 |
| porcentaje_sobre_manchester | comprobacion | 10–30 | 11,16 [8,05; 14,28] ✓ | 11,37 |
| porcentaje_pretriaje_mas_5 | comprobacion | 30–60 | 31,39 [28,47; 34,30] ✓ | 31,58 |

Por mes, el reloj A de los niveles 2 a 5 va de 65,39 en enero a 16,58 en agosto (ver
«Enero con una plantilla anual»). Sin censurados.

### Sensibilidad de la enfermería (médicos [12, 11, 5])

`uv run edsim calibracion sensibilidad --mando enfermeria_triaje` (3 min 13 s) y lo mismo
con `--semilla 2027` (2 min 14 s). La enfermería no cambia el reloj de los médicos de forma
apreciable, ni los médicos el pretriaje: con los médicos de la 4.6b o con [12, 11, 4], el
pretriaje es el mismo salvo por los pacientes censurados, que no se miden (13,21 y 13,20
con [2, 2, 1]). La tabla de 2027 se ejecutó con el `config/` final (médicos [12, 11, 4]).

| Plantilla | u | 2026: pretriaje medio [IC 95 %] | 2026: % pretriaje > 5 min | 2027: pretriaje medio [IC 95 %] | 2027: % pretriaje > 5 min |
| --- | --- | --- | --- | --- | --- |
| [4, 3, 2] | 0,5500–0,5550 | 0,60 [0,52; 0,67] ✗ | 3,72 | 0,60 [0,52; 0,68] ✗ | 3,62 |
| [3, 3, 2] | 0,5575–0,6050 | 0,95 [0,82; 1,08] ✗ | 6,22 | 1,03 [0,85; 1,21] ✗ | 6,81 |
| [3, 3, 1] | 0,6075–0,7925 | 3,54 [2,85; 4,23] ✗ | 16,23 | 3,92 [3,30; 4,54] ✗ | 16,57 |
| [3, 2, 1] | 0,7950–0,8325 | 6,78 [5,49; 8,06] ✓ | 31,39 | 7,86 [6,31; 9,41] ✓ | 32,91 |
| [2, 2, 1] | 0,8350–0,9900 | 13,21 [8,98; 17,44] ✓ | 51,44 | 15,16 [10,61; 19,71] ✗ | 53,02 |

Sin censurados en ninguna. Con 2026 pasan [3, 2, 1] y [2, 2, 1], y la regla elige
[2, 2, 1], la más cercana a la referencia (12,4). Con 2027 [2, 2, 1] no pasa: el veto la
descarta y queda [3, 2, 1] (ver «El veto de la semilla 2027»). La tabla de 2027 es la
sensibilidad entera con `--semilla 2027`, que aplica la regla a esa semilla; la elección
con el veto la da `uv run edsim calibracion sensibilidad --mando enfermeria_triaje
--comprobacion 2027`, que con 2027 evalúa solo [2, 2, 1] (vetada) y [3, 2, 1] (elegida).

### Sensibilidad de los médicos (enfermería [3, 2, 1])

`uv run edsim calibracion sensibilidad --mando medicos` (15 min 37 s). Días fuera de
Manchester con el reloj C / días medidos, sumados en las 12 réplicas.

| Plantilla | u | Reloj A, niveles 2 a 5 [IC 95 %] | Nivel 3 | % sobre Manchester | Censurados (máx.) | Días fuera (C), niveles 2 / 3 / 4 / 5 |
| --- | --- | --- | --- | --- | --- | --- |
| [18, 17, 7] | 0,5500 | 13,65 [11,95; 15,36] ✗ | 12,90 | 5,79 | 0,00 % | 0/144 / 0/144 / 1/144 / 1/142 |
| [17, 17, 7] | 0,5525–0,5550 | 13,67 [11,95; 15,38] ✗ | 12,91 | 5,79 | 0,00 % | 0/144 / 0/144 / 1/144 / 1/142 |
| [17, 16, 7] | 0,5575–0,5650 | 13,68 [11,95; 15,40] ✗ | 12,91 | 5,80 | 0,00 % | 0/144 / 0/144 / 1/144 / 1/142 |
| [17, 16, 6] | 0,5675–0,5850 | 15,21 [13,27; 17,14] ✗ | 13,38 | 6,48 | 0,00 % | 1/144 / 0/144 / 2/144 / 5/142 |
| [16, 16, 6] | 0,5875–0,5925 | 15,24 [13,28; 17,20] ✗ | 13,40 | 6,49 | 0,00 % | 1/144 / 0/144 / 2/144 / 5/142 |
| [16, 15, 6] | 0,5950–0,6225 | 15,27 [13,28; 17,25] ✗ | 13,41 | 6,50 | 0,00 % | 1/144 / 0/144 / 2/144 / 5/142 |
| [15, 15, 6] | 0,6250–0,6350 | 15,35 [13,32; 17,37] ✗ | 13,44 | 6,53 | 0,00 % | 1/144 / 0/144 / 2/144 / 5/142 |
| [15, 14, 6] | 0,6375–0,6675 | 15,43 [13,38; 17,48] ✗ | 13,47 | 6,53 | 0,00 % | 1/144 / 0/144 / 2/144 / 6/142 |
| [14, 14, 6] | 0,6700–0,6775 | 15,65 [13,48; 17,81] ✗ | 13,53 | 6,59 | 0,00 % | 1/144 / 0/144 / 2/144 / 6/142 |
| [14, 14, 5] | 0,6800–0,6825 | 20,41 [17,32; 23,49] ✗ | 14,70 | 9,07 | 0,00 % | 4/144 / 0/144 / 9/144 / 22/142 |
| [14, 13, 5] | 0,6850–0,7200 | 20,66 [17,50; 23,82] ✗ | 14,78 | 9,18 | 0,00 % | 4/144 / 0/144 / 10/144 / 22/142 |
| [13, 13, 5] | 0,7225–0,7400 | 21,16 [17,76; 24,55] ✗ | 14,92 | 9,27 | 0,00 % | 3/144 / 0/144 / 11/144 / 22/142 |
| [13, 12, 5] | 0,7425–0,7800 | 22,09 [18,25; 25,92] ✗ | 15,07 | 9,60 | 0,00 % | 5/144 / 0/144 / 15/144 / 28/142 |
| [12, 12, 5] | 0,7825–0,8075 | 23,89 [18,60; 29,19] ✗ | 15,31 | 10,16 | 0,00 % | 6/144 / 0/144 / 20/144 / 30/142 |
| [12, 11, 5] | 0,8100–0,8475 | 27,75 [19,12; 36,38] ✗ | 15,65 | 11,16 | 0,00 % | 6/144 / 0/144 / 28/144 / 32/142 |
| **[12, 11, 4]** | 0,8500 | 42,10 [28,02; 56,18] ✓ | 18,76 | 16,13 | 0,20 % | 28/144 / 7/144 / 88/144 / 54/142 |
| [11, 11, 4] | 0,8525–0,8900 | 50,23 [27,79; 72,66] ✗ | 19,35 | 18,03 | 0,23 % | 37/144 / 6/144 / 89/144 / 55/142 |
| [11, 10, 4] | 0,8925–0,9350 | 76,47 [24,53; 128,42] ✗ | 20,44 | 22,52 | 0,23 % | 55/144 / 11/144 / 95/144 / 67/142 |
| [10, 10, 4] | 0,9375–0,9875 | 129,66 [7,41; 251,90] ✗ | 21,56 | 27,90 | 1,12 % | 53/144 / 11/144 / 101/144 / 81/137 |
| [10, 9, 4] | 0,9900 | 240,52 [11,66; 469,37] ✗ | 23,31 | 34,49 | 7,31 % | 75/144 / 15/144 / 113/143 / 74/118 |

Solo pasa [12, 11, 4], con un único punto de la rejilla de u (0,85). [11, 11, 4] tiene la
media dentro (50,23), pero su IC (44,87 de ancho) es más ancho que la horquilla (35): los
meses se separan demasiado. Con 2027, [12, 11, 4] pasa (43,29): no hay veto de médicos.
Con la enfermería [2, 2, 1] (antes del veto) la sensibilidad de los médicos elegía también
[12, 11, 4] (48,69) y el cumplidor [14, 14, 6] (16 min 17 s).

### El veto de la semilla 2027

`uv run edsim calibracion evaluar --semilla 2027` con cada enfermería (24 s cada una). Los
dos objetivos de ajuste, con médicos [12, 11, 4]:

| Enfermería | Semilla | Pretriaje medio [IC 95 %] (6–15) | Reloj A, niveles 2 a 5 [IC 95 %] (35–70) | Censurados |
| --- | --- | --- | --- | --- |
| [2, 2, 1] | 2026 | 13,20 [8,99; 17,41] ✓ | 48,69 [31,80; 65,58] ✓ | 3, en enero (0,08 %) |
| [2, 2, 1] | 2027 | **15,16 [10,61; 19,71] ✗** | 50,07 [37,45; 62,69] ✓ | 0 |
| [3, 2, 1] | 2026 | 6,78 [5,49; 8,06] ✓ | 42,10 [28,02; 56,18] ✓ | 8, en enero (0,20 %) |
| [3, 2, 1] | 2027 | 7,86 [6,31; 9,41] ✓ | 43,29 [33,11; 53,47] ✓ | 0 |

Con 2027 el pretriaje de [2, 2, 1] sale de la horquilla por la media (15,16 > 15) y por el
IC (9,10 de ancho frente a 9). Con dos enfermeras de mañana el pretriaje depende de unos
pocos días de muchas llegadas: con 2027, la quincena de noviembre da 32,58 min y la de
enero 25,23. [3, 2, 1] queda cerca del borde inferior (6,78 y 7,86) y pasa con las dos.

### Ajuste (2026), comprobación (2027) y confirmación (2028) del centro calibrado

`uv run edsim calibracion evaluar`, con `--semilla 2027` y con `--semilla 2028` (24 s cada
una).

| Objetivo | Uso | Horquilla | ajuste-2026 | comprobacion-2027 | confirmacion-2028 |
| --- | --- | --- | --- | --- | --- |
| pretriaje_medio | ajuste | 6–15 | 6,78 [5,49; 8,06] ✓ | 7,86 [6,31; 9,41] ✓ | 7,76 [6,48; 9,03] ✓ |
| tiempo_medico_niveles_2_5 | ajuste | 35–70 | 42,10 [28,02; 56,18] ✓ | 43,29 [33,11; 53,47] ✓ | 41,20 [33,57; 48,84] ✓ |
| tiempo_medico_nivel_3 | comprobacion | 45–75 | 18,76 [16,60; 20,93] ✗ | 20,13 [17,36; 22,90] ✗ | 20,60 [17,86; 23,34] ✗ |
| porcentaje_sobre_manchester | comprobacion | 10–30 | 16,13 [12,33; 19,93] ✓ | 16,79 [13,31; 20,27] ✓ | 16,64 [13,95; 19,32] ✓ |
| porcentaje_pretriaje_mas_5 | comprobacion | 30–60 | 31,38 [28,47; 34,28] ✓ | 32,91 [29,31; 36,50] ✓ | 32,36 [29,54; 35,17] ✓ |
| Censurados | | | 8, en enero (0,20 %) | 0 | 0 |

Media por paciente del año del reloj A de los niveles 2 a 5: 42,99, 43,87 y 41,57. Con las
tres semillas pasan los objetivos de ajuste y fallan solo el nivel 3, por la discrepancia
de la 4.6b.

| Nivel | % sobre Manchester: ajuste-2026, % del nivel / contribución | comprobacion-2027 |
| --- | --- | --- |
| 2 | 48,3 % / 5,86 puntos | 48,3 % / 5,92 puntos |
| 3 | 6,4 % / 2,13 puntos | 7,1 % / 2,40 puntos |
| 4 | 15,0 % / 7,89 puntos | 15,7 % / 8,22 puntos |
| 5 | 17,7 % / 0,24 puntos | 18,3 % / 0,25 puntos |

### Enero con una plantilla anual

La plantilla es la misma todo el año, y la regla 4 con la ventana anual pide que la media
del año caiga en la horquilla. Enero, el mes de más carga (factor mensual 1,10), queda cerca
de la saturación. Reloj A de los niveles 2 a 5 por mes (la quincena desde el primer lunes;
médicos [12, 11, 4] salvo la primera fila):

| Centro | Semilla | ene | feb | mar | abr | may | jun | jul | ago | sep | oct | nov | dic |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 4.6b: [3, 2, 1] + [12, 11, 5] | 2026 | 65,4 | 38,7 | 25,8 | 23,6 | 24,1 | 17,8 | 28,9 | 16,6 | 19,6 | 22,7 | 16,9 | 32,9 |
| **[3, 2, 1] + [12, 11, 4]** | 2026 | 105,2 | 58,7 | 36,9 | 37,8 | 36,6 | 28,5 | 41,2 | 24,6 | 28,4 | 34,4 | 25,0 | 47,8 |
| **[3, 2, 1] + [12, 11, 4]** | 2027 | 78,6 | 40,8 | 46,2 | 37,8 | 27,1 | 22,6 | 45,0 | 33,9 | 35,9 | 31,6 | 62,3 | 57,6 |
| **[3, 2, 1] + [12, 11, 4]** | 2028 | 60,5 | 65,2 | 35,7 | 37,5 | 39,3 | 33,9 | 32,7 | 31,7 | 39,6 | 33,8 | 29,7 | 54,9 |
| [2, 2, 1] + [12, 11, 4] | 2026 | 123,9 | 68,8 | 45,5 | 39,1 | 45,6 | 31,2 | 50,2 | 27,9 | 31,8 | 37,5 | 28,4 | 54,6 |
| [2, 2, 1] + [12, 11, 4] | 2027 | 93,7 | 44,9 | 52,9 | 41,9 | 31,0 | 29,0 | 50,1 | 37,1 | 40,8 | 35,5 | 79,0 | 65,0 |

Pretriaje medio por mes:

| Centro | Semilla | ene | feb | mar | abr | may | jun | jul | ago | sep | oct | nov | dic |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **[3, 2, 1] + [12, 11, 4]** | 2026 | 10,3 | 10,2 | 8,1 | 5,9 | 7,2 | 5,5 | 7,1 | 4,4 | 4,7 | 5,4 | 4,9 | 7,6 |
| **[3, 2, 1] + [12, 11, 4]** | 2027 | 10,0 | 9,7 | 9,5 | 8,2 | 5,0 | 4,5 | 8,2 | 6,1 | 5,2 | 5,9 | 11,6 | 10,5 |
| [2, 2, 1] + [12, 11, 4] | 2026 | 30,0 | 19,9 | 15,0 | 7,6 | 15,6 | 8,8 | 13,2 | 7,7 | 7,9 | 9,6 | 8,3 | 14,7 |
| [2, 2, 1] + [12, 11, 4] | 2027 | 25,2 | 13,5 | 15,0 | 13,1 | 9,2 | 8,5 | 12,7 | 9,9 | 14,9 | 9,5 | 32,6 | 17,8 |

- **El salto de 5 a 4 médicos de noche.** La carga de médicos de la noche es de 3,399
  (día medio). Con 5 médicos, u nominal 0,68; con 4, 0,85, y con el factor de enero
  (1,10), 0,93. Con [12, 11, 5] el reloj A anual se queda en 27,75 (fuera por abajo); con
  [12, 11, 4] sube a 42,10, y en enero a 105,2. Entre las dos no hay plantilla de la
  regla: es el único paso que lleva el año dentro de la horquilla.
- **Censurados de enero.** Con 2026, 8 pacientes de enero (0,20 % de 3924) siguen dentro
  al final del día de vaciado; ninguno en otro mes ni con 2027 o 2028. El aviso de la CLI
  salta por encima del 0,1 % en una réplica.
- **El pretriaje de noche.** Mismo método que el 18,6 de la 4.6b (llegados de 22 a 8 h
  de los niveles 2 a 5 en la ventana [2, 14) de cada réplica, con los médicos de la 4.6b,
  que no mueven el pretriaje); el 18,6 (p90 58,9) se reproduce con una ejecución de la
  semilla 2026 desde `fecha_inicio`. Con la ventana anual y semilla 2026, [3, 2, 1] da 15,6
  min por paciente (p90 44,1; enero 23,8) y [2, 2, 1], 18,4 (p90 50,0; enero 38,7). Por
  turno, mañana / tarde / noche: 1,1 / 8,1 / 15,6 con [3, 2, 1] y 10,9 / 13,5 / 18,4 con
  [2, 2, 1]. La causa del empeoramiento con [2, 2, 1] es la cola de la mañana: con dos
  enfermeras (u nominal 0,83 en el día medio) el pretriaje de los llegados sube de 1,7 min
  a las 8 h a 16,7 a las 13 h (con [3, 2, 1], 0,3 y 1,3), y la cola pasa a la tarde y a
  la noche.
- **La ejecución principal del notebook 04** (91 días desde el 5 de enero, semilla 2026)
  cae en los meses de más carga: reloj A de los niveles 2 a 5 de 82,0 min y del nivel 5 de
  627 (con [12, 11, 5], 49,3 y 229). La semana del 19 al 25 de enero, con cuatro días
  seguidos de más llegadas, da 306 y 3897 min: a las 8:00 llega a haber 129 pacientes
  clasificados esperando médico (el 23) y la cola no se vacía hasta el 30. Sin censurados
  al final, y la semana siguiente vuelve a 84 min. Es el mismo efecto que en la tarea 4.7,
  más fuerte con un médico menos de noche. Los 3897 min (unas 65 horas) del nivel 5 en esa semana no son realistas: el modelo aún no tiene abandono sin ser visto (`patient_left_wbs`, hito 5), y en un hospital real buena parte de esos pacientes se iría. Lo acotan el abandono del hito 5 y el refuerzo de invierno.
- **Refuerzo de invierno, para versiones posteriores.** Con una plantilla anual, enero
  queda cerca de la saturación: reloj A de 105 min con 2026 y 8 censurados. Un refuerzo de
  invierno (por ejemplo, el quinto médico de noche solo en los meses de más carga) es
  para versiones posteriores: pide una plantilla por mes en el motor y en la regla, y
  medir con la ventana anual que el año sigue dentro de la horquilla. Esta tarea mantiene
  la misma plantilla todo el año.

### Centro cumplidor

`uv run edsim calibracion evaluar --centro config/centro_cumplidor.toml` (y con
`--semilla 2027`). No es un centro calibrado: el reloj A de los niveles 2 a 5 queda por
debajo de la horquilla, como se espera de un centro que cumple Manchester.

| Objetivo | Uso | Horquilla | cumplidor-2026 | cumplidor-2027 |
| --- | --- | --- | --- | --- |
| pretriaje_medio | ajuste | 6–15 | 6,78 [5,49; 8,06] ✓ | 7,86 [6,31; 9,41] ✓ |
| tiempo_medico_niveles_2_5 | ajuste | 35–70 | 15,65 [13,48; 17,81] ✗ | 17,46 [14,64; 20,29] ✗ |
| tiempo_medico_nivel_3 | comprobacion | 45–75 | 13,53 [12,13; 14,93] ✗ | 14,54 [12,84; 16,24] ✗ |
| porcentaje_sobre_manchester | comprobacion | 10–30 | 6,59 [5,42; 7,75] ✗ | 7,52 [6,09; 8,95] ✗ |
| porcentaje_pretriaje_mas_5 | comprobacion | 30–60 | 31,39 [28,47; 34,30] ✓ | 32,91 [29,31; 36,50] ✓ |

Sin censurados. Días fuera de Manchester con el reloj C, niveles 2 a 5, con 2026: 1/144,
0/144, 2/144 y 6/142, todos por debajo del 10 % (14 de 144). La siguiente de la regla,
[14, 14, 5], tiene 22/142 en el nivel 5 y no pasa. Porcentaje sobre Manchester por nivel
con 2026: 41,8 / 2,2 / 1,4 / 1,5 % (el nivel 2 sigue por encima por el pretriaje y el
triaje, como en la 4.6b).

### Fila reproducible

`uv run edsim calibracion evaluar --dias 5 --calentamiento 1` (12 réplicas de la ventana
anual; 13 s; código 1, porque con 5 días el IC de los niveles 2 a 5 es más ancho que la
horquilla). Medias: pretriaje 7,08; reloj A de los niveles 2 a 5, 58,58; nivel 3, 20,88;
sobre Manchester, 18,12 %; pretriaje de más de 5 minutos, 31,57 %; 1 censurado, en
septiembre. El test slow `test_reproduce_la_fila_corta_anual_del_registro` la comprueba;
`test_reproduce_la_fila_del_registro_del_centro`, `test_la_semilla_2027_veta_2_2_1_y_queda_3_2_1`,
`test_la_comprobacion_independiente_con_2028` y
`test_el_cumplidor_y_su_siguiente_con_dias_enteros` recalculan las tablas de arriba.
