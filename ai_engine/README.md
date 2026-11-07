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
- card_model: baseline Poisson prepartido de tarjetas amarillas, con tasas por localía y ajuste arbitral reducido hacia la media de liga cuando hay muestra suficiente.

El modelo de tarjetas requiere history_rows con partidos terminados antes del inicio del encuentro objetivo, de la misma competición, IDs de equipos y tarjetas amarillas de ambos equipos. El árbitro es opcional; sin muestra suficiente se conserva un factor neutral. La aplicación todavía no recolecta ni conecta automáticamente ese histórico con este modelo: no se agregan consultas API ni se activa en la interfaz en esta etapa.

Todos los modelos son experimentales y no calibrados. Antes de mostrar señales requieren backtesting cronológico, calibración, evaluación de sobredispersión y cuotas verificables. No generan valor esperado ni recomendaciones sin esos insumos.
