# Football Lab AI — contrato de datos

La capa de datos se integra progresivamente sin modificar el flujo ni la interfaz actual de Streamlit. Los módulos son puros al importarse y no hacen solicitudes de red por sí solos.

## Contrato y fuentes
- Normaliza fixture, estadísticas, eventos y cuotas de API-Football.
- Asocia estadísticas por ID de equipo y conserva ausencias como None.
- Preserva el árbitro del fixture si el proveedor lo entrega.
- La integración actual reutiliza api_get y stats_cache; no agrega consultas ni controles visuales.

## Modelos experimentales
- goal_model: baseline Poisson prepartido de goles, 1X2 y ambos marcan.
- corner_model: baseline Poisson prepartido de córners.
- live_corner_model: frecuencias empíricas de córners restantes por minuto, equipo, sede y estado.
- card_model: baseline Poisson prepartido de tarjetas amarillas, con tasas por localía y ajuste arbitral reducido hacia un promedio de liga representativo cuando se proporciona.

El historial de tarjetas se extrae de las mismas respuestas fixtures/statistics que ya consulta el historial automático, sin añadir endpoints ni solicitudes. Se conserva el partido, liga, temporada, equipos, tarjetas y árbitro. Para goles, córners y tarjetas, el histórico solo admite partidos finalizados con timestamp conocido y estrictamente anterior al inicio del encuentro objetivo; si falta cualquiera de los timestamps, el partido se excluye para evitar fuga temporal. Cada intento real de consultar estadísticas consume presupuesto aunque la API responda vacío o falle. La comparación arbitral exige además un promedio de liga representativo explícito; el subconjunto de dos equipos no se usa como sustituto de ese promedio. Si falta ese dato o la muestra del árbitro, el factor es neutral. El motor todavía no está conectado a la interfaz ni genera señales.

## Evaluación y calibración
- `evaluation.evaluate_binary_forecasts` calcula Brier score, log loss y tabla de confiabilidad por intervalos.
- `evaluation.evaluate_chronological_holdout` separa por fecha de primer registro y por partido completo, para que snapshots en vivo del mismo fixture no aparezcan simultáneamente en desarrollo y prueba. Solo puntúa resultados verificados del bloque posterior y exige al menos 5 partidos por bloque por defecto.
- La validación cronológica evalúa pronósticos ya registrados; no entrena modelos ni demuestra rentabilidad. Sus desgloses por mercado y liga se calculan únicamente sobre el bloque de prueba posterior, no sobre los datos de desarrollo; cada desglose debe leerse junto con el tamaño de muestra.
- Solo incluye pronósticos con resultado marcado explícitamente como verificado; excluye registros incompletos o inválidos.
- El holdout cronológico exige timestamps con zona horaria explícita. Los timestamps legacy sin zona se excluyen en vez de asumir UTC y alterar el orden temporal.
- Informa si alcanza el mínimo de muestra configurado (30 por defecto), sin presentar ese umbral como garantía de validez.
- La evaluación debe ejecutarse cronológicamente y separarse por liga, mercado y línea. No calcula ROI ni recomienda apuestas.

Todos los modelos son experimentales y no calibrados. Antes de mostrar señales requieren backtesting cronológico, calibración, evaluación de sobredispersión y cuotas verificables. No generan valor esperado ni recomendaciones sin esos insumos.


## Cobertura del histórico de tarjetas

`feature_builder` expone el número de partidos históricos válidos de tarjetas amarillas para la liga del encuentro y el número de esos partidos dirigidos por el árbitro actual. Estos contadores informan disponibilidad, no suficiencia estadística: `card_model` aplica por separado sus mínimos de muestra por equipo y árbitro. No se deriva un promedio arbitral/de liga representativo usando únicamente los dos equipos del encuentro; si falta ese promedio, el ajuste del árbitro permanece neutral.

## Diagnóstico de cobertura por mercado

