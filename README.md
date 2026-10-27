# Escáner Fútbol — versión móvil inicial

Aplicación web Streamlit preparada para pantalla de celular. Esta es una base de desarrollo; todavía no es un sistema de trading validado ni una publicación en internet.

## Requisitos
- Python 3.10 o superior
- Clave válida de API-Football

## Ejecutar localmente
1. Instala Python desde https://www.python.org/downloads/ (en Windows, marca “Add Python to PATH”).
2. Descomprime este proyecto.
3. Abre una terminal en la carpeta del proyecto.
4. Instala dependencias:
   `python -m pip install -r requirements.txt`
5. Copia `.streamlit/secrets.toml.example` a `.streamlit/secrets.toml`.
6. En `secrets.toml`, reemplaza `PEGA_TU_CLAVE_AQUI` por tu clave. No compartas ese archivo ni lo subas a GitHub.
7. Ejecuta:
   `python -m streamlit run app.py`

## Preparación para publicar
Para despliegue en Streamlit Community Cloud:
1. Crea un repositorio privado en GitHub y sube los archivos del proyecto, excepto `.streamlit/secrets.toml`.
2. En Streamlit Community Cloud, conecta tu cuenta de GitHub, selecciona el repositorio y `app.py`.
3. En la configuración de Secrets del servicio, agrega:
   `API_FOOTBALL_KEY = "TU_CLAVE"`
4. Publica y prueba el enlace desde el celular.

Los nombres exactos de botones pueden variar según la interfaz actual del proveedor.

## Límites y seguridad
- No hay integración de cuotas RushBet en esta versión.
- No se calculan probabilidades ni EV hasta implementar y probar un modelo calibrado.
- Cada partido analizado puede consumir una consulta adicional de estadísticas. El listado global en vivo usa una consulta.
- Las estadísticas se almacenan en caché durante la sesión para evitar consultas repetidas.
- El plan de API puede variar; verifica el límite vigente en tu panel de API-Football.
- No se ejecutan apuestas automáticamente.

## Registro y evaluación retrospectiva de señales

En la pestaña **Estado de los mercados**, descarga el CSV de señales de la sesión y consérvalo. Cuando ya se conozca el resultado del evento, completa estas columnas en cada fila que quieras evaluar:

- `estimated_probability_exploratory`: probabilidad que guardó el escáner, entre 0 y 1.
- `outcome`: **1 si se cumplió el mercado concreto de esa fila** y **0 si no se cumplió**. No escribas aquí el marcador final. Ejemplo: para “Ambos equipos marcan”, usa 1 si ambos anotaron y 0 si no.
- `outcome_verified`: escribe `true` solo después de comprobar el resultado real.

Después, carga el CSV completado en el evaluador retrospectivo. Las filas no verificadas, inválidas o sin resultado binario se excluyen. El Brier score mide el error de las probabilidades (0 es perfecto; menor es mejor). La tasa de acierto por sí sola no demuestra que las probabilidades estén calibradas. Evalúa cada tipo de mercado por separado y reúne una muestra suficiente antes de sacar conclusiones.

La evaluación es manual y experimental: no consulta resultados finales automáticamente, no ajusta todavía los modelos y no demuestra rentabilidad ni valor esperado (EV).

## Próximas etapas
1. Probar conexión real y respuestas de API-Football.
2. Mejorar filtros de datos y control de cuotas.
3. Desarrollar y validar los cuatro modelos de mercado.
4. Añadir histórico, evaluación retrospectiva y alertas dentro del panel.
5. Desplegar y verificar el enlace final.


## Estimación histórica de goles en los minutos finales

En la pestaña de goles se puede cargar un CSV con el historial de cada equipo al llegar a un minuto de corte. Formato requerido (una fila por equipo y partido terminado):

`league,team,minute,score_for,score_against,goals_for_after,goals_against_after`

- `league`: nombre de la competición tal como aparece en el escáner (por ejemplo, `Serie A`).
- `team`: nombre del equipo.
- `minute`: minuto de corte histórico (por ejemplo, `70`).
- `score_for` y `score_against`: goles del equipo y rival en ese minuto.
- `goals_for_after` y `goals_against_after`: goles de cada lado desde después del corte hasta el final.

El panel estima frecuencias de al menos un gol adicional, al menos dos y probabilidad empírica de que ese equipo vuelva a marcar. Prioriza el marcador exacto si hay al menos 8 casos; si no, usa la muestra del equipo en esa liga y minuto, siempre que tenga al menos 8 registros. Muestra insuficiente significa `N/D`, no cero.

**Limitación actual:** el escáner todavía no recopila automáticamente todo el historial de eventos de cada equipo. API-Football requiere consultar los eventos por partido, lo que puede consumir muchas llamadas; por eso esta primera versión recibe el historial mediante CSV y no realiza barridos históricos ocultos que agoten el plan gratuito. Las frecuencias no están calibradas y no garantizan resultados.

