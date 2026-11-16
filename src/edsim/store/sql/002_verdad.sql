-- 002_verdad: la verdad de las ejecuciones guardadas y los roles (docs/specs/hito-8.md, H8-6).
--
-- La verdad no pasa por Kafka (H7-2): la carga `edsim almacen cargar-verdad`, con COPY, desde los
-- ficheros de la ejecución. Las tablas son normales, no hypertables: Timescale exigiría la columna
-- de partición en la clave, y la verdad se carga entera y no crece en directo.

CREATE SCHEMA IF NOT EXISTS verdad;

-- Los eventos verdaderos: las columnas de bronce.eventos menos las de Kafka, `valor`, `recibido`
-- e `ingest_time`, con sus tipos (las once que declara analitica/models/fuentes.yml).
CREATE TABLE verdad.eventos (
    event_id       text             NOT NULL,
    event_type     text             NOT NULL,
    schema_version integer          NOT NULL,
    run_id         text             NOT NULL,
    episode_id     text,
    patient_id     text,
    source_system  text             NOT NULL,
    sim_time       double precision NOT NULL,
    event_time     timestamptz      NOT NULL,
    recorded_time  timestamptz      NOT NULL,
    payload        jsonb            NOT NULL,
    PRIMARY KEY (run_id, event_id)
);

-- La ficha de cada episodio: las 65 columnas de ground_truth_episodios.csv (modelo del hito 5,
-- esquema 4), con sus nombres. `respuesta_pruebas` va siempre vacía con el modelo clínico.
CREATE TABLE verdad.episodios (
    episodio                     text NOT NULL,
    llegada                      bigint NOT NULL,
    minuto_llegada               double precision NOT NULL,
    nivel                        integer NOT NULL,
    triaje                       double precision NOT NULL,
    valoracion                   double precision NOT NULL,
    reevaluacion                 double precision NOT NULL,
    pruebas                      boolean NOT NULL,
    respuesta_pruebas            double precision,
    destino                      text NOT NULL,
    franja                       text NOT NULL,
    tipo_dia                     text NOT NULL,
    estacion                     text NOT NULL,
    banda                        integer NOT NULL,
    edad                         integer NOT NULL,
    sexo                         text NOT NULL,
    medio                        text NOT NULL,
    motivo                       text NOT NULL,
    z_gravedad                   double precision NOT NULL,
    gravedad                     double precision NOT NULL,
    nivel_real                   integer NOT NULL,
    calidad_triaje               text NOT NULL,
    salto                        integer NOT NULL,
    pedida_analitica             boolean NOT NULL,
    pedida_radiografia           boolean NOT NULL,
    pedida_ecg                   boolean NOT NULL,
    pedida_imagen                boolean NOT NULL,
    alterada_analitica           boolean NOT NULL,
    alterada_radiografia         boolean NOT NULL,
    alterada_ecg                 boolean NOT NULL,
    alterada_imagen              boolean NOT NULL,
    respuesta_base_analitica     double precision NOT NULL,
    respuesta_base_radiografia   double precision NOT NULL,
    respuesta_base_ecg           double precision NOT NULL,
    respuesta_base_imagen        double precision NOT NULL,
    sorteo_pedida_analitica      double precision NOT NULL,
    sorteo_alterada_analitica    double precision NOT NULL,
    sorteo_respuesta_analitica   double precision NOT NULL,
    sorteo_pedida_radiografia    double precision NOT NULL,
    sorteo_alterada_radiografia  double precision NOT NULL,
    sorteo_respuesta_radiografia double precision NOT NULL,
    sorteo_pedida_ecg            double precision NOT NULL,
    sorteo_alterada_ecg          double precision NOT NULL,
    sorteo_respuesta_ecg         double precision NOT NULL,
    sorteo_pedida_imagen         double precision NOT NULL,
    sorteo_alterada_imagen       double precision NOT NULL,
    sorteo_respuesta_imagen      double precision NOT NULL,
    centro                       text NOT NULL,
    huella_centro                text NOT NULL,
    llegadas                     text NOT NULL,
    huella_llegadas              text NOT NULL,
    dias                         integer NOT NULL,
    calentamiento                integer NOT NULL,
    semilla                      bigint NOT NULL,
    run_id                       text NOT NULL,
    perfiles                     text NOT NULL,
    huella_perfiles              text NOT NULL,
    z_paciencia                  double precision NOT NULL,
    paciencia                    double precision NOT NULL,
    sorteo_destino_alta          double precision NOT NULL,
    sorteo_destino_ingreso       double precision NOT NULL,
    sorteo_destino_traslado      double precision NOT NULL,
    sorteo_destino_exitus        double precision NOT NULL,
    z_cama                       double precision NOT NULL,
    espera_cama_base             double precision NOT NULL,
    PRIMARY KEY (run_id, episodio)
);

