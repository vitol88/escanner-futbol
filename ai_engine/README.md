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
- Informa si alcanza el mínimo de muestra configurado (30 por defecto), sin presentar ese umbral como garantía de validez.
- La evaluación debe ejecutarse cronológicamente y separarse por liga, mercado y línea. No calcula ROI ni recomienda apuestas.

Todos los modelos son experimentales y no calibrados. Antes de mostrar señales requieren backtesting cronológico, calibración, evaluación de sobredispersión y cuotas verificables. No generan valor esperado ni recomendaciones sin esos insumos.


## Cobertura del histórico de tarjetas

`feature_builder` expone el número de partidos históricos válidos de tarjetas amarillas para la liga del encuentro y el número de esos partidos dirigidos por el árbitro actual. Estos contadores informan disponibilidad, no suficiencia estadística: `card_model` aplica por separado sus mínimos de muestra por equipo y árbitro. No se deriva un promedio arbitral/de liga representativo usando únicamente los dos equipos del encuentro; si falta ese promedio, el ajuste del árbitro permanece neutral.
