import csv
import html
import io
import json
import os
from datetime import datetime
from typing import Any

import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from models.live_context import qualifies_as_corner_candidate, summarize_live_context
from models.backtest import evaluate_binary_predictions
from models.automatic_history import build_automatic_history
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
  .signal-card { margin:.65rem 0 1rem; padding:1.15rem 1.2rem; border-radius:18px; border:1px solid #FACC15; background:radial-gradient(circle at 92% 8%,rgba(250,204,21,.18),transparent 34%),linear-gradient(135deg,#242014 0%,#171B21 58%,#111419 100%); box-shadow:0 8px 28px rgba(0,0,0,.24); }
  .signal-kicker { color:#FACC15; font-size:.76rem; font-weight:850; letter-spacing:1.4px; text-transform:uppercase; }
  .signal-title { color:#F4F4F5; font-size:1.12rem; font-weight:750; margin-top:.35rem; }
  .signal-pick { color:#FACC15; font-size:clamp(1.8rem,5vw,2.65rem); font-weight:900; line-height:1.15; margin:.45rem 0; }
  .signal-meta { color:#D4D4D8; font-size:.82rem; margin-top:.4rem; }
  .live-match-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(270px,1fr)); gap:10px; margin:.5rem 0 1.1rem; }
  .live-match-card { background:linear-gradient(135deg,#171B21,#101216); border:1px solid #343A44; border-radius:13px; padding:10px 12px; }
  .live-match-league { color:#A1A1AA; font-size:.72rem; margin-bottom:8px; font-weight:700; }
  .live-match-league span { color:#FACC15; }
  .live-match-teams { display:grid; grid-template-columns:minmax(0,1fr) auto minmax(0,1fr); align-items:center; gap:8px; }
  .live-match-team { min-width:0; display:flex; align-items:center; gap:7px; color:#F4F4F5; font-size:.82rem; font-weight:700; }
  .live-match-team span:last-child { overflow-wrap:anywhere; }
  .live-match-team.away-team { justify-content:flex-end; text-align:right; }
  .team-badge { width:25px; height:25px; object-fit:contain; flex:0 0 25px; }
  .team-badge-fallback { width:25px; height:25px; display:inline-flex; align-items:center; justify-content:center; flex:0 0 25px; background:#242014; border-radius:50%; }
  .live-match-score { white-space:nowrap; background:#0B0D10; border:1px solid #393326; border-radius:8px; padding:5px 8px; color:#FACC15; font-weight:900; font-size:1rem; }
  .fixture-hero { background:linear-gradient(135deg,#171B21,#0D1014); border:1px solid #393326; border-radius:14px; padding:12px 13px; margin:.55rem 0 .8rem; box-shadow:0 5px 16px rgba(0,0,0,.18); }
  .fixture-hero-top { display:flex; justify-content:space-between; align-items:center; gap:8px; color:#A1A1AA; font-size:.72rem; margin-bottom:12px; }
  .fixture-clock { display:inline-flex; align-items:center; gap:5px; padding:4px 8px; border-radius:999px; border:1px solid #51451E; background:#242014; color:#FACC15; font-weight:800; white-space:nowrap; }
  .fixture-hero-teams { display:grid; grid-template-columns:minmax(0,1fr) auto minmax(0,1fr); gap:9px; align-items:center; }
  .fixture-hero-team { display:flex; flex-direction:column; align-items:center; justify-content:center; gap:6px; min-width:0; text-align:center; color:#F4F4F5; font-weight:750; font-size:.82rem; }
  .fixture-hero-team img { width:38px; height:38px; object-fit:contain; }
  .fixture-hero-team span { overflow-wrap:anywhere; }
  .fixture-hero-score { color:#FACC15; background:#080A0D; border:1px solid #3B3525; border-radius:10px; padding:7px 12px; font-size:1.55rem; font-weight:950; white-space:nowrap; letter-spacing:.5px; }
  .fixture-hero-league { color:#A1A1AA; font-size:.7rem; text-align:center; margin-top:10px; }
  .fixture-hero-fallback { font-size:30px; line-height:38px; }
  @media (max-width: 420px) { .fixture-hero-team {font-size:.72rem;} .fixture-hero-team img {width:31px;height:31px;} .fixture-hero-score {font-size:1.25rem;padding:6px 9px;} }

  .history-table { width:100%; border-collapse:separate; border-spacing:0; border:1px solid #4A4024; border-radius:12px; overflow:hidden; font-size:.9rem; margin:.5rem 0 1rem; }
  .history-table th { background:#FACC15; color:#151515; text-align:left; padding:.72rem .65rem; font-weight:850; }
  .history-table td { background:#15191F; color:#F4F4F5; padding:.68rem .65rem; border-top:1px solid #34302A; }
  .history-table tr:nth-child(even) td { background:#1B2027; }
  .history-table td:nth-child(2), .history-table td:nth-child(3), .history-table th:nth-child(2), .history-table th:nth-child(3) { text-align:center; }
  @media (max-width: 640px) { .history-table {font-size:.76rem;} .history-table th,.history-table td {padding:.55rem .4rem;} }
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

def fixture_card_html(fixture: dict[str, Any]) -> str:
    """Compact live match card using the team badge URLs supplied by API-Football."""
    teams = fixture.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    goals = fixture.get("goals") or {}
    status = (fixture.get("fixture") or {}).get("status") or {}
    league = (fixture.get("league") or {}).get("name") or "Liga"
    minute = status.get("elapsed")
    minute_label = f"{minute}'" if minute is not None else str(status.get("short") or "EN VIVO")
    home_name = html.escape(str(home.get("name") or "Local"))
    away_name = html.escape(str(away.get("name") or "Visitante"))
    league_name = html.escape(str(league))
    home_logo = html.escape(str(home.get("logo") or ""), quote=True)
    away_logo = html.escape(str(away.get("logo") or ""), quote=True)
    home_score = goals.get("home") if goals.get("home") is not None else "-"
    away_score = goals.get("away") if goals.get("away") is not None else "-"
    home_badge = f'<img class="team-badge" src="{home_logo}" alt="" onerror="this.style.display=\'none\'">' if home_logo else '<span class="team-badge-fallback">⚽</span>'
    away_badge = f'<img class="team-badge" src="{away_logo}" alt="" onerror="this.style.display=\'none\'">' if away_logo else '<span class="team-badge-fallback">⚽</span>'
    return (
        '<div class="live-match-card">'
        f'<div class="live-match-league">{league_name} <span>· {html.escape(minute_label)}</span></div>'
        '<div class="live-match-teams">'
        f'<div class="live-match-team">{home_badge}<span>{home_name}</span></div>'
        f'<div class="live-match-score">{home_score} – {away_score}</div>'
        f'<div class="live-match-team away-team">{away_badge}<span>{away_name}</span></div>'
        '</div></div>'
    )

def fixture_hero_html(
    fixture: dict[str, Any],
    mode: str = "goals",
    home_corners: int | None = None,
    away_corners: int | None = None,
) -> str:
    """Larger team/score/minute header; show goals or current corners by section."""
    teams = fixture.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    goals = fixture.get("goals") or {}
    fixture_data = fixture.get("fixture") or {}
    status = fixture_data.get("status") or {}
    league = (fixture.get("league") or {}).get("name") or "Liga"
    minute = status.get("elapsed")
    minute_label = f"{minute}′" if minute is not None else str(status.get("short") or "EN VIVO")
    home_name = html.escape(str(home.get("name") or "Local"))
    away_name = html.escape(str(away.get("name") or "Visitante"))
    home_logo = html.escape(str(home.get("logo") or ""), quote=True)
    away_logo = html.escape(str(away.get("logo") or ""), quote=True)
    if mode == "corners":
        home_score = home_corners if home_corners is not None else "–"
        away_score = away_corners if away_corners is not None else "–"
        header_label = "🚩 CÓRNERS ACTUALES"
    else:
        home_score = goals.get("home") if goals.get("home") is not None else "–"
        away_score = goals.get("away") if goals.get("away") is not None else "–"
        header_label = "⚽ PARTIDO EN ANÁLISIS"
    home_badge = f'<img src="{home_logo}" alt="" onerror="this.style.display=\'none\'">' if home_logo else '<div class="fixture-hero-fallback">⚽</div>'
    away_badge = f'<img src="{away_logo}" alt="" onerror="this.style.display=\'none\'">' if away_logo else '<div class="fixture-hero-fallback">⚽</div>'
    return (
        '<div class="fixture-hero">'
        f'<div class="fixture-hero-top"><span>{header_label}</span><span class="fixture-clock">◷ {html.escape(minute_label)}</span></div>'
        '<div class="fixture-hero-teams">'
        f'<div class="fixture-hero-team">{home_badge}<span>{home_name}</span></div>'
        f'<div class="fixture-hero-score">{home_score} – {away_score}</div>'
        f'<div class="fixture-hero-team">{away_badge}<span>{away_name}</span></div>'
        '</div>'
        f'<div class="fixture-hero-league">{html.escape(str(league))}</div>'
        '</div>'
    )

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
if "auto_refresh_enabled" not in st.session_state:
    st.session_state.auto_refresh_enabled = True
if "sound_muted" not in st.session_state:
    st.session_state.sound_muted = False
if "score_snapshot" not in st.session_state:
    st.session_state.score_snapshot = {}
if "notification_events" not in st.session_state:
    st.session_state.notification_events = []
if "last_auto_refresh_error" not in st.session_state:
    st.session_state.last_auto_refresh_error = ""

controls = st.columns([1.4, 1, 1])
with controls[0]:
    st.session_state.auto_refresh_enabled = st.toggle(
        "Actualización automática (60 s)",
        value=st.session_state.auto_refresh_enabled,
        help="Actualiza los marcadores cada 60 segundos mientras esta página esté abierta."
    )
with controls[1]:
    if st.button("🔕 Silenciar sonido" if not st.session_state.sound_muted else "🔔 Activar sonido"):
        st.session_state.sound_muted = not st.session_state.sound_muted
with controls[2]:
    refresh = st.button("↻ Actualizar ahora", type="primary")

auto_tick = None
if st.session_state.auto_refresh_enabled:
    auto_tick = st_autorefresh(interval=60_000, key="live_fixture_refresh_60s")

should_refresh = refresh or (
    auto_tick is not None
    and auto_tick > 0
    and auto_tick != st.session_state.get("last_auto_tick_seen")
)
if auto_tick is not None:
    st.session_state.last_auto_tick_seen = auto_tick

if should_refresh:
    try:
        data = api_get("fixtures", {"live": "all"})
        new_fixtures = data.get("response", [])
        old_snapshot = st.session_state.score_snapshot
        current_snapshot = {}
        new_events = []
        for match in new_fixtures:
            fixture_data = match.get("fixture") or {}
            fixture_id = str(fixture_data.get("id") or "")
            if not fixture_id:
                continue
            goals_data = match.get("goals") or {}
            score = (goals_data.get("home"), goals_data.get("away"))
            current_snapshot[fixture_id] = score
            previous_score = old_snapshot.get(fixture_id)
            if previous_score is not None and score != previous_score and all(isinstance(v, int) for v in score):
                home = (match.get("teams") or {}).get("home") or {}
                away = (match.get("teams") or {}).get("away") or {}
                old_total = sum(v for v in previous_score if isinstance(v, int))
                if sum(score) > old_total:
                    new_events.append({
                        "id": f"{fixture_id}:{score[0]}-{score[1]}",
                        "title": "⚽ ¡GOOOOL!",
                        "message": f"{home.get('name', 'Local')} {score[0]} - {score[1]} {away.get('name', 'Visitante')}"
                    })
        st.session_state.score_snapshot = current_snapshot
        st.session_state.live_fixtures = new_fixtures
        st.session_state.last_refresh = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.session_state.last_auto_refresh_error = ""
        seen_ids = {event.get("id") for event in st.session_state.notification_events}
        for event in new_events:
            if event["id"] not in seen_ids:
                st.session_state.notification_events.append(event)
                st.toast(f"{event['title']} · {event['message']}", icon="⚽")
        st.session_state.notification_events = st.session_state.notification_events[-5:]
    except Exception as exc:
        st.session_state.last_auto_refresh_error = str(exc)

if st.session_state.last_refresh:
    st.caption(f"Última actualización: {st.session_state.last_refresh} · intervalo: 60 segundos")
if st.session_state.last_auto_refresh_error:
    st.warning(f"No se pudo actualizar el listado en vivo: {st.session_state.last_auto_refresh_error}")

recent_events = st.session_state.notification_events[-3:]
events_json = json.dumps(recent_events, ensure_ascii=False).replace("</", "<\\/")
muted_js = "true" if st.session_state.sound_muted else "false"
st.components.v1.html(
    f"""
    <div id="scanner-notices" style="font-family:system-ui;color:#f4f4f5"></div>
    <script>
    const events = {events_json};
    const muted = {muted_js};
    const root = document.getElementById('scanner-notices');
    const seenKey = 'football-lab-seen-events';
    let seen = [];
    try {{ seen = JSON.parse(localStorage.getItem(seenKey) || '[]'); }} catch (e) {{}}
    const fresh = events.filter(e => !seen.includes(e.id));
    if (fresh.length) {{
      fresh.forEach(e => {{
        const card = document.createElement('div');
        card.style.cssText = 'margin:8px 0;padding:12px 14px;border-radius:12px;background:#242014;border:1px solid #FACC15;box-shadow:0 6px 20px #0008';
        card.innerHTML = '<b style="color:#FACC15">' + e.title + '</b><div style="margin-top:4px">' + e.message + '</div>';
        root.appendChild(card);
        setTimeout(() => card.remove(), 9000);
      }});
      seen = [...seen, ...fresh.map(e => e.id)].slice(-30);
      try {{ localStorage.setItem(seenKey, JSON.stringify(seen)); }} catch (e) {{}}
      if (!muted) {{
        try {{
          const AudioCtx = window.AudioContext || window.webkitAudioContext;
          if (AudioCtx) {{
            const ctx = new AudioCtx();
            [880, 1175].forEach((freq, i) => {{
              const osc = ctx.createOscillator(), gain = ctx.createGain(), t = ctx.currentTime + i * 0.14;
              osc.type = 'sine'; osc.frequency.value = freq;
              gain.gain.setValueAtTime(0.0001, t);
              gain.gain.exponentialRampToValueAtTime(0.12, t + 0.025);
              gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.18);
              osc.connect(gain); gain.connect(ctx.destination); osc.start(t); osc.stop(t + 0.2);
            }});
            setTimeout(() => ctx.close(), 700);
          }}
        }} catch (e) {{}}
      }}
    }}
    </script>
    """,
    height=150,
    scrolling=False,
)

left, right = st.columns([2, 1])
with left:
    st.subheader("Partidos en vivo")
with right:
    st.caption("Los goles se detectan comparando marcadores entre actualizaciones.")

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
    st.markdown("### Marcadores en vivo")
    if filtered:
        match_cards_html = '<div class="live-match-grid">' + "".join(fixture_card_html(match) for match in filtered) + "</div>"
        st.markdown(match_cards_html, unsafe_allow_html=True)
    else:
        st.info("No hay partidos para las ligas seleccionadas.")

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

        # Compare current scores with the previous completed scan without extra API calls.
        previous_scores = st.session_state.get("previous_scan_scores", {})
        current_scores = {}
        progress = st.progress(0)
        for idx, fixture in enumerate(filtered):
            league_data = fixture.get("league") or {}
            goals_data = fixture.get("goals") or {}
            elapsed_value = ((fixture.get("fixture") or {}).get("status") or {}).get("elapsed")
            fixture_id_for_score = (fixture.get("fixture") or {}).get("id")
            score_home_now = goals_data.get("home") if isinstance(goals_data.get("home"), int) else None
            score_away_now = goals_data.get("away") if isinstance(goals_data.get("away"), int) else None
            current_scores[str(fixture_id_for_score)] = {
                "home": score_home_now, "away": score_away_now, "minute": elapsed_value
            }
            previous = previous_scores.get(str(fixture_id_for_score), {})
            recent_goals = 0
            previous_minute = previous.get("minute")
            minute_gap = elapsed_value - previous_minute if isinstance(elapsed_value, int) and isinstance(previous_minute, int) else None
            if minute_gap is not None and 0 < minute_gap <= 10:
                prev_home, prev_away = previous.get("home"), previous.get("away")
                if isinstance(prev_home, int) and isinstance(prev_away, int) and isinstance(score_home_now, int) and isinstance(score_away_now, int):
                    recent_goals = max(0, score_home_now - prev_home) + max(0, score_away_now - prev_away)
            live_context = summarize_live_context(
                st.session_state.stats_cache.get(str((fixture.get("fixture") or {}).get("id")), []),
                elapsed_value if isinstance(elapsed_value, int) else None,
            )
            try:
                estimate = estimate_live_goal_markets(
                    country=league_data.get("country"),
                    league_name=league_data.get("name"),
                    score_home=score_home_now,
                    score_away=score_away_now,
                    elapsed_minute=elapsed_value if isinstance(elapsed_value, int) else None,
                    recent_goals=recent_goals,
                    minutes_since_previous_scan=minute_gap,
                    data=MODEL_DATA,
                    live_stats=live_context,
                )
            except TypeError as model_exc:
                # Compatibility fallback if Cloud briefly serves an older model module
                # than app.py. Keep the scan running and clearly disclose that recent-goal
                # adjustment was unavailable instead of crashing the whole app.
                if "recent_goals" not in str(model_exc) and "minutes_since_previous_scan" not in str(model_exc):
                    raise
                estimate = estimate_live_goal_markets(
                    country=league_data.get("country"),
                    league_name=league_data.get("name"),
                    score_home=score_home_now,
                    score_away=score_away_now,
                    elapsed_minute=elapsed_value if isinstance(elapsed_value, int) else None,
                    data=MODEL_DATA,
                    live_stats=live_context,
                )
                estimate["recent_goal_adjustment"] = 1.0
                estimate["recent_goals_observed"] = 0
                estimate["compatibility_fallback"] = True
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
                for line, probability in estimate.get("under_total_goals", {}).items():
                    # Avoid presenting a line as a live under when the current score
                    # has already exceeded that line.
                    if estimate["current_total_goals"] <= int(float(line)):
                        candidates.append((f"Menos de {line} goles totales", probability))

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
                # Slightly wider screening to surface more candidate markets without forcing a tip.
                # These are model probabilities, not validated betting edges.
                tips = [(name, probability) for name, probability in candidates if probability >= 0.60]
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
        # Automatic historical context, cached by team and fixture. Limit historical
        # statistics calls per scan so this does not silently consume the whole API quota.
        history_calls_before = st.session_state.api_request_count
        history_cache = st.session_state.setdefault("automatic_history_cache", {})
        history_cache["_automatic_history_stats_calls"] = 0
        history_cache["_automatic_history_team_fixture_calls"] = 0
        for corner_item in corner_results:
            if corner_item.get("error"):
                continue
            try:
                used_history_stats = int(history_cache.get("_automatic_history_stats_calls", 0))
                corner_item["automatic_history"] = build_automatic_history(
                    corner_item["fixture"],
                    api_get=api_get,
                    cache=history_cache,
                    stats_budget=max(0, 8 - used_history_stats),
                )
            except Exception as history_exc:
                corner_item["automatic_history"] = {
                    "available": False,
                    "note": f"Historial automático no disponible: {history_exc}",
                }
        st.session_state.last_scan_history_api_calls = st.session_state.api_request_count - history_calls_before
        st.session_state.last_scan_api_calls = st.session_state.api_request_count - scan_api_calls_start
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
        st.session_state.previous_scan_scores = current_scores

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
                    "outcome": "",
                    "outcome_verified": "",
                })
        st.session_state.signal_rows = signal_rows
        st.session_state.last_scan_api_calls = st.session_state.api_request_count - scan_api_calls_start

    tab_goals, tab_corners, tab_overview = st.tabs(["⚽ Goles y señales", "🚩 Córners", "📊 Estado y registro"])

    with tab_goals:
        st.markdown("### Señales automáticas de goles")
        st.caption("El escáner combina las referencias disponibles de liga y el contexto en vivo. El historial reciente se consulta automáticamente durante el escaneo; no necesitas cargar archivos históricos.")
        goal_results = st.session_state.get("goal_scan_results", [])
        if goal_results:
            st.subheader("Tips preliminares del escáner")
            st.caption("Probabilidades exploratorias; se muestran candidatos desde el 60 %, pero no están calibradas ni garantizan resultados.")
            # Show the automatic home/away goal averages alongside goal-market analysis.
            corner_history_by_id = {
                (item.get("fixture", {}).get("fixture") or {}).get("id"): item.get("automatic_history") or {}
                for item in st.session_state.get("corner_scan_results", [])
            }
            search_matches = st.text_input("🔎 Buscar equipo o liga", placeholder="Ej. Roma, Premier League…", key="search_goal_matches").strip().casefold()
            tips_found = 0
            for fixture, estimate, tips, context in goal_results:
                fixture_id = (fixture.get("fixture") or {}).get("id")
                history = corner_history_by_id.get(fixture_id, {})
                if history.get("available"):
                    st.markdown(fixture_hero_html(fixture), unsafe_allow_html=True)
                    st.markdown("**📊 Promedios de goles**")
                    goal_history_rows = [
                        {"Indicador": "Goles a favor del local en casa", "Promedio": history.get("home_goals_for") if history.get("home_goals_for") is not None else "N/D", "Muestra": history.get("home_goal_sample", 0)},
                        {"Indicador": "Goles concedidos por el local en casa", "Promedio": history.get("home_goals_against") if history.get("home_goals_against") is not None else "N/D", "Muestra": history.get("home_goal_sample", 0)},
                        {"Indicador": "Goles a favor del visitante fuera", "Promedio": history.get("away_goals_for") if history.get("away_goals_for") is not None else "N/D", "Muestra": history.get("away_goal_sample", 0)},
                        {"Indicador": "Goles concedidos por el visitante fuera", "Promedio": history.get("away_goals_against") if history.get("away_goals_against") is not None else "N/D", "Muestra": history.get("away_goal_sample", 0)},
                    ]
                    goal_table_html = '<table class="history-table"><thead><tr><th>Indicador</th><th>Promedio</th><th>Muestra</th></tr></thead><tbody>'
                    for goal_row in goal_history_rows:
                        avg = goal_row["Promedio"]
                        avg_text = f"{avg:.2f}".rstrip("0").rstrip(".") if isinstance(avg, (int, float)) else str(avg)
                        goal_table_html += f"<tr><td>{goal_row['Indicador']}</td><td>{avg_text}</td><td>{goal_row['Muestra']}</td></tr>"
                    goal_table_html += "</tbody></table>"
                    st.markdown(goal_table_html, unsafe_allow_html=True)
                    st.caption("Promedios históricos automáticos de localía; la muestra puede variar según los datos disponibles de la API.")
                if not estimate.get("available") or not tips:
                    continue
                if search_matches and search_matches not in fixture_label(fixture).casefold():
                    continue
                tips_found += len(tips)
                with st.expander(f"⚽ {fixture_label(fixture)} · {len(tips)} mercados", expanded=False):
                    st.markdown(fixture_hero_html(fixture), unsafe_allow_html=True)
                    rows = [{"Mercado": name, "Probabilidad exploratoria": round(prob * 100, 1)} for name, prob in sorted(tips, key=lambda pair: pair[1], reverse=True)]
                    st.dataframe(rows, hide_index=True, use_container_width=True)
                    st.caption(f"Referencia de liga: {estimate['baseline_league']} ({estimate['baseline_matches']} partidos). Contexto en vivo: {context['context_status']}.")
                    st.caption("Modelo exploratorio; requiere validación retrospectiva antes de tratarlo como señal fiable.")
            if tips_found == 0:
                st.info("No hay oportunidades que superen el filtro en esta ronda.")
        else:
            st.info("Pulsa «Escanear todos los partidos en vivo» para calcular las señales.")

    with tab_corners:
        st.markdown("### Córners · historial automático y ritmo en vivo")
        st.caption("El bot consulta partidos anteriores por API, distingue local/visitante y cachea los resultados. No tienes que subir CSV.")
        corner_results = st.session_state.get("corner_scan_results", [])
        if corner_results:
            for item in corner_results:
                st.markdown(
                    fixture_hero_html(
                        item["fixture"],
                        mode="corners",
                        home_corners=item.get("home_corners"),
                        away_corners=item.get("away_corners"),
                    ),
                    unsafe_allow_html=True,
                )
                if item.get("error"):
                    st.caption("Las estadísticas en vivo no están disponibles para este partido.")
                else:
                    if item.get("home_corners") is not None and item.get("away_corners") is not None:
                        st.caption(f"Córners actuales: local {item['home_corners']} · visitante {item['away_corners']} · total {item['home_corners'] + item['away_corners']}.")
                    history = item.get("automatic_history") or {}
                    if history.get("available"):
                        history_rows = [
                            {"Indicador": "Córners a favor del local en casa", "Promedio": history.get("home_corners_for") if history.get("home_corners_for") is not None else "N/D", "Muestra": history.get("home_corner_sample", 0)},
                            {"Indicador": "Córners concedidos por el local en casa", "Promedio": history.get("home_corners_against") if history.get("home_corners_against") is not None else "N/D", "Muestra": history.get("home_corner_sample", 0)},
                            {"Indicador": "Córners a favor del visitante fuera", "Promedio": history.get("away_corners_for") if history.get("away_corners_for") is not None else "N/D", "Muestra": history.get("away_corner_sample", 0)},
                            {"Indicador": "Córners concedidos por el visitante fuera", "Promedio": history.get("away_corners_against") if history.get("away_corners_against") is not None else "N/D", "Muestra": history.get("away_corner_sample", 0)},
                        ]
                        table_html = '<table class="history-table"><thead><tr><th>Indicador</th><th>Promedio</th><th>Muestra</th></tr></thead><tbody>'
                        for history_row in history_rows:
                            average = history_row["Promedio"]
                            average_text = f"{average:.2f}".rstrip("0").rstrip(".") if isinstance(average, (int, float)) else str(average)
                            table_html += (
                                "<tr>"
                                f"<td>{history_row['Indicador']}</td>"
                                f"<td>{average_text}</td>"
                                f"<td>{history_row['Muestra']}</td>"
                                "</tr>"
                            )
                        table_html += "</tbody></table>"
                        st.markdown(table_html, unsafe_allow_html=True)
                        st.caption(history.get("note", "Historial automático de partidos anteriores."))
                    else:
                        st.caption(history.get("note", "Historial automático no disponible para este encuentro."))
                    minute = (((item.get("fixture") or {}).get("fixture") or {}).get("status") or {}).get("elapsed")
                    if item.get("home_corners") is not None and item.get("away_corners") is not None and isinstance(minute, int) and minute < 90:
                        total_now = item["home_corners"] + item["away_corners"]
                        hist_rate = None
                        if history.get("home_corners_for") is not None and history.get("away_corners_for") is not None:
                            hist_rate = float(history["home_corners_for"]) + float(history["away_corners_for"])
                        if hist_rate is not None:
                            projected = 0.5 * hist_rate + 0.5 * (total_now * 90 / max(1, minute))
                            # 10.4 -> Más de 10.5; round upward to the next half-corner line.
                            import math
                            suggested_line = math.ceil(projected * 2) / 2
                            line_text = str(int(suggested_line)) if suggested_line.is_integer() else f"{suggested_line:.1f}"
                            st.markdown(
                                '<div class="signal-card">'
                                '<div class="signal-kicker">🚩 Tip sugerido · mercado de córners</div>'
                                '<div class="signal-title">Línea orientativa de córners totales</div>'
                                f'<div class="signal-pick">Más de {line_text}</div>'
                                f'<div class="signal-meta">Proyección del modelo: {projected:.1f} córners · En vivo: {total_now} córners al minuto {minute}</div>'
                                '</div>',
                                unsafe_allow_html=True,
                            )
                            st.caption("Tip orientativo calculado con promedios históricos y ritmo en vivo. No es una apuesta segura ni una probabilidad validada; verifica la línea y la cuota disponibles en tu casa de apuestas.")
                        else:
                            st.info("Tip de córners no disponible: faltan promedios históricos de ambos equipos para estimar la línea con el método actual. N/D significa dato ausente, no cero.")
                        if minute <= 5:
                            st.caption("Partido muy reciente: el ritmo en vivo todavía tiene poca muestra.")
                st.divider()
        else:
            st.info("Pulsa «Escanear todos los partidos en vivo» para obtener el análisis automático.")

    with tab_overview:
        st.subheader("Estado de los mercados")
        market_status = [
            ("Córners", "Consulta automática de promedios recientes local/visitante y combinación exploratoria con el ritmo en vivo; pendiente de validación."),
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
        st.markdown("### Validación retrospectiva")
        st.caption("En cada fila, outcome=1 si se cumplió ESE mercado y outcome=0 si no se cumplió (no escribas el marcador final). Marca outcome_verified=true solo después de comprobar el resultado real. Las filas no verificadas o inválidas se excluyen.")
        backtest_file = st.file_uploader(
            "Cargar CSV de señales con resultados verificados",
            type=["csv"],
            key="backtest_csv_upload",
        )
        if backtest_file is not None:
            try:
                uploaded_rows = list(csv.DictReader(io.StringIO(backtest_file.getvalue().decode("utf-8-sig"))))
                metrics = evaluate_binary_predictions(uploaded_rows)
                metric_cols = st.columns(4)
                metric_cols[0].metric("Muestra verificada", metrics["sample_size"])
                metric_cols[1].metric("Tasa de acierto", f"{metrics['hit_rate']:.1%}" if metrics["hit_rate"] is not None else "N/D")
                metric_cols[2].metric("Brier score", f"{metrics['brier_score']:.3f}" if metrics["brier_score"] is not None else "N/D")
                metric_cols[3].metric("Filas excluidas", metrics["excluded"])
                if metrics["sample_size"]:
                    st.caption(
                        f"Probabilidad media pronosticada: {metrics['mean_probability']:.1%} frente a "
                        f"frecuencia real de acierto: {metrics['observed_rate']:.1%}. "
                        "Una diferencia grande puede indicar mala calibración; evalúa cada mercado por separado y con una muestra suficiente. Brier score: cuanto más bajo, mejor (0 es perfecto)."
                    )
                else:
                    st.info("Todavía no hay filas con probabilidad válida y resultado binario marcado como verificado.")
            except (UnicodeDecodeError, csv.Error, ValueError) as exc:
                st.error(f"No se pudo leer el CSV para la evaluación: {exc}")

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


