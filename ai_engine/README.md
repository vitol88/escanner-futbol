# Football Lab AI — contrato de datos

Esta carpeta inicia la capa de datos compartida de Football Lab AI. La integración es
progresiva y no modifica el flujo ni la interfaz actual de Streamlit.

## Principios

- No hace solicitudes de red al importar módulos.
- Recibe la función `api_get` que ya utiliza la aplicación.
- Normaliza los datos de API-Football a un contrato estable.
- Relaciona las estadísticas con los equipos por ID, no por el orden de respuesta.
- Conserva los datos ausentes como `None`; nunca los convierte en cero.
- Mantiene los valores originales y las métricas desconocidas.
- Informa la calidad y cobertura de datos por partido.

## Contrato de partido

`build_match_snapshot()` devuelve:

- `schema_version`: versión del contrato.
- `source` y `fetched_at`: procedencia y momento de captura.
- `match`: identidad, competición, estado, marcador y equipos.
- `statistics`: métricas normalizadas por local y visitante.
- `events` y `odds`: datos opcionales del proveedor.
- `data_quality`: campos disponibles y equipos sin estadísticas.

## Uso incremental

```python
from ai_engine.data_engine import FootballDataEngine

engine = FootballDataEngine(
    api_get=api_get,  # adaptador existente de la aplicación
    cache=st.session_state.stats_cache,
)
raw_stats = engine.get_fixture_statistics(fixture_id)
snapshot = engine.snapshot(fixture, statistics=raw_stats)
```

La sección de estadísticas del partido seleccionado ya utiliza este adaptador y guarda
un snapshot versionado en `st.session_state.ai_match_snapshots`, con un máximo de 100
partidos por sesión. La integración reutiliza `api_get` y `stats_cache`; no agrega
consultas, controles visuales ni cambios de navegación. Los próximos motores podrán
consumir esos snapshots sin volver a consultar el proveedor.

## Primer modelo prepartido de goles

`goal_model.estimate_prematch_goals(features)` añade un baseline independiente
de Poisson para goles esperados local/visitante, 1X2, ambos marcan y líneas
totales. Solo calcula cuando ambos equipos tienen al menos cinco partidos de
muestra y están disponibles los cuatro promedios por localía. El mínimo es
configurable. El resultado queda marcado como experimental/no calibrado; no
genera picks, cuotas objetivo ni valor esperado. Antes de usarlo en la aplicación
debe pasar backtesting cronológico y análisis de calibración.

## Primer modelo prepartido de córners

`corner_model.estimate_prematch_corners(features)` consume las variables de
`feature_builder` y el histórico existente de `build_automatic_history`. Estima
córners esperados del local, visitante y total, además de probabilidades Over/Under
para líneas de total y de cada equipo. Exige por defecto cinco partidos con
estadísticas de córners válidas por sede y conserva la abstención cuando faltan
datos. Es un baseline Poisson experimental, no calibrado y sin recomendaciones.
Debe compararse con una binomial negativa si el backtesting confirma
sobredispersión en la distribución histórica de córners.

El histórico de frecuencias empíricas de córners restantes por minuto en
`models/corner_history.py` sigue siendo un componente separado: este primer
modelo es prepartido y no sustituye ni altera el estimador live existente.


## Modelo live de córners restantes

live_corner_model.estimate_live_remaining_corners(features, history_rows) reutiliza models.corner_history.estimate_remaining_corners para consultar frecuencias históricas en el mismo minuto, competición, equipo, sede y estado de córners. Evalúa las perspectivas del local y visitante. Si ambas están disponibles, combina las medias ponderadas por tamaño de muestra: no suma dos estimaciones del total del mismo partido. Si solo una perspectiva alcanza la muestra mínima, usa esa perspectiva y lo informa.

El resultado separa córners actuales, media de córners restantes y total final proyectado. Incluye probabilidades empíricas de al menos uno/dos córners restantes y la frecuencia de que cada equipo consiga al menos uno. Tiros, tiros al arco y posesión se incluyen como contexto descriptivo; todavía no ajustan las probabilidades. No hay multiplicador heurístico de presión. Se abstiene si faltan minuto, equipos, liga, córners actuales o muestra histórica. No consulta API, no accede a Streamlit y no modifica el estimador live actual.