`coverage.build_data_coverage_report` resume las muestras ya disponibles para goles, córners prepartido, tarjetas amarillas y córners restantes en vivo. Distingue muestra disponible de muestra suficiente y permite configurar los mínimos. No hace llamadas de API ni modifica el estado de Streamlit.

- Goles y córners prepartido usan los tamaños de muestra por localía que ya entrega `automatic_history`.
- Tarjetas cuenta partidos válidos por liga donde el equipo local actuó como local y el visitante como visitante; también cuenta partidos del árbitro actual.
- El ajuste arbitral permanece no disponible hasta contar con un promedio representativo e independiente de toda la liga. El historial de los dos equipos no se usa como promedio de liga.
- Córners en vivo usa una fuente histórica distinta y compara liga, equipo, sede y minuto exacto. Si no se proporciona ese histórico minuto-a-minuto, el diagnóstico lo marca como ausente; no lo sustituye por los promedios prepartido.
- “Suficiente” solo significa que se cumple el mínimo técnico del baseline experimental; no significa que el modelo esté calibrado ni que deba recomendar una apuesta.


## Puertas de ejecución y abstención

`eligibility.build_model_eligibility` aplica una puerta independiente para cada baseline experimental. Solo permite calcular cuando la cobertura correspondiente y las variables requeridas están presentes. Córners en vivo exige además la fuente histórica minuto-a-minuto separada y el estado actual del partido. La falta de datos produce `status="abstain"` con una razón legible; no se sustituye por ceros ni por promedios de otro mercado.

La elegibilidad autoriza únicamente un cálculo experimental, nunca una recomendación: todas las puertas mantienen `may_emit_betting_signal=false`. La política global de señales permanece desactivada hasta completar validación cronológica y calibración. El módulo es puro y todavía no se conecta a la interfaz ni al scanner.


## Orquestador experimental

`pipeline.analyze_experimental_models(features, history, live_corner_history_rows=...)` coordina cobertura, elegibilidad y ejecución de los baselines disponibles. Cada mercado se ejecuta solo si su puerta lo autoriza; si el cálculo devuelve un resultado inválido, el propio mercado vuelve a abstenerse. El resultado conserva cobertura, elegibilidad, proyección y razones de abstención por separado.

El pipeline no consulta APIs, no escribe archivos, no toca Streamlit y no modifica la interfaz. Todas las salidas se marcan como experimentales y la política de recomendaciones/señales permanece desactivada. El histórico minuto-a-minuto live se consulta con el nombre de competición almacenado en esas filas (con ID como fallback), igual que el diagnóstico de cobertura.


## Contrato versionado de pronósticos

`prediction_schema.normalize_prediction_record` adapta una fila nueva o del CSV histórico a un contrato común para cualquier mercado: goles, córners, tarjetas, resultado, empate o ambos marcan. Incluye partido, liga, fase prepartido/en vivo, minuto/marcador, mercado, selección/línea, probabilidad, versión de modelo, fuente, snapshot y estado de verificación. Los metadatos opcionales ausentes se mantienen como desconocidos; no se inventan líneas ni versiones.

- Acepta el campo histórico `estimated_probability_exploratory` y también el campo normalizado `probability`.
- Convierte timestamps con zona explícita a UTC. Los timestamps antiguos sin zona se conservan y marcan como `naive_legacy`; no se adivina su zona horaria.
- Un resultado binario solo se conserva cuando `outcome_verified` es explícito y el resultado es 0 o 1.
- Genera un identificador determinista por partido/fase/mercado/línea/estado/modelo. Para guardar dos snapshots realmente distintos en el mismo minuto y marcador, el productor debe proporcionar `snapshot_id`.
- `normalize_prediction_records` informa filas válidas, inválidas y duplicadas sin modificar el CSV original.

Este contrato es una capa de compatibilidad y validación; todavía no cambia el logger activo ni crea pronósticos adicionales. La integración del registro por mercado se hará cuando cada mercado produzca probabilidades con línea y contexto definidos.


