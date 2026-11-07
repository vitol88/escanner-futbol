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

El historial de tarjetas se extrae de las mismas respuestas fixtures/statistics que ya consulta el historial automático, sin añadir endpoints ni solicitudes. Se conserva el partido, liga, temporada, equipos, tarjetas y árbitro; se filtran partidos posteriores al encuentro objetivo cuando existen timestamps. La comparación arbitral exige además un promedio de liga representativo explícito; el subconjunto de dos equipos no se usa como sustituto de ese promedio. Si falta ese dato o la muestra del árbitro, el factor es neutral. El motor todavía no está conectado a la interfaz ni genera señales.

Todos los modelos son experimentales y no calibrados. Antes de mostrar señales requieren backtesting cronológico, calibración, evaluación de sobredispersión y cuotas verificables. No generan valor esperado ni recomendaciones sin esos insumos.
