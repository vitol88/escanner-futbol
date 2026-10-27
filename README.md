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

## Próximas etapas
1. Probar conexión real y respuestas de API-Football.
2. Mejorar filtros de datos y control de cuotas.
3. Desarrollar y validar los cuatro modelos de mercado.
4. Añadir histórico, evaluación retrospectiva y alertas dentro del panel.
5. Desplegar y verificar el enlace final.