### Integración del registro en vivo

El escáner global de goles ahora añade al CSV el contrato versionado al registrar cada señal en vivo: fase `live`, ID de liga, tipo de mercado, probabilidad normalizada, identificador del modelo, fuente, snapshot y un `prediction_id` determinista. La fecha nueva se escribe en UTC con sufijo `Z`. Se mantienen los campos históricos `estimated_probability_exploratory` y el resto del contexto para que el panel de evaluación existente siga leyendo los CSV anteriores.

La escritura del CSV construye la unión de columnas presentes en todas las filas, de modo que un archivo con filas antiguas y nuevas no falle al guardarse. La deduplicación activa del scanner (fixture/mercado/minuto/marcador) se conserva sin cambios; el snapshot identifica ese estado, pero todavía no se crean nuevas señales por cada variación de estadísticas dentro del mismo minuto. Las líneas y selecciones no se separan si el productor no las entrega explícitamente. Córners, tarjetas y mercados prepartido aún no se añaden a este logger.

Los evaluadores y la auditoría aceptan tanto el campo histórico `estimated_probability_exploratory` como el campo canónico `probability`. Así, los CSV anteriores siguen funcionando y las exportaciones normalizadas pueden evaluarse sin renombrar columnas manualmente.


## Persistencia del histórico minuto a minuto de córners

`live_corner_store.sync_live_corner_history_to_sqlite(database_path, csv_path)` valida el CSV mediante `live_corner_history` y guarda únicamente observaciones válidas en la tabla `live_corner_observations` de SQLite. La clave primaria compuesta por partido, equipo normalizado, sede y minuto hace que la sincronización sea idempotente.

- `load_live_corner_history_from_sqlite(database_path)` recupera las observaciones en el contrato que consume el modelo live.
- `analyze_with_persisted_live_corner_history(database_path, csv_path, features, history, **options)` sincroniza el archivo, carga el histórico acumulado y ejecuta `pipeline.analyze_experimental_models`.
- Si el CSV no existe o no aporta filas válidas, las observaciones previamente almacenadas siguen disponibles.
- La tabla es independiente del ledger de pronósticos: no mezcla observaciones históricas con probabilidades ni resultados de apuestas.
- Esta integración es una capa de servicio probada; todavía no activa captura automática desde API-Football ni modifica la interfaz de Streamlit.

Las salidas siguen siendo experimentales. La política de recomendaciones y señales permanece desactivada.


## Captura automática de córners en vivo

El escáner integra `ai_engine.live_corner_capture.capture_live_corner_snapshot` dentro del ciclo estadístico existente. Usa exclusivamente la respuesta de `fixtures/statistics` que el escáner ya consultó para cada partido de su lote rotativo (máximo cinco partidos por ciclo); no crea solicitudes adicionales a API-Football.

- Guarda una instantánea por partido y minuto con liga, equipos y córners de ambos equipos.
- Si el mismo minuto se consulta más de una vez, conserva el mayor conteo observado y actualiza la hora de última observación; no duplica la clave partido/minuto.
- Rechaza partidos no activos, minutos fuera de rango y estadísticas incompletas.
- La captura es auxiliar: si SQLite falla, el escáner y sus notificaciones siguen funcionando.
- Base de datos predeterminada: `data/football_lab.sqlite3` junto a `app.py`. Se puede cambiar con la variable de entorno `FOOTBALL_LAB_DB_PATH`.
- La base de datos está excluida de Git. En despliegues con sistema de archivos efímero, configura `FOOTBALL_LAB_DB_PATH` hacia un volumen persistente antes de confiar en la acumulación entre reinicios.

**Importante:** estas filas son instantáneas provisionales. No se consideran todavía observaciones históricas de resultado ni alimentan los modelos. Para eso falta verificar el total final de córners de cada partido y calcular los córners posteriores a cada minuto capturado. Esa etapa debe usar estadísticas finales ya disponibles o una consulta de cierre presupuestada, sin convertir conteos parciales en resultados.


