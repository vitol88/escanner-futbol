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

En la pestaña **Rendimiento del modelo**, puedes descargar el CSV de señales y cargarlo en el evaluador retrospectivo. Cuando ya se conozca el resultado del evento, completa estas columnas en cada fila que quieras evaluar:

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


## Historial automático de equipos

Durante el escaneo, la app consulta los últimos partidos de cada equipo dentro de la liga y temporada del encuentro. Calcula promedios de goles por sede y, cuando las estadísticas históricas de la API están disponibles, córners a favor y en contra. Los resultados y estadísticas históricas se cachean durante la sesión.

Para limitar consumo de API, la primera versión limita las búsquedas históricas de equipos a 12 consultas por escaneo y las consultas de estadísticas históricas a 8 por escaneo. Cuando se alcanza el límite, los datos no disponibles se muestran como N/D; no se inventan valores. El caché de sesión desaparece al reiniciarse la aplicación.

Esta versión aún no incorpora un archivo histórico minuto a minuto ni un historial de enfrentamientos directos al modelo. Los promedios de resultados recientes y córners por sede son contexto exploratorio; no son probabilidades calibradas ni garantías de rentabilidad.


## Cambios recientes del escáner

- Los accesos rápidos de cada partido permiten consultar la lectura exploratoria de goles, empate, ambos marcan y córners.
- El detalle de partido muestra un campo esquemático (no posiciones reales) y permite solicitar los últimos cinco enfrentamientos directos bajo demanda. Esa consulta se cachea durante la sesión para no repetirla innecesariamente.
- El registro de señales se carga desde `registro_senales_escanner.csv` si el archivo existe y se actualiza al registrar señales nuevas. La ruta se puede cambiar con la variable de entorno `SIGNAL_HISTORY_PATH`. Se evita duplicar una señal idéntica del mismo partido, mercado, minuto y marcador.
- **Importante sobre persistencia:** el archivo se conserva mientras el sistema de archivos del host conserve los datos. Algunos alojamientos gratuitos reinician o usan disco efímero; en esos casos descarga el CSV o configura almacenamiento externo antes de depender de él como histórico permanente.
- El botón «Probar sonido» ayuda a comprobar el audio después de una interacción del usuario. El navegador puede bloquear sonido automático y notificaciones si la página no está activa o no se concedieron permisos.
- Las notificaciones push con la app cerrada en iPhone todavía requieren un servicio push, service worker, suscripción y claves de configuración; no se consideran implementadas por estas alertas dentro de Streamlit.
- El campo esquemático y las probabilidades son informativos. Los modelos siguen siendo exploratorios y no han demostrado calibración ni rentabilidad.


### Diseño y acciones por partido en vivo

La vista **En vivo** agrupa los partidos en listas desplegables por país y competición. Al abrir un encuentro, muestra los escudos disponibles, marcador y minuto, junto con cuatro acciones principales:

- **Estadísticas en vivo:** solicita bajo demanda posesión, tiros, tiros a puerta, córners, pases, faltas, tarjetas, fueras de juego y atajadas, según los datos que entregue la API.
- **H2H:** muestra hasta cinco enfrentamientos finalizados disponibles de la competición actual, con fecha, escudos, equipos y marcador. La consulta se guarda en caché durante la sesión.
- **Goles y señales:** muestra el análisis calculado para ese encuentro, incluidos promedios local/visitante, lectura en vivo y tip principal cuando existan datos suficientes.
- **Córners:** muestra córners actuales por equipo, promedios históricos por sede, ritmo en vivo y una proyección orientativa cuando los datos estén disponibles.

El botón seleccionado queda resaltado en amarillo y el panel de análisis aparece con una transición visual. Los botones consultan el partido seleccionado; los datos faltantes se muestran como no disponibles y no se sustituyen por valores inventados. Estas consultas bajo demanda pueden consumir solicitudes del plan gratuito de API-Football.


### Auditoría de calidad del CSV

