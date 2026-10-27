import csv
import io
import os
from datetime import datetime
from typing import Any

import requests
import streamlit as st

from models.live_context import qualifies_as_corner_candidate, summarize_live_context
from models.probabilities import (
    corner_pace_per_90,
    estimate_live_goal_markets,
    load_league_baselines,
    poisson_at_least,
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
  :root { --scanner-yellow: #FACC15; --scanner-black: #0B0D10; --scanner-panel: #15191F; }
  .stApp { background: var(--scanner-black); color: #F4F4F5; }
  [data-testid="stHeader"] { background: rgba(11,13,16,.96); }
  [data-testid="stSidebar"] { background: #111419; border-right: 1px solid #34302A; }
  .block-container {max-width: 1120px; padding-top: 1rem; padding-bottom: 4rem;}
  h1, h2, h3 { color: #FACC15 !important; }
  [data-testid="stMetric"] {background: #171B21; border: 1px solid #393326; padding: .8rem; border-radius: 12px;}
  div.stButton > button, div.stDownloadButton > button {
    width: 100%; min-height: 2.8rem; border-radius: 12px;
    border: 1px solid #FACC15; background: #FACC15; color: #111111; font-weight: 700;
  }
  div.stButton > button:hover, div.stDownloadButton > button:hover {
    background: #FFE566; border-color: #FFE566; color: #111111;
  }
  [data-testid="stTabs"] button[role="tab"] { color: #D4D4D8; font-weight: 650; }
  [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    color: #FACC15; border-bottom-color: #FACC15;
  }
  [data-testid="stDataFrame"] { border: 1px solid #3A3426; border-radius: 10px; overflow: hidden; }
  [data-testid="stExpander"] { background: #15191F; border: 1px solid #3A3426; border-radius: 12px; }
  hr { border-color: #38342B; }
  .brand-header { display:flex; align-items:center; gap:14px; padding:14px 16px; margin:0 0 14px 0; background:linear-gradient(120deg,#15191F,#0B0D10); border:1px solid #393326; border-radius:16px; }
  .brand-mark { width:52px; height:52px; flex:0 0 52px; display:flex; align-items:center; justify-content:center; background:radial-gradient(circle at 30% 25%,#FFE566,#D9A900); border:1px solid #FFE566; border-radius:15px; font-size:25px; box-shadow:0 0 22px rgba(250,204,21,.18); }
  .loading-brand { display:flex; align-items:center; gap:12px; padding:14px; margin:8px 0; border:1px solid #393326; border-radius:14px; background:linear-gradient(120deg,#171B21,#101216); }
  .loading-orbit { width:36px; height:36px; border:3px solid #393326; border-top-color:#FACC15; border-right-color:#FACC15; border-radius:50%; animation:lab-spin .8s linear infinite; flex:0 0 36px; }
  @keyframes lab-spin { to {transform:rotate(360deg);} }
  .loading-title { color:#FACC15; font-weight:800; letter-spacing:.5px; }
  .loading-subtitle { color:#A1A1AA; font-size:12px; margin-top:3px; }
  .brand-title { font-size:22px; line-height:1.15; letter-spacing:1.5px; font-weight:900; color:#F4F4F5; }
  .brand-title span { color:#FACC15; }
  .brand-subtitle { color:#A1A1AA; font-size:10px; letter-spacing:1px; margin-top:5px; }
  .brand-pill { margin-left:auto; white-space:nowrap; color:#FACC15; border:1px solid #554719; background:#242014; border-radius:999px; padding:6px 9px; font-size:10px; font-weight:800; }
  [data-testid="stExpander"] summary p { font-weight:700; }
  [data-testid="stExpander"] summary:hover { color:#FACC15; }
  div[data-testid="stMetricLabel"] p { color:#A1A1AA !important; font-size: .78rem; }
  div[data-testid="stMetricValue"] { color:#FACC15 !important; }
  @media (max-width: 640px) {
    .block-container {padding-left: .8rem; padding-right: .8rem;}
    h1 {font-size: 1.7rem !important;}
    h2 {font-size: 1.3rem !important;}
  }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="brand-header">
  <div class="brand-mark"><svg viewBox="0 0 64 64" width="42" height="42" aria-label="Football Lab logo"><circle cx="27" cy="29" r="20" fill="#101216" stroke="#FACC15" stroke-width="2.5"/><path d="M27 17l9 6-3 10H21l-4-9z" fill="#FACC15"/><path d="M17 24l-8-2m27 1 8-5m-9 15 8 8M21 33l-3 11m15-1-1 6" stroke="#F4F4F5" stroke-width="2" fill="none" stroke-linecap="round"/><path d="M39 51V38h6v13m4 0V29h6v22m4 0V20h5v31" fill="#FACC15" stroke="#FACC15" stroke-width="1"/><path d="M9 53Q28 61 53 53" fill="none" stroke="#FACC15" stroke-width="2.5" stroke-linecap="round"/></svg></div>
  <div>
    <div class="brand-title">FOOTBALL <span>LAB</span></div>
    <div class="brand-subtitle">LIVE ANALYTICS TERMINAL · GOLES · CÓRNERS · EMPATE</div>
  </div>
  <div class="brand-pill">● LIVE SCANNER</div>
</div>
""", unsafe_allow_html=True)
st.caption("Terminal de análisis deportivo · probabilidades exploratorias, no garantías de resultado")

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
    # Count attempted requests for transparent session-level API usage.
    st.session_state["api_request_count"] = st.session_state.get("api_request_count", 0) + 1
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
if "api_request_count" not in st.session_state:
    st.session_state.api_request_count = 0
if "last_scan_api_calls" not in st.session_state:
    st.session_state.last_scan_api_calls = 0
if "last_scan_stats_matches" not in st.session_state:
    st.session_state.last_scan_stats_matches = 0

left, right = st.columns([2, 1])
with left:
    st.subheader("Partidos en vivo")
with right:
    refresh = st.button("↻ Actualizar partidos", type="primary")

if refresh:
    try:
        with st.spinner("FOOTBALL LAB · Consultando partidos en vivo..."):
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
    st.markdown("### Tu centro de análisis")
    st.info("Pulsa «Actualizar partidos» para cargar los encuentros en vivo. Después podrás escanear goles, córners, empate y ambos equipos marcan.")
    st.markdown("""
    <div class="brand-header">
      <div>
        <div class="brand-title">DETECTA. <span>COMPARA.</span> ANALIZA.</div>
        <div class="brand-subtitle">Un panel único para explorar los mercados disponibles en los partidos en vivo.</div>
      </div>
    </div>
    """, unsafe_allow_html=True)
else:
    leagues = sorted({
        (f.get("league") or {}).get("name", "Liga")
        for f in fixtures
    })
    chosen_leagues = st.multiselect("🏆 Ligas", leagues, default=leagues)
    filtered = [
        f for f in fixtures
        if (f.get("league") or {}).get("name", "Liga") in chosen_leagues
    ]
    goal_results_now = st.session_state.get("goal_scan_results", [])
    corner_results_now = st.session_state.get("corner_scan_results", [])
    current_tips_count = sum(len(item[2]) for item in goal_results_now)
    st.markdown("### Resumen de sesión")
    metric_cols = st.columns(5)
    metric_cols[0].metric("Partidos en vivo", len(fixtures))
    metric_cols[1].metric("Ligas activas", len(chosen_leagues))
    metric_cols[2].metric("Tips de goles", current_tips_count)
    metric_cols[3].metric("Partidos córners", len(corner_results_now))
    metric_cols[4].metric("Solicitudes API (sesión)", st.session_state.api_request_count)
    st.caption(
        f"Último escaneo: {st.session_state.last_scan_api_calls} solicitudes API y "
        f"{st.session_state.last_scan_stats_matches} consultas de estadísticas intentadas. "
        "El contador incluye solicitudes intentadas en esta sesión."
    )
    stats_limit = st.slider(
        "Máximo de partidos a consultar con estadísticas detalladas por escaneo",
        min_value=5, max_value=50, value=20, step=5,
        help="Todos los partidos filtrados se evalúan con la información disponible. Este límite controla las consultas adicionales a fixtures/statistics para proteger tu cuota de API."
    )
    st.caption("El listado en vivo usa una solicitud. Cada partido al que se consultan estadísticas detalladas puede consumir otra; los demás se evalúan sin ese contexto en vivo.")
    if st.button("⚡ Escanear todos los partidos en vivo", type="primary"):
        scan_api_calls_start = st.session_state.api_request_count
        # Force fresh statistics for this scan; cap detailed-stat calls to protect API quota.
        st.session_state.stats_cache = {}
        st.session_state.goal_scan_results = []
        st.session_state.corner_scan_results = []
        st.markdown("""<div class="loading-brand"><div class="brand-mark"><svg viewBox="0 0 64 64" width="38" height="38"><circle cx="27" cy="29" r="20" fill="#101216" stroke="#FACC15" stroke-width="2.5"/><path d="M27 17l9 6-3 10H21l-4-9z" fill="#FACC15"/><path d="M17 24l-8-2m27 1 8-5m-9 15 8 8M21 33l-3 11m15-1-1 6" stroke="#F4F4F5" stroke-width="2" fill="none"/><path d="M39 51V38h6v13m4 0V29h6v22m4 0V20h5v31" fill="#FACC15"/></svg></div><div class="loading-orbit"></div><div><div class="loading-title">FOOTBALL LAB · ESCÁNER EN VIVO</div><div class="loading-subtitle">Evaluando mercados de goles y preparando revisión de córners…</div></div></div>""", unsafe_allow_html=True)
        # Fetch live statistics before estimating goals, so this same scan can
        # actually use the activity context instead of only using a cache from a
        # previous run. One request per fixture; subsequent sections reuse the cache.
        stats_fetch_progress = st.progress(0, text="Cargando estadísticas en vivo para el análisis de goles…")
        stats_fixtures = filtered[:stats_limit]
        stats_queries_attempted = 0
        for stats_idx, stats_fixture in enumerate(stats_fixtures):
            stats_fixture_id = (stats_fixture.get("fixture") or {}).get("id")
            if stats_fixture_id is not None:
                stats_cache_key = str(stats_fixture_id)
                if stats_cache_key not in st.session_state.stats_cache:
                    try:
                        stats_queries_attempted += 1
                        stats_payload = api_get("fixtures/statistics", {"fixture": stats_fixture_id})
                        st.session_state.stats_cache[stats_cache_key] = stats_payload.get("response", [])
                    except Exception as stats_exc:
                        st.session_state.stats_cache[stats_cache_key] = []
                        if "HTTP 429" in str(stats_exc):
                            st.warning("Se alcanzó el límite de consultas de la API durante la carga de estadísticas. El escaneo continuará con los datos disponibles y no repetirá las solicitudes fallidas en esta ronda.")
                            # Mark the remaining fixtures as unavailable for this round,
                            # preventing the corners pass from retrying after HTTP 429.
                            for remaining_fixture in filtered[stats_idx + 1:]:
                                remaining_id = (remaining_fixture.get("fixture") or {}).get("id")
                                if remaining_id is not None:
                                    st.session_state.stats_cache[str(remaining_id)] = []
                            break
            stats_fetch_progress.progress((stats_idx + 1) / max(1, len(stats_fixtures)))
        # Mark fixtures beyond the configured detail limit as unavailable for this
        # scan, so the corners pass does not issue hidden extra API requests.
        for skipped_fixture in filtered[len(stats_fixtures):]:
            skipped_id = (skipped_fixture.get("fixture") or {}).get("id")
            if skipped_id is not None:
                st.session_state.stats_cache[str(skipped_id)] = []
        stats_fetch_progress.empty()
        st.session_state.last_scan_stats_matches = stats_queries_attempted

        progress = st.progress(0)
        for idx, fixture in enumerate(filtered):
            league_data = fixture.get("league") or {}
            goals_data = fixture.get("goals") or {}
            elapsed_value = ((fixture.get("fixture") or {}).get("status") or {}).get("elapsed")
            estimate = estimate_live_goal_markets(
                country=league_data.get("country"),
                league_name=league_data.get("name"),
                score_home=goals_data.get("home") if isinstance(goals_data.get("home"), int) else None,
                score_away=goals_data.get("away") if isinstance(goals_data.get("away"), int) else None,
                elapsed_minute=elapsed_value if isinstance(elapsed_value, int) else None,
                data=MODEL_DATA,
                live_stats=summarize_live_context(
                    st.session_state.stats_cache.get(str((fixture.get("fixture") or {}).get("id")), []),
                    elapsed_value if isinstance(elapsed_value, int) else None,
                ),
            )
            tips = []
            if estimate.get("available"):
                candidates = [
                    (
                        f"Total final: {int(target)} goles o más (+{int(target) - estimate['current_total_goals']} desde ahora)",
                        probability,
                    )
                    for target, probability in estimate["over_total_goals"].items()
                ]
                candidates.append(("No habrá más goles", estimate["probability_no_more_goals"]))

                # Team-specific goal markets: e.g. local/visitor to finish with 2+ goals.
                home_name = ((fixture.get("teams") or {}).get("home") or {}).get("name", "Local")
                away_name = ((fixture.get("teams") or {}).get("away") or {}).get("name", "Visitante")
                for target, item in estimate.get("home_final_goals_at_least", {}).items():
                    if not item.get("already_settled"):
                        goal_word = "gol" if int(target) == 1 else "goles"
                        candidates.append((f"{home_name}: terminará con {target} {goal_word} o más", item["probability"]))
                for target, item in estimate.get("away_final_goals_at_least", {}).items():
                    if not item.get("already_settled"):
                        goal_word = "gol" if int(target) == 1 else "goles"
                        candidates.append((f"{away_name}: terminará con {target} {goal_word} o más", item["probability"]))

                candidates.append(("Empate final", estimate["draw_final"]))
                # If both teams have already scored, BTTS is settled, not a future tip.
                if not estimate.get("btts_already_settled"):
                    score_home_now = goals_data.get("home")
                    score_away_now = goals_data.get("away")
                    if score_home_now == 0 and score_away_now == 0:
                        btts_label = "Ambos equipos marcan (deben marcar ambos equipos)"
                    elif score_home_now == 0:
                        btts_label = f"Ambos equipos marcan (falta que marque {home_name})"
                    else:
                        btts_label = f"Ambos equipos marcan (falta que marque {away_name})"
                    candidates.append((btts_label, estimate["btts_final"]))
                # Only show candidate markets that pass the experimental screening threshold.
                # Otherwise the match is omitted from the opportunity list.
                tips = [(name, probability) for name, probability in candidates if probability >= 0.65]
            st.session_state.goal_scan_results.append((fixture, estimate, tips))
            progress.progress((idx + 1) / max(1, len(filtered)))
        corner_results = []
        # Prioritize fixtures with preliminary goal candidates; all statistics already fetched above are reused.
        candidate_ids = {
            (fixture.get("fixture") or {}).get("id")
            for fixture, estimate, tips in st.session_state.goal_scan_results
            if estimate.get("available") and tips
        }
        prioritized = sorted(
            filtered,
            key=lambda item: (
                (item.get("fixture") or {}).get("id") not in candidate_ids,
                -int((((item.get("fixture") or {}).get("status") or {}).get("elapsed")) or 0),
            ),
        )
        # Reuse cached statistics for all fixtures. No additional API calls are made here.
        corner_fixtures = prioritized
        corner_progress = st.progress(0)
        for idx, fixture in enumerate(corner_fixtures):
            fixture_id = (fixture.get("fixture") or {}).get("id")
            if fixture_id is None:
                corner_results.append({
                    "fixture": fixture,
                    "error": "El partido no tiene un ID de fixture válido; se omite la consulta de estadísticas.",
                })
                corner_progress.progress((idx + 1) / max(1, len(corner_fixtures)))
                continue
            try:
                cache_key = str(fixture_id)
                if cache_key not in st.session_state.stats_cache:
                    stats_payload = api_get("fixtures/statistics", {"fixture": fixture_id})
                    st.session_state.stats_cache[cache_key] = stats_payload.get("response", [])
                stats = st.session_state.stats_cache[cache_key]
                home_c = safe_stat(stats, "Corner Kicks", 0)
                away_c = safe_stat(stats, "Corner Kicks", 1)
                home_shots = safe_stat(stats, "Total Shots", 0)
                away_shots = safe_stat(stats, "Total Shots", 1)
                home_shots_on = safe_stat(stats, "Shots on Goal", 0)
                away_shots_on = safe_stat(stats, "Shots on Goal", 1)
                home_possession = safe_stat(stats, "Ball Possession", 0)
                away_possession = safe_stat(stats, "Ball Possession", 1)
                home_yellow = safe_stat(stats, "Yellow Cards", 0)
                away_yellow = safe_stat(stats, "Yellow Cards", 1)
                home_red = safe_stat(stats, "Red Cards", 0)
                away_red = safe_stat(stats, "Red Cards", 1)
                elapsed = ((fixture.get("fixture") or {}).get("status") or {}).get("elapsed")
                pace = corner_pace_per_90(home_c + away_c, elapsed) if isinstance(home_c, (int, float)) and isinstance(away_c, (int, float)) and isinstance(elapsed, int) else None
                corner_results.append({
                    "fixture": fixture,
                    "home_corners": home_c,
                    "away_corners": away_c,
                    "home_shots": home_shots,
                    "away_shots": away_shots,
                    "home_shots_on": home_shots_on,
                    "away_shots_on": away_shots_on,
                    "home_possession": home_possession,
                    "away_possession": away_possession,
                    "home_yellow": home_yellow,
                    "away_yellow": away_yellow,
                    "home_red": home_red,
                    "away_red": away_red,
                    "pace": pace,
                    "error": None,
                })
            except Exception as exc:
                corner_results.append({"fixture": fixture, "error": str(exc)})
                if "HTTP 429" in str(exc):
                    break
            corner_progress.progress((idx + 1) / max(1, len(corner_fixtures)))
        st.session_state.corner_scan_results = corner_results

        # Attach live context to the corresponding goal scan. Missing statistics remain missing.
        context_by_fixture = {}
        for item in corner_results:
            fixture_id = (item.get("fixture", {}).get("fixture") or {}).get("id")
            if not fixture_id or item.get("error"):
                continue
            cached_stats = st.session_state.stats_cache.get(str(fixture_id), [])
            elapsed = ((item.get("fixture", {}).get("fixture") or {}).get("status") or {}).get("elapsed")
            context_by_fixture[fixture_id] = summarize_live_context(cached_stats, elapsed)

        # Missing detailed stats must not erase candidates from the global scan.
        goal_results_with_context = []
        for fixture, estimate, tips in st.session_state.goal_scan_results:
            # Keep every evaluated fixture, including unavailable estimates and
            # matches with no qualifying tips, so the UI can explain omissions.
            fixture_id = ((fixture.get("fixture") or {}).get("id"))
            context = context_by_fixture.get(fixture_id)
            if context is None:
                context = {
                    "context_status": "pendiente de estadísticas detalladas",
                    "corners_total": None, "shots_total": None,
                    "shots_on_total": None, "red_cards_total": None,
                    "core_complete": False,
                    "elapsed": ((fixture.get("fixture") or {}).get("status") or {}).get("elapsed"),
                }
            goal_results_with_context.append((fixture, estimate, tips, context))
        st.session_state.goal_scan_results = goal_results_with_context

        # Session-local audit log: user can download it before leaving the app.
        signal_rows = st.session_state.get("signal_rows", [])
        for fixture, estimate, tips, context in goal_results_with_context:
            for market, probability in tips:
                signal_rows.append({
                    "recorded_at": datetime.now().isoformat(timespec="seconds"),
                    "fixture_id": (fixture.get("fixture") or {}).get("id"),
                    "league": (fixture.get("league") or {}).get("name"),
                    "home": ((fixture.get("teams") or {}).get("home") or {}).get("name"),
                    "away": ((fixture.get("teams") or {}).get("away") or {}).get("name"),
                    "minute": context.get("elapsed"),
                    "score_home": ((fixture.get("goals") or {}).get("home")),
                    "score_away": ((fixture.get("goals") or {}).get("away")),
                    "market": market,
                    "estimated_probability_exploratory": round(float(probability), 4),
                    "context_status": context.get("context_status"),
                    "corners_total": context.get("corners_total"),
                    "shots_total": context.get("shots_total"),
                    "shots_on_total": context.get("shots_on_total"),
                    "red_cards_total": context.get("red_cards_total"),
                    "final_score": "",
                    "outcome_verified": "",
                })
        st.session_state.signal_rows = signal_rows
        st.session_state.last_scan_api_calls = st.session_state.api_request_count - scan_api_calls_start

    tab_goals, tab_corners, tab_overview = st.tabs(["⚽ Goles y señales", "🚩 Córners", "📊 Estado y registro"])

    with tab_goals:
        goal_results = st.session_state.get("goal_scan_results", [])
        if goal_results:
            st.subheader("Tips preliminares del escáner")
            st.caption("Abre cada partido para comparar sus mercados. Las probabilidades son exploratorias y el filtro del 65% todavía no está validado.")
            search_matches = st.text_input("🔎 Buscar equipo o liga", placeholder="Ej. Roma, Premier League…", key="search_goal_matches").strip().casefold()
            tips_found = 0
            for fixture, estimate, tips, context in goal_results:
                if not estimate.get("available"):
                    continue
                if not tips:
                    continue
                searchable = f"{fixture_label(fixture)} {((fixture.get('teams') or {}).get('home') or {}).get('name', '')} {((fixture.get('teams') or {}).get('away') or {}).get('name', '')}".casefold()
                if search_matches and search_matches not in searchable:
                    continue
                tips_found += len(tips)
                with st.expander(f"⚽ {fixture_label(fixture)} · {len(tips)} mercados", expanded=False):
                    market_rows = [
                        {
                            "Mercado": market,
                            "Probabilidad exploratoria": round(probability * 100, 1),
                            "Filtro experimental": "Supera 65%" if probability >= 0.65 else "No supera 65%",
                        }
                        for market, probability in sorted(tips, key=lambda item: item[1], reverse=True)
                    ]
                    st.dataframe(
                        market_rows,
                        hide_index=True,
                        use_container_width=True,
                        column_config={
                            "Probabilidad exploratoria": st.column_config.ProgressColumn(
                                "Probabilidad exploratoria",
                                help="Estimación experimental; no equivale a una garantía de acierto.",
                                format="%.1f%%",
                                min_value=0,
                                max_value=100,
                            )
                        },
                    )
                    st.caption(f"Referencia histórica: {estimate['baseline_league']} ({estimate['baseline_matches']} partidos). Contexto en vivo: {context['context_status']}; córners {context.get('corners_total') if context.get('corners_total') is not None else 'N/D'}, tiros {context.get('shots_total') if context.get('shots_total') is not None else 'N/D'}, a puerta {context.get('shots_on_total') if context.get('shots_on_total') is not None else 'N/D'}, rojas {context.get('red_cards_total') if context.get('red_cards_total') is not None else 'N/D'}.")
                    st.caption(f"Ajuste del modelo: ×{estimate.get('live_activity_adjustment', 1.0):.3f} · {estimate.get('live_stats_status', 'sin ajuste')}. Es un ajuste exploratorio limitado, todavía no validado retrospectivamente.")
            if tips_found == 0:
                st.info("No hay oportunidades preliminares para mostrar en esta ronda; se omiten los partidos sin una estimación útil.")
            unavailable_items = [item for item in goal_results if not item[1].get("available")]
            unavailable = len(unavailable_items)
            no_tip_count = sum(1 for item in goal_results if item[1].get("available") and not item[2])
            if unavailable_items:
                reason_counts = {}
                for item in unavailable_items:
                    reason = item[1].get("reason") or "Motivo no especificado"
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
                with st.expander(f"📊 Resumen de causas de estimaciones no disponibles ({unavailable})"):
                    st.dataframe(
                        [{"Causa": reason, "Partidos": count} for reason, count in sorted(reason_counts.items(), key=lambda pair: pair[1], reverse=True)],
                        hide_index=True,
                        use_container_width=True,
                    )
            if no_tip_count:
                st.caption(
                    f"{no_tip_count} partidos sí tuvieron estimación, pero ningún mercado superó el 65%; "
                    "esto es diferente de datos incompletos o de una liga sin referencia histórica."
                )
            st.caption(
                f"Partidos evaluados: {len(goal_results)} · sin estimación disponible: {unavailable} "
                f"· con estimación pero sin mercados que superen el filtro: {no_tip_count}."
            )
            if unavailable_items:
                with st.expander(f"ℹ️ ¿Por qué no se estiman {unavailable} partidos?"):
                    unavailable_rows = [
                        {
                            "Partido": fixture_label(item[0]),
                            "Motivo": item[1].get("reason") or "Motivo no especificado",
                        }
                        for item in unavailable_items
                    ]
                    st.dataframe(
                        unavailable_rows,
                        hide_index=True,
                        use_container_width=True,
                    )
                    st.caption(
                        "Estos partidos no se convierten en tips: falta una referencia histórica compatible, "
                        "la muestra de esa liga es pequeña o faltan datos básicos del encuentro."
                    )
    
    
    with tab_corners:
        corner_results = st.session_state.get("corner_scan_results", [])
        if corner_results:
            st.subheader("Córners · revisión en vivo")
            st.caption("Se consulta una muestra priorizada para controlar llamadas a la API. La muestra no limita la búsqueda global de señales de goles; los datos incompletos se muestran como no disponibles, nunca como cero.")
            for item in corner_results:
                st.markdown(f"**{fixture_label(item['fixture'])}**")
                if item.get("error"):
                    st.caption("Estadísticas de córners no disponibles en la API para este partido.")
                elif item.get("home_corners") is None or item.get("away_corners") is None:
                    st.caption("Sin córners completos para este partido; no se interpreta el dato ausente como cero.")
                else:
                    st.caption(f"Córners: local {item['home_corners']} · visitante {item['away_corners']} · total {item['home_corners'] + item['away_corners']}.")
                    if item.get("pace") is not None:
                        st.caption(f"Ritmo de córners extrapolado: {item['pace']:.1f}/90 min (indicador descriptivo, no probabilidad validada).")
                        elapsed_now = ((item.get("fixture") or {}).get("fixture") or {}).get("status") or {}
                        minute_now = elapsed_now.get("elapsed")
                        total_corners_now = item["home_corners"] + item["away_corners"]
                        if isinstance(minute_now, int) and minute_now >= 10:
                            projected_additional = item["pace"] * max(0, 90 - min(minute_now, 90)) / 90
                            projected_final = total_corners_now + projected_additional
                            st.info(
                                f"Proyección orientativa si continúa el ritmo actual: "
                                f"{projected_final:.1f} córners totales al final; "
                                f"aprox. {projected_additional:.1f} córners adicionales. "
                                "No usa todavía promedios históricos de córners por liga/equipo."
                            )
                            if minute_now <= 20 or total_corners_now <= 2:
                                st.caption(
                                    "Confianza muy baja: hay pocos minutos y/o córners observados. "
                                    "Es una extrapolación lineal, no un tip confirmado."
                                )
                        # Exploratory corner-market probabilities from a Poisson model whose
                        # remaining-corner rate is the observed live pace. This is not calibrated
                        # and must be labelled low-confidence early in the match.
                        if isinstance(minute_now, int) and minute_now < 90:
                            remaining_corner_rate = max(0.0, item["pace"] * (90 - min(minute_now, 90)) / 90)
                            corner_market_rows = []
                            for line in (6.5, 7.5, 8.5, 9.5, 10.5, 11.5):
                                target_total = int(line) + 1
                                if total_corners_now >= target_total:
                                    corner_market_rows.append({
                                        "Mercado": f"Más de {line:.1f} córners",
                                        "Prob. exploratoria": "Ya superado",
                                        "Estado": "No es una oportunidad futura",
                                    })
                                else:
                                    corners_needed = target_total - total_corners_now
                                    probability = poisson_at_least(remaining_corner_rate, corners_needed)
                                    corner_market_rows.append({
                                        "Mercado": f"Más de {line:.1f} córners",
                                        "Prob. exploratoria": round(probability * 100, 1),
                                        "Estado": "Candidato experimental" if probability >= 0.65 else "Por debajo del filtro (65%)",
                                    })
                            st.markdown("**Mercados de córners · probabilidad exploratoria**")
                            st.dataframe(
                                corner_market_rows,
                                hide_index=True,
                                use_container_width=True,
                                column_config={
                                    "Prob. exploratoria": st.column_config.ProgressColumn(
                                        "Prob. exploratoria",
                                        help="Modelo preliminar basado en el ritmo observado; no está calibrado.",
                                        format="%.1f%%",
                                        min_value=0,
                                        max_value=100,
                                    )
                                },
                            )
                            if minute_now <= 20 or total_corners_now <= 2:
                                st.caption(
                                    "Probabilidades de muy baja confianza: se basan en el ritmo observado y una distribución Poisson simplificada. "
                                    "Todavía no incorporan promedios históricos fiables por liga/equipo ni están validadas retrospectivamente."
                                )
                        if qualifies_as_corner_candidate(
                            minute=minute_now,
                            total_corners=total_corners_now,
                            pace_per_90=item.get("pace"),
                            home_shots=item.get("home_shots"),
                            away_shots=item.get("away_shots"),
                        ):
                            st.warning("CANDIDATO EXPERIMENTAL · ritmo de córners elevado y actividad de tiros. Revisar mercados de córners restantes y cuota disponible; no es una probabilidad validada ni una apuesta automática.")
                    st.caption(f"Tiros totales: local {item.get('home_shots')} · visitante {item.get('away_shots')} | a puerta: local {item.get('home_shots_on')} · visitante {item.get('away_shots_on')}.")
                    st.caption(f"Posesión: local {item.get('home_possession') or 'N/D'} · visitante {item.get('away_possession') or 'N/D'}.")
                    st.caption(f"Tarjetas amarillas: local {item.get('home_yellow') if item.get('home_yellow') is not None else 'N/D'} · visitante {item.get('away_yellow') if item.get('away_yellow') is not None else 'N/D'} | rojas: local {item.get('home_red') if item.get('home_red') is not None else 'N/D'} · visitante {item.get('away_red') if item.get('away_red') is not None else 'N/D'}.")
                    st.caption("Estas estadísticas describen el partido; aún no ajustan automáticamente las probabilidades porque el modelo debe calibrarse antes de usarlas como factores predictivos.")
                st.divider()
    
    
    with tab_overview:
        st.subheader("Estado de los mercados")
        market_status = [
            ("Córners", "Se muestran córners observados y proyecciones exploratorias; falta historial fiable por liga/equipo para calibrarlas."),
            ("Goles", "Probabilidades exploratorias basadas en medias históricas de liga; aún no calibradas."),
            ("Empate", "Estimación exploratoria con un modelo Poisson simplificado; requiere validación retrospectiva."),
            ("Ambos equipos marcan", "Estimación condicionada al marcador y a los goles restantes; requiere validación retrospectiva."),
        ]
        market_cols = st.columns(2)
        for col, (market, status_text) in zip(market_cols * 2, market_status):
            with col:
                st.markdown(f"**{market}**")
                st.caption(status_text)
        st.caption("Las probabilidades no están validadas. No hay cuotas verificadas de RushBet ni EV calculado todavía; no se ejecutan apuestas automáticamente.")
        signal_rows = st.session_state.get("signal_rows", [])
        log_cols = st.columns(2)
        log_cols[0].metric("Señales registradas", len(signal_rows))
        log_cols[1].metric("Resultados por verificar", sum(1 for row in signal_rows if not row.get("outcome_verified")))
        if signal_rows:
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=list(signal_rows[0].keys()))
            writer.writeheader()
            writer.writerows(signal_rows)
            st.download_button(
                "⬇️ Descargar registro de señales (CSV)",
                data=buffer.getvalue().encode("utf-8-sig"),
                file_name="registro_senales_escanner.csv",
                mime="text/csv",
                help="Descarga las señales de esta sesión para conservarlas y verificar los resultados después."
            )
            st.caption("El registro pertenece a la sesión actual. Los resultados se mantienen sin verificar hasta disponer de una comprobación real.")

    if not goal_results and not corner_results:
        st.info("Pulsa «Escanear todos los partidos en vivo» para generar el primer informe.")
    elif not goal_results:
        st.info("En esta ronda no hubo señales de goles que superaran el umbral experimental del 65%. Esto no significa que todos los partidos carezcan de datos ni que no existan candidatos de córners.")
        st.caption("El modelo necesita una referencia histórica compatible para estimar goles. Si no la encuentra, la señal se marca como no disponible; las estadísticas en vivo no sustituyen por sí solas una base histórica fiable.")