## Cierre verificado de snapshots de córners

`live_corner_finalize.finalize_live_corner_fixture(database_path, completed_fixture, final_statistics)` transforma snapshots provisionales en observaciones históricas solo cuando recibe el fixture en estado `FT`, `AET` o `PEN` y las estadísticas finales completas por ID de equipo.

- Comprueba identidad de fixture/equipos/liga y que los córners finales no sean inferiores a ningún snapshot guardado.
- Por cada minuto capturado crea dos filas (perspectiva local y visitante) en `live_corner_observations`.
- Calcula `corners_for_after` y `corners_against_after` como diferencia entre el total final verificado y el conteo observado en ese minuto.
- Usa `INSERT OR IGNORE` con la clave partido/equipo/sede/minuto; repetir el cierre no duplica filas.
- Si falta el resultado final, las estadísticas están incompletas o no coinciden los equipos, no convierte el snapshot en histórico.

La integración con `build_automatic_history` reutiliza las respuestas de estadísticas de partidos finalizados que ya se solicitan para el análisis de forma reciente. No crea consultas adicionales: también ejecuta el cierre cuando la respuesta ya está en la caché de sesión. Por tanto, un partido capturado se cierra cuando vuelve a aparecer en el flujo histórico de un análisis posterior dentro de la misma liga/temporada y se dispone de sus estadísticas. No es un proceso en segundo plano ni garantiza el cierre inmediato al pitazo final. El presupuesto histórico existente sigue siendo el límite de solicitudes.


## Auditoría de cobertura del histórico SQLite

`live_corner_audit.audit_live_corner_database(database_path)` genera un informe de solo lectura sobre la base de datos de córners.

- Separa snapshots provisionales de observaciones verificadas y partidos pendientes de cierre.
- Cuenta observaciones y partidos cerrados por liga.
- Distribuye las capturas por bloques de 15 minutos y las observaciones por equipo/localía.
- Comprueba que cada observación tenga su pareja local/visitante y que los conteos de ambas perspectivas sean recíprocos.
- Si la base no existe, devuelve un informe vacío y no crea archivos ni tablas.

La auditoría describe volumen y consistencia estructural; no mide precisión predictiva, calibración ni rentabilidad. No modifica datos, no consulta APIs y no se conecta a la interfaz. También comprueba la coherencia cronológica de cada equipo y sede: los córners restantes no deben aumentar conforme avanza el minuto y la suma de córners acumulados más restantes debe conservar el mismo total final implícito. Agrupa por `team_key` normalizada para no fragmentar una trayectoria si cambia el nombre visible del equipo.


## Backtest cronológico de referencia para córners restantes

`live_corner_backtest.run_live_corner_baseline_backtest(database_path)` evalúa un baseline sencillo sobre observaciones verificadas:

- Captura y conserva el timestamp Unix del inicio del partido en snapshots y observaciones finales. Las bases existentes se actualizan mediante migraciones aditivas; no se borran filas.
- Ordena partidos por timestamp y reserva el bloque más reciente para prueba. Todas las capturas y perspectivas de un mismo partido permanecen juntas; partidos con el mismo timestamp de inicio también se mantienen en el mismo bloque para impedir solapamiento temporal.
- Entrena únicamente con partidos anteriores a la prueba. La predicción utiliza la media de la liga y bloque de 15 minutos; si no existe esa muestra, recurre a la media de liga y después a la media global de entrenamiento. El resultado identifica qué nivel de histórico se utilizó.
- Reporta MAE y sesgo (predicción menos resultado real) globales y por liga, además de métricas por liga y bloque de 15 minutos. Cada desglose informa cuántos partidos lo respaldan y se abstiene cuando no alcanza el mínimo configurado. Las métricas de error se calculan por observación minuto/equipo (no como promedio de un único error por partido); por ello, los encuentros con más minutos capturados aportan más observaciones y peso al MAE. El número de partidos se informa por separado para contextualizar la cobertura. Como análisis complementario, `fixture_weighted_metrics` calcula primero el error medio dentro de cada partido y luego promedia los partidos con el mismo peso, para comprobar cuánto influye la densidad desigual de capturas. Ninguna de las dos métricas elimina la correlación entre cortes del mismo encuentro; ambas son descriptivas y deben interpretarse con cautela.
- Se abstiene si faltan timestamps o no hay suficientes partidos para entrenamiento y prueba; no vuelve silenciosamente al split aleatorio/hash.
- Abre SQLite en modo solo lectura y no consulta APIs ni modifica la base.

