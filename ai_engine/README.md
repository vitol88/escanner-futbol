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