El módulo puro `ai_engine.dataset_audit.audit_forecast_dataset` permite revisar un CSV exportado sin modificarlo: identifica registros con metadatos o probabilidades inválidas, duplicados por partido/mercado/minuto/marcador y resultados explícitamente verificados. Esta auditoría mide calidad estructural; no sustituye el evaluador de calibración, no completa resultados faltantes y no calcula rentabilidad.


## Persistencia remota del registro central (Supabase)

Para conservar los pronósticos aunque Streamlit Community Cloud reinicie su disco, la app puede sincronizar el ledger con Supabase usando los secretos existentes `SUPABASE_URL` y `SUPABASE_SECRET_KEY`.

Antes de usar esta función, ejecuta una sola vez el SQL de `supabase/migrations/001_prediction_ledger.sql` en el SQL Editor del proyecto Supabase. La migración crea `public.prediction_ledger`, con `prediction_id` como clave primaria para evitar duplicados. No elimina ni modifica `telegram_alerts`.

Con la tabla creada, cada escaneo sincroniza los pronósticos válidos y **Consultar registro central** lee el histórico remoto. SQLite local se conserva como caché/fallback. Si la tabla remota no existe o Supabase no responde, la interfaz muestra el error y no presenta el disco local como persistencia garantizada.

Los CSV históricos que no estén presentes en el entorno desplegado deben importarse desde una copia exportada previamente; la conexión remota no puede recuperar archivos que ya no están en el host. No borres la copia original después de importarla hasta comprobar los contadores y la exportación desde Supabase.

## Registro central de pronósticos (SQLite)

El escáner mantiene ahora un ledger independiente y append-only en SQLite, por defecto `registro_pronosticos_football_lab.sqlite3`. La ruta se puede configurar con `PREDICTION_LEDGER_PATH`.

- Cada fila se normaliza con el esquema versionado y conserva fixture, fecha UTC cuando está disponible, fase, mercado, línea, probabilidad, modelo, versión y snapshot.
- `prediction_id` es clave única: volver a procesar una misma señal no crea una segunda fila. Snapshots realmente distintos pueden conservarse por separado.
- Las inserciones se realizan en transacción. Los registros inválidos se omiten y los resultados no se completan salvo que estén marcados explícitamente como verificados.
- El ledger se alimenta actualmente de las señales de goles en vivo que ya registra el escáner. No significa todavía que todos los mercados, pronósticos pre-partido o proyecciones de córners/tarjetas estén conectados a persistencia.
- El CSV histórico anterior se mantiene sin cambios y sigue siendo compatible. Si una escritura del ledger falla, la app vuelve a intentar sincronizar los registros canónicos guardados en el CSV durante el siguiente escaneo.
- La base SQLite reside en el disco del host. En despliegues con almacenamiento efímero, configura un volumen persistente o una ruta persistente antes de usarla como histórico a largo plazo.

El ledger no emite apuestas ni cambia umbrales, cálculos o presentación de la app. Las probabilidades registradas siguen siendo experimentales hasta completar validación cronológica con resultados verificados.

## Histórico minuto a minuto para córners en vivo

El módulo `ai_engine.live_corner_history.load_live_corner_history_csv` permite incorporar un histórico explícito para el estimador de córners restantes. El archivo CSV debe contener estas columnas:

- `fixture_id`, `league`, `team`, `venue` (`home`/`away`), `minute`
- `corners_for`, `corners_against`: córners acumulados hasta el minuto indicado.
- `corners_for_after`, `corners_against_after`: córners adicionales obtenidos después de ese corte hasta el final del partido.

Cada observación debe corresponder a un partido finalizado y a un corte temporal real. El cargador valida números, minuto, sede, columnas e identidad del partido; informa filas inválidas y duplicados, y no inventa observaciones. No transforma promedios de partido completo en datos minuto a minuto.

Este cargador es una base de entrada y validación: la app todavía no consume automáticamente este archivo ni registra snapshots en vivo para construirlo. Hasta conectar una fuente histórica suficiente, el modelo live de córners debe abstenerse. El histórico prepartido de equipos no sustituye esta fuente.