Las observaciones históricas antiguas sin timestamp no se puntúan: deben volver a generarse mediante capturas nuevas para poder participar en una evaluación cronológica. Este baseline no es un modelo entrenado ni una recomendación de apuesta, y sus métricas no demuestran rentabilidad.

## Informe local de auditoría y backtest

Ejecuta desde la raíz del repositorio:

```bash
python -m ai_engine.live_corner_report
```

El comando usa por defecto `data/football_lab.sqlite3` (o la ruta definida en `FOOTBALL_LAB_DB_PATH`). También acepta una ruta explícita y salida JSON:

```bash
python -m ai_engine.live_corner_report --db /ruta/football_lab.sqlite3 --json
```

El informe combina la auditoría de snapshots/cierres verificados con el backtest cronológico, incluyendo motivos de abstención y métricas disponibles. Es de solo lectura, no consulta API-Football y no activa señales. Si el histórico todavía no alcanza los mínimos o faltan timestamps, informa esa condición en vez de inventar una precisión.

La evaluación también compara el baseline segmentado por liga/minuto con una referencia ingenua: la media global de córners restantes calculada solo con el bloque de entrenamiento. Informa ambos MAE y la mejora relativa del baseline segmentado. Si la referencia global tiene MAE cero, la mejora relativa queda como no calculable. Esta comparación evita declarar útil una segmentación que no supere una predicción constante; sigue siendo una evaluación experimental, no una prueba de rentabilidad.

### Evaluación rolling-origin de córners en vivo

El backtest también ejecuta tres bloques cronológicos de evaluación *expanding-window*: cada bloque se predice usando únicamente partidos anteriores y el conjunto de entrenamiento crece en los bloques siguientes. Los partidos con el mismo kickoff permanecen juntos y se informa el MAE ponderado frente al promedio global de entrenamiento. Si el histórico no alcanza para formar bloques con suficientes partidos, el resultado se marca como no disponible; no se relajan los mínimos para fabricar métricas. Esta evaluación es experimental y no activa señales ni demuestra rentabilidad.

La salida rolling-origin incluye además el número de bloques que mejoran o empeoran frente al promedio global, el rango entre el MAE más bajo y más alto y una etiqueta descriptiva de estabilidad (improves_in_every_fold, worse_in_every_fold, mixed_results, etc.). Es un resumen diagnóstico, no una aprobación automática del predictor: una mejora ponderada puede coexistir con bloques individuales peores.


### Evaluación configurable de líneas O/U de córners restantes

El backtest acepta líneas de medio córner explícitas mediante `over_under_lines`; el informe local permite indicarlas con `--corner-lines 4.5,5.5,6.5`. No hay líneas predeterminadas: se evalúan únicamente las que el usuario configure. Para cada línea se compara la media pronosticada (calculada solo con el entrenamiento) frente al resultado verificado y se informa matriz de confusión, tasa real/predicha de over, accuracy, sensibilidad, especificidad y balanced accuracy. Se usan líneas x.5 para evitar resultados push en líneas enteras. La evaluación es descriptiva: no convierte la media en probabilidad, no incorpora cuotas, no calcula ROI y no emite señales. La prueba conserva el split cronológico y las observaciones de un mismo partido agrupadas.