-- Las llegadas de cada día: las columnas de ground_truth_dias.csv.
CREATE TABLE verdad.dias (
    dia               integer          NOT NULL,
    fecha             date             NOT NULL,
    efecto_diario     double precision NOT NULL,
    esperadas         double precision NOT NULL,
    cota              double precision NOT NULL,
    candidatas        integer          NOT NULL,
    aceptadas         integer          NOT NULL,
    centro            text             NOT NULL,
    huella_centro     text             NOT NULL,
    llegadas          text             NOT NULL,
    huella_llegadas   text             NOT NULL,
    dias              integer          NOT NULL,
    calentamiento     integer          NOT NULL,
    semilla           bigint           NOT NULL,
    run_id            text             NOT NULL,
    PRIMARY KEY (run_id, dia)
);

-- La libreta de cada perfil registrado: una fila por hecho de registros/<perfil>-s<semilla>/
-- defectos.csv. `run_id` es el derivado (<run_id>_<perfil>_s<semilla>), el que lleva lo
-- registrado en bronce; `run_id_origen`, la ejecución verdadera, que es lo que borra y vuelve a
-- cargar `cargar-verdad`. Sin clave: `registro` es nulo en los hechos perdidos o pendientes.
CREATE TABLE verdad.libreta (
    run_id_origen    text             NOT NULL,
    run_id           text             NOT NULL,
    perfil           text             NOT NULL,
    semilla          bigint           NOT NULL,
    registro         text,
    hecho            text             NOT NULL,
    clase            text             NOT NULL,
    retraso_min      double precision,
    desfase_min      double precision,
    campo_vacio      text,
    campo_erroneo    text,
    valor_verdadero  text,
    valor_registrado text,
    duplicado_de     text,
    corrige          text
);
CREATE INDEX ON verdad.libreta (run_id_origen);
CREATE INDEX ON verdad.libreta (run_id);

-- Los roles son de todo el servidor, no de una base, y cada sesión de tests crea su propia base
-- en el mismo servidor: se crean solo si no existen y sin que dos migraciones a la vez se pisen.
-- `duplicate_object` es el rol que ya existe; `unique_violation`, dos CREATE ROLE cruzados (el
-- índice de pg_authid). Contraseñas de desarrollo iguales al nombre, como las de compose.yaml:
-- es un candado contra mirar la solución sin querer, no seguridad.
DO $$
BEGIN
    CREATE ROLE hospital LOGIN PASSWORD 'hospital';
EXCEPTION WHEN duplicate_object OR unique_violation THEN
    NULL;
END
$$;

DO $$
BEGIN
    CREATE ROLE laboratorio LOGIN PASSWORD 'laboratorio';
EXCEPTION WHEN duplicate_object OR unique_violation THEN
    NULL;
END
$$;

-- `laboratorio` lo lee todo: bronce y verdad, las tablas que hay y las que cree `edsim`
-- después (ALTER DEFAULT PRIVILEGES vale para los objetos que crea el rol que migra).
-- `hospital` no tiene USAGE en ninguno de los dos: un esquema nuevo no lo da a PUBLIC.
GRANT USAGE ON SCHEMA bronce, verdad TO laboratorio;
GRANT SELECT ON ALL TABLES IN SCHEMA bronce, verdad TO laboratorio;
ALTER DEFAULT PRIVILEGES IN SCHEMA bronce, verdad GRANT SELECT ON TABLES TO laboratorio;
