import os
from datetime import datetime
from typing import Any

import requests
import streamlit as st

from models.probabilities import (
    corner_pace_per_90,
    estimate_live_goal_markets,
    load_league_baselines,
)

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

MODEL_DATA = load_league_baselines()

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

def safe_stat(
    stats: list[dict[str, Any]],
    stat_name: str,
    team_index: int = 0,
):
    """Return a statistic for one team only (0=home, 1=away).

    Never search other teams as a fallback: missing data must remain missing.
    """
    if team_index < 0 or team_index >= len(stats or []):
        return None
    team_stats = (stats or [])[team_index]
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
    # API-Football returns one statistics object per team, home first and away second.
    # Read each team explicitly so one team's values can never fill the other's gap.
    home_corners = safe_stat(stats, "Corner Kicks", team_index=0)
    away_corners = safe_stat(stats, "Corner Kicks", team_index=1)
    home_shots = safe_stat(stats, "Total Shots", team_index=0)
    away_shots = safe_stat(stats, "Total Shots", team_index=1)
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
            st.info("Los conteos son datos observados en vivo; no equivalen a una recomendación de apuesta.")
            elapsed = ((fixture.get("fixture") or {}).get("status") or {}).get("elapsed")
            if isinstance(home_c, (int, float)) and isinstance(away_c, (int, float)):
                pace = corner_pace_per_90(home_c + away_c, elapsed if isinstance(elapsed, int) else None)
                if pace is not None:
                    st.metric("Ritmo de córners extrapolado (por 90 min)", round(pace, 1))
                    st.caption("Referencia descriptiva basada en el ritmo actual; no es una probabilidad ni una señal validada.")
        else:
            st.warning("Datos insuficientes para evaluar córners. Faltan: " + (", ".join(missing) if missing else "estadísticas válidas") + ".")

        league_data = fixture.get("league") or {}
        goals_data = fixture.get("goals") or {}
        elapsed_value = ((fixture.get("fixture") or {}).get("status") or {}).get("elapsed")
        score_h = goals_data.get("home")
        score_a = goals_data.get("away")
        estimate = estimate_live_goal_markets(
            country=league_data.get("country"),
            league_name=league_data.get("name"),
            score_home=score_h if isinstance(score_h, int) else None,
            score_away=score_a if isinstance(score_a, int) else None,
            elapsed_minute=elapsed_value if isinstance(elapsed_value, int) else None,
            data=MODEL_DATA,
        )
        st.markdown("**Mercados de goles · estimación exploratoria**")
        if estimate.get("available"):
            st.caption(
                f"Referencia histórica: {estimate['baseline_league']} · "
                f"{estimate['baseline_matches']} partidos · minuto {estimate['minute_used']}. "
                f"Modelo provisional por promedio de liga; no calibrado ni validado para apuestas."
            )
            g1, g2 = st.columns(2)
            g1.metric("Más de 0.5 goles finales", f"{estimate['over_total_goals']['0.5'] * 100:.1f}%")
            g2.metric("Más de 1.5 goles finales", f"{estimate['over_total_goals']['1.5'] * 100:.1f}%")
            g3, g4 = st.columns(2)
            g3.metric("Más de 2.5 goles finales", f"{estimate['over_total_goals']['2.5'] * 100:.1f}%")
            g4.metric("Más de 3.5 goles finales", f"{estimate['over_total_goals']['3.5'] * 100:.1f}%")
            g5, g6 = st.columns(2)
            g5.metric("Empate final", f"{estimate['draw_final'] * 100:.1f}%")
            g6.metric("Ambos equipos marcan", f"{estimate['btts_final'] * 100:.1f}%")
            st.caption(
                f"Goles restantes esperados por el modelo: local {estimate['expected_home_goals_remaining']:.2f}, "
                f"visitante {estimate['expected_away_goals_remaining']:.2f}."
            )
        else:
            st.caption("Sin probabilidad calculada: " + str(estimate.get("reason") or "faltan datos fiables"))

st.divider()
st.subheader("Estado de los mercados")
market_status = [
    ("Córners", "Se muestran córners observados y ritmo por 90 minutos cuando hay estadísticas completas. No hay historial de córners suficiente para calibrar probabilidades."),
    ("Goles", "Estimaciones exploratorias por medias históricas de liga en competiciones con al menos 30 partidos de referencia."),
    ("Empate", "Probabilidad exploratoria de empate final a partir de un modelo Poisson simplificado; todavía requiere validación retrospectiva."),
    ("Ambos equipos marcan", "Probabilidad exploratoria condicionada al marcador y los goles restantes; todavía requiere validación retrospectiva."),
]
market_cols = st.columns(2)
for col, (market, status_text) in zip(market_cols * 2, market_status):
    with col:
        st.markdown(f"**{market}**")
        st.caption(status_text)
st.caption("La base histórica de goles usada en esta rama procede del archivo compartido actualizado el 26/10/2026. Las cifras son exploratorias, no señales validadas. No hay cuotas verificadas de RushBet ni EV calculado todavía; no se ejecutan apuestas automáticamente.")
