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
