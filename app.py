import os
from datetime import datetime
from typing import Any

import requests
import streamlit as st

API_BASE = "https://v3.football.api-sports.io"
TIMEOUT_SECONDS = 15

st.set_page_config(
    page_title="Escáner Fútbol",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
  .block-container {max-width: 1050px; padding-top: 1rem; padding-bottom: 4rem;}
  [data-testid="stMetric"] {background: rgba(120,120,120,.08); padding: .8rem; border-radius: 12px;}
  div.stButton > button {width: 100%; min-height: 2.8rem; border-radius: 12px;}
  @media (max-width: 640px) {
    .block-container {padding-left: .8rem; padding-right: .8rem;}
    h1 {font-size: 1.7rem !important;}
    h2 {font-size: 1.3rem !important;}
  }
</style>
""", unsafe_allow_html=True)

st.title("⚽ Escáner Fútbol")
st.caption("Panel móvil de fútbol en vivo · versión inicial de desarrollo")

with st.sidebar:
    st.header("Configuración")
    st.write("La clave se lee desde Secrets o desde una variable de entorno.")
    st.caption("No publiques tu clave de API en GitHub.")
    st.divider()
    st.write("Mercados objetivo")
    st.write("• Córners")
    st.write("• Empate")
    st.write("• Goles")
    st.write("• Ambos equipos marcan")

def get_api_key() -> str:
    try:
        secret = st.secrets.get("API_FOOTBALL_KEY", "")
    except Exception:
        secret = ""
    return str(secret or os.getenv("API_FOOTBALL_KEY", "")).strip()

def api_get(endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    key = get_api_key()
    if not key:
        raise RuntimeError(
            "Falta configurar API_FOOTBALL_KEY en Secrets. "
            "Consulta README.md para ver los pasos."
        )
    response = requests.get(
        f"{API_BASE}/{endpoint}",
        headers={"x-apisports-key": key},
        params=params or {},
        timeout=TIMEOUT_SECONDS,
    )
    if response.status_code == 429:
        raise RuntimeError(
            "API-Football rechazó la consulta por límite de solicitudes (HTTP 429). "
            "Se detuvo el escaneo; revisa el límite de tu plan."
        )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(f"API-Football reportó un error: {payload['errors']}")
    return payload

def safe_stat(stats: list[dict[str, Any]], stat_name: str):
    for team_stats in stats or []:
        for item in team_stats.get("statistics") or []:
            if item.get("type") == stat_name:
                return item.get("value")
    return None

def fixture_label(fixture: dict[str, Any]) -> str:
    teams = fixture.get("teams") or {}
    home = (teams.get("home") or {}).get("name", "Local")
    away = (teams.get("away") or {}).get("name", "Visitante")
    goals = fixture.get("goals") or {}
    score = f"{goals.get('home') if goals.get('home') is not None else '-'}–{goals.get('away') if goals.get('away') is not None else '-'}"
    status = (fixture.get("fixture") or {}).get("status") or {}
    minute = status.get("elapsed")
    minute_text = f"{minute}'" if minute is not None else str(status.get("short", "EN VIVO"))
    league = (fixture.get("league") or {}).get("name", "Liga")
    return f"{home} {score} {away} · {minute_text} · {league}"

def has_core_stats(stats: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    home_corners = safe_stat(stats, "Corner Kicks")
    away_corners = None
    if len(stats or []) > 1:
        for item in (stats[1].get("statistics") or []):
            if item.get("type") == "Corner Kicks":
                away_corners = item.get("value")
                break
    home_shots = safe_stat(stats, "Total Shots")
    away_shots = None
    if len(stats or []) > 1:
        for item in (stats[1].get("statistics") or []):
            if item.get("type") == "Total Shots":
                away_shots = item.get("value")
                break
    missing = []
    if home_corners is None or away_corners is None:
        missing.append("córners")
    if home_shots is None or away_shots is None:
        missing.append("tiros")
    return len(missing) == 0, missing

if "live_fixtures" not in st.session_state:
    st.session_state.live_fixtures = []
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = None
if "stats_cache" not in st.session_state:
    st.session_state.stats_cache = {}

left, right = st.columns([2, 1])
with left:
    st.subheader("Partidos en vivo")
with right:
    refresh = st.button("↻ Actualizar partidos", type="primary")

if refresh:
    try:
        with st.spinner("Consultando partidos en vivo..."):
            data = api_get("fixtures", {"live": "all"})
            st.session_state.live_fixtures = data.get("response", [])
            st.session_state.last_refresh = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.success(f"Partidos recibidos: {len(st.session_state.live_fixtures)}")
    except Exception as exc:
        st.error(str(exc))

if st.session_state.last_refresh:
    st.caption(f"Última consulta: {st.session_state.last_refresh}")

fixtures = st.session_state.live_fixtures
if not fixtures:
    st.info("Pulsa «Actualizar partidos» para cargar el listado. Para conectar la API, primero configura la clave en Secrets.")
else:
    leagues = sorted({
        (f.get("league") or {}).get("name", "Liga")
        for f in fixtures
    })
    chosen_leagues = st.multiselect("Filtrar ligas", leagues, default=leagues)
    filtered = [
        f for f in fixtures
        if (f.get("league") or {}).get("name", "Liga") in chosen_leagues
    ]
    st.metric("Partidos recibidos", len(fixtures))
    st.caption("El listado de partidos usa una consulta. Las estadísticas detalladas requieren consultas adicionales, así que el análisis se limita para cuidar tu cuota.")
    max_scan = st.select_slider(
        "Máximo de partidos para revisar estadísticas en esta ronda",
        options=[1, 2, 3, 4, 5],
        value=3,
        help="Límite intencional para no consumir tu plan gratuito en un solo escaneo."
    )
    if st.button("Analizar partidos seleccionados"):
        selected = filtered[:max_scan]
        results = []
        progress = st.progress(0)
        for idx, fixture in enumerate(selected):
            fixture_id = (fixture.get("fixture") or {}).get("id")
            try:
                cache_key = str(fixture_id)
                if cache_key not in st.session_state.stats_cache:
                    stats_payload = api_get("fixtures/statistics", {"fixture": fixture_id})
                    st.session_state.stats_cache[cache_key] = stats_payload.get("response", [])
                stats = st.session_state.stats_cache[cache_key]
                enough, missing = has_core_stats(stats)
                results.append((fixture, enough, missing, stats, None))
            except Exception as exc:
                results.append((fixture, False, [], [], str(exc)))
                if "HTTP 429" in str(exc):
                    break
            progress.progress((idx + 1) / max(1, len(selected)))
        st.session_state.scan_results = results

    for fixture in filtered:
        st.markdown(f"**{fixture_label(fixture)}**")
        st.divider()

    for fixture, enough, missing, stats, error in st.session_state.get("scan_results", []):
        st.markdown(f"### {fixture_label(fixture)}")
        if error:
            st.warning(f"No se pudo analizar: {error}")
        elif enough:
            home_c = None
            away_c = None
            for i, team_stats in enumerate(stats or []):
                val = None
                for item in team_stats.get("statistics") or []:
                    if item.get("type") == "Corner Kicks":
                        val = item.get("value")
                if i == 0:
                    home_c = val
                elif i == 1:
                    away_c = val
            st.success("Datos mínimos disponibles para evaluar el mercado de córners.")
            c1, c2, c3 = st.columns(3)
            c1.metric("Córners local", home_c if home_c is not None else "—")
            c2.metric("Córners visitante", away_c if away_c is not None else "—")
            c3.metric("Total córners", (home_c or 0) + (away_c or 0) if isinstance(home_c, (int, float)) and isinstance(away_c, (int, float)) else "—")
            st.info("La señal probabilística y el cálculo de EV se habilitarán después de validar el modelo y disponer de cuotas fiables.")
        else:
            st.warning("Datos insuficientes para una señal estricta. Faltan: " + (", ".join(missing) if missing else "estadísticas válidas") + ".")

st.divider()
st.subheader("Estado de los mercados")
market_cols = st.columns(2)
for col, market in zip(market_cols * 2, ["Córners", "Empate", "Goles", "Ambos equipos marcan"]):
    with col:
        st.markdown(f"**{market}**")
        st.caption("Motor de señales pendiente de calibración")
st.caption("Esta versión es un prototipo técnico. No ejecuta apuestas, no confirma cuotas de RushBet y no presenta estimaciones heurísticas como probabilidades validadas.")
