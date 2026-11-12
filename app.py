import csv
import html
import io
import json
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
import time
from typing import Any

import requests
import streamlit as st

from ai_engine.data_engine import FootballDataEngine
from ai_engine.opportunity_engine import evaluate_opportunity, classify_goal_tip_market
from ai_engine.live_corner_capture import capture_live_corner_snapshot
from ai_engine.live_corner_finalize import finalize_live_corner_fixture
from models.live_context import qualifies_as_corner_candidate, summarize_live_context
from ai_engine.evaluation import evaluate_binary_forecasts, evaluate_forecasts_by_group, evaluate_forecasts_by_market, evaluate_chronological_holdout, assess_model_readiness
from ai_engine.dataset_audit import audit_forecast_dataset, audit_prediction_history
from ai_engine.prediction_schema import PREDICTION_SCHEMA_VERSION, normalize_prediction_record
from ai_engine.prediction_ledger import append_prediction_records, load_prediction_records
from ai_engine.supabase_prediction_ledger import append_supabase_prediction_records, load_supabase_prediction_records
from ai_engine.supabase_analysis_snapshots import build_analysis_snapshot, append_supabase_analysis_snapshots
from ai_engine.supabase_outcome_sync import sync_finished_fixture_outcomes, load_latest_match_outcomes
from ai_engine.supabase_evaluation import load_supabase_evaluations, summarize_supabase_evaluations, summarize_evaluations_by_minute
from ai_engine.outcome_ledger import load_verified_outcomes, record_verified_outcome
from ai_engine.settlement import resolve_binary_outcome, settle_prediction_rows
from ai_engine.telegram_publisher import send_telegram_signal, send_telegram_test_message
from ai_engine.telegram_store import build_alert_key, reserve_telegram_alert, update_telegram_alert, check_supabase_connection, test_supabase_duplicate_protection
from models.automatic_history import build_automatic_history
from models.deep_goal_context import build_deep_goal_context
from models.probabilities import (
    corner_pace_per_90,
    estimate_live_goal_markets,
    load_league_baselines,
    poisson_at_least,
    poisson_pmf,
)
from models.live_odds import (
    best_live_odds_by_market,
    classify_market,
    match_goal_tip_to_live_odds,
    extract_live_odds,
    numerology_context,
    score_pattern_context,
)

API_BASE = "https://v3.football.api-sports.io"
TIMEOUT_SECONDS = 15
def persist_analysis_snapshot(fixture_id, analysis_type, match_data, inputs, outputs):
    """Persistir el análisis sin convertirlo en una apuesta."""
    try:
        supabase_url = str(st.secrets.get("SUPABASE_URL", "") or os.getenv("SUPABASE_URL", "")).strip()
        secret_key = str(st.secrets.get("SUPABASE_SECRET_KEY", "") or os.getenv("SUPABASE_SECRET_KEY", "")).strip()
        if not supabase_url or not secret_key:
            return {"inserted": 0, "duplicates": 0, "skipped": True}
        snapshot = build_analysis_snapshot(fixture_id=fixture_id, analysis_type=analysis_type, match=match_data, inputs=inputs, outputs=outputs)
        result = append_supabase_analysis_snapshots([snapshot], supabase_url, secret_key)
        st.session_state["analysis_snapshot_last_result"] = {"type": analysis_type, "fixture_id": str(fixture_id), **result}
        st.session_state["analysis_snapshot_last_error"] = ""
        return result
    except Exception as exc:
        st.session_state["analysis_snapshot_last_error"] = f"{type(exc).__name__}: {exc}"
        return {"inserted": 0, "duplicates": 0, "error": str(exc)}

LIVE_CORNER_CAPTURE_DB = Path(os.environ.get(
    "FOOTBALL_LAB_DB_PATH",
    str(Path(__file__).resolve().parent / "data" / "football_lab.sqlite3"),
))

st.set_page_config(
    page_title="FOOTBALL LAB · Live Analytics",
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
  div.stButton > button[kind="secondary"] {
    border-color: #49402A; background: linear-gradient(145deg,#20252D,#111419); color: #E5E7EB;
  }
  div.stButton > button[kind="secondary"]:hover {
    border-color: #FACC15; background: linear-gradient(145deg,#3B3216,#211D12); color: #FFE566;
  }
  div.stButton > button[kind="primary"], div.stDownloadButton > button {
    border-color: #FFE566; background: #FACC15; color: #111111;
  }
  div.stButton > button[kind="primary"]:hover, div.stDownloadButton > button:hover {
    background: #FFE566; border-color: #FFE566; color: #111111;
  }

  /* Buscador principal: permitir el pintado nativo del texto en Safari/iOS. */
  html body .stApp div[class*="st-key-home_search_bar"] input,
  html body .stApp div[class*="st-key-home_search_bar"] input:focus,
  html body .stApp div[class*="st-key-home_search_bar"] input:focus-visible {
    color:#F8FAFC !important;
    -webkit-text-fill-color:#F8FAFC !important;
    -webkit-text-stroke:0 !important;
    text-shadow:none !important;
    mix-blend-mode:normal !important;
    filter:none !important;
    opacity:1 !important;
    visibility:visible !important;
    caret-color:#FACC15 !important;
  }
  /* Buscador premium de partidos: panel grafito, borde dorado y lupa compacta. */
  [class*="st-key-search_goal_matches"] { min-width:0 !important; }
  [class*="st-key-search_goal_matches"] [data-testid="stTextInput"] { margin:0 !important; }
  [class*="st-key-search_goal_matches"] [data-testid="stTextInput"] > div {
    min-height:48px !important; border:1px solid #6F5B20 !important;
    border-right:0 !important; border-radius:13px 0 0 13px !important;
    background:linear-gradient(145deg,#1C2027 0%,#111419 100%) !important;
    box-shadow:inset 0 1px 0 rgba(255,255,255,.035),0 5px 16px rgba(0,0,0,.18) !important;
    transition:border-color .18s ease,box-shadow .18s ease,background .18s ease !important;
  }
  [class*="st-key-search_goal_matches"] [data-testid="stTextInput"] > div:focus-within {
    border-color:#FACC15 !important;
    box-shadow:inset 0 0 0 1px rgba(250,204,21,.18),0 0 0 3px rgba(250,204,21,.08),0 0 18px rgba(250,204,21,.10) !important;
  }
  [class*="st-key-search_goal_matches"] input,
  [data-testid="stSidebar"] [class*="st-key-search_goal_matches"] input {
    min-height:46px !important; padding:0 13px !important;
    color:#F8FAFC !important; -webkit-text-fill-color:#F8FAFC !important;
    opacity:1 !important; text-shadow:none !important;
    font-size:.88rem !important; font-weight:550 !important;
    caret-color:#FACC15 !important; background:transparent !important;
  }
  [class*="st-key-search_goal_matches"] input::placeholder,
  [data-testid="stSidebar"] [class*="st-key-search_goal_matches"] input::placeholder {
    color:#9299A5 !important; -webkit-text-fill-color:#9299A5 !important; opacity:1 !important;
  }
  /* Fuerza el color del texto mientras se escribe; otros estilos de botones/vistas no deben ocultarlo en foco. */
  [data-testid="stSidebar"] [class*="st-key-search_goal_matches"] input,
  [data-testid="stSidebar"] [class*="st-key-search_goal_matches"] input:hover,
  [data-testid="stSidebar"] [class*="st-key-search_goal_matches"] input:active,
  [data-testid="stSidebar"] [class*="st-key-search_goal_matches"] input:focus,
  [data-testid="stSidebar"] [class*="st-key-search_goal_matches"] input:focus-visible,
  [data-testid="stSidebar"] [class*="st-key-search_goal_matches"] input:not(:placeholder-shown) {
    color:#FFFFFF !important;
    -webkit-text-fill-color:#FFFFFF !important;
    caret-color:#FACC15 !important;
    opacity:1 !important;
    visibility:visible !important;
    text-shadow:0 0 1px rgba(255,255,255,.12) !important;
    filter:none !important;
  }
  [data-testid="stSidebar"] [class*="st-key-search_goal_matches"] [data-testid="stTextInput"] input {
    color:#FFFFFF !important;
    -webkit-text-fill-color:#FFFFFF !important;
  }
  [class*="st-key-search_live_matches_button"] { margin:0 !important; }
  [class*="st-key-search_live_matches_button"] [data-testid="stButton"] { margin:0 !important; }
  [class*="st-key-search_live_matches_button"] button {
    min-height:48px !important; height:48px !important; padding:0 !important;
    border:1px solid #FDE047 !important; border-radius:0 13px 13px 0 !important;
    background:linear-gradient(145deg,#FFE566 0%,#FACC15 58%,#EAB308 100%) !important;
    color:#111419 !important; font-size:1.15rem !important; font-weight:900 !important;
    box-shadow:0 5px 16px rgba(250,204,21,.16),inset 0 1px 0 rgba(255,255,255,.35) !important;
    transition:filter .18s ease,box-shadow .18s ease,transform .18s ease !important;
  }
  [class*="st-key-search_live_matches_button"] button:hover {
    filter:brightness(1.08) !important; box-shadow:0 0 20px rgba(250,204,21,.28) !important;
    transform:translateY(-1px) !important;
  }
  [class*="st-key-search_live_matches_button"] button:active { transform:translateY(0) scale(.98) !important; }
  @media(max-width:640px) {
    [class*="st-key-search_goal_matches"] input { font-size:.82rem !important; padding:0 10px !important; }
    [class*="st-key-search_live_matches_button"] button { min-height:46px !important; height:46px !important; }
    [class*="st-key-search_goal_matches"] [data-testid="stTextInput"] > div { min-height:46px !important; }
  }
/* Los tres controles comparten tamaño, altura y línea; sin marcos dorados. */
  /* Forzar estilo minimalista en los contenedores Streamlit que envuelven los toggles. */
  [class*="st-key-auto_refresh_control_card"], [class*="st-key-sound_control_card"],
  [class*="st-key-auto_refresh_control_card"] *, [class*="st-key-sound_control_card"] * {
    box-shadow:none !important;
  }
  [class*="st-key-auto_refresh_control_card"], [class*="st-key-sound_control_card"],
  [class*="st-key-auto_refresh_control_card"] > div, [class*="st-key-sound_control_card"] > div,
  [class*="st-key-auto_refresh_control_card"] [data-testid="stVerticalBlock"],
  [class*="st-key-sound_control_card"] [data-testid="stVerticalBlock"],
  [class*="st-key-auto_refresh_control_card"] [data-testid="stHorizontalBlock"],
  [class*="st-key-sound_control_card"] [data-testid="stHorizontalBlock"],
  [class*="st-key-auto_refresh_control_card"] [data-testid="stToggle"],
  [class*="st-key-sound_control_card"] [data-testid="stToggle"],
  [class*="st-key-auto_refresh_control_card"] [data-testid="stToggle"] > label,
  [class*="st-key-sound_control_card"] [data-testid="stToggle"] > label {
    border:0 !important; outline:0 !important; border-color:transparent !important;
    border-radius:0 !important; background:transparent !important;
    min-height:22px !important; height:22px !important; padding:0 !important; margin:0 !important;
  }
  [class*="st-key-auto_refresh_control_card"] [data-testid="stToggle"] [role="switch"],
  [class*="st-key-sound_control_card"] [data-testid="stToggle"] [role="switch"] {
    transform:scale(.36) !important; transform-origin:center !important;
  }
  [class*="st-key-auto_refresh_control_card"] [data-testid="stMarkdownContainer"] > div,
  [class*="st-key-sound_control_card"] [data-testid="stMarkdownContainer"] > div {
    height:22px !important; min-height:22px !important; line-height:1 !important;
    font-size:8px !important; display:flex !important; align-items:center !important;
  }
  [class*="st-key-top_status_controls"] [data-testid="stHorizontalBlock"] { align-items:center !important; }
  [class*="st-key-top_status_controls"] [data-testid="stColumn"] { align-self:center !important; }
  
  [class*="st-key-top_status_controls"] { position:fixed !important; top:4px !important; left:8px !important; right:auto !important; z-index:10080 !important; display:block !important; width:276px !important; max-width:calc(100vw - 16px) !important; margin:0 !important; padding:0 !important; overflow:visible !important; background:transparent !important; }
  [class*="st-key-top_status_controls"] [data-testid="stHorizontalBlock"] { display:grid !important; grid-template-columns:repeat(3,minmax(0,1fr)) !important; align-items:center !important; gap:5px !important; flex-wrap:nowrap !important; overflow:visible !important; }
  [class*="st-key-top_status_controls"] [data-testid="stColumn"] { min-width:0 !important; width:auto !important; padding:0 !important; overflow:visible !important; }
  [class*="st-key-auto_refresh_control_card"], [class*="st-key-sound_control_card"], [class*="st-key-auto_refresh_control_card"] > div, [class*="st-key-sound_control_card"] > div, [class*="st-key-auto_refresh_control_card"] [data-testid="stVerticalBlock"], [class*="st-key-sound_control_card"] [data-testid="stVerticalBlock"] { box-sizing:border-box !important; width:100% !important; min-width:0 !important; min-height:22px !important; height:22px !important; display:flex !important; align-items:center !important; justify-content:center !important; padding:0 !important; border:0 !important; outline:0 !important; border-radius:0 !important; background:transparent !important; overflow:visible !important; box-shadow:none !important; }
  [class*="st-key-auto_refresh_control_card"] [data-testid="stHorizontalBlock"], [class*="st-key-sound_control_card"] [data-testid="stHorizontalBlock"] { gap:1px !important; align-items:center !important; height:22px !important; }
  [class*="st-key-auto_refresh_control_card"] [data-testid="stColumn"], [class*="st-key-sound_control_card"] [data-testid="stColumn"] { padding:0 !important; min-width:0 !important; }
  [class*="st-key-auto_refresh_control_card"] [data-testid="stToggle"], [class*="st-key-sound_control_card"] [data-testid="stToggle"] { display:flex !important; align-items:center !important; justify-content:center !important; min-height:22px !important; height:22px !important; padding:0 !important; margin:0 !important; background:transparent !important; }
  [class*="st-key-auto_refresh_control_card"] [data-testid="stToggle"] > label, [class*="st-key-sound_control_card"] [data-testid="stToggle"] > label { display:flex !important; align-items:center !important; justify-content:center !important; gap:1px !important; width:100% !important; height:22px !important; margin:0 !important; padding:0 !important; white-space:nowrap !important; }
  [class*="st-key-auto_refresh_control_card"] [data-testid="stToggle"] label p, [class*="st-key-sound_control_card"] [data-testid="stToggle"] label p { color:#D8C27A !important; font-size:8px !important; line-height:1 !important; margin:0 !important; white-space:nowrap !important; }
  [class*="st-key-auto_refresh_control_card"] [role="switch"], [class*="st-key-sound_control_card"] [role="switch"] { flex:0 0 auto !important; transform:scale(.42) !important; transform-origin:center !important; }
  [class*="st-key-auto_refresh_control_card"] [data-testid="stMarkdownContainer"] > div, [class*="st-key-sound_control_card"] [data-testid="stMarkdownContainer"] > div { height:22px !important; min-height:22px !important; display:flex !important; align-items:center !important; font-size:8px !important; line-height:1 !important; }
  [class*="st-key-top_status_controls"] iframe { display:block !important; width:100% !important; height:34px !important; min-height:34px !important; max-height:34px !important; margin:0 !important; padding:0 !important; border:0 !important; overflow:visible !important; align-self:center !important; }
  @media(max-width:640px) { [class*="st-key-top_status_controls"] { top:3px !important; left:5px !important; right:auto !important; width:248px !important; max-width:calc(100vw - 10px) !important; } [class*="st-key-top_status_controls"] [data-testid="stHorizontalBlock"] { gap:3px !important; } [class*="st-key-auto_refresh_control_card"] [data-testid="stToggle"] label p, [class*="st-key-sound_control_card"] [data-testid="stToggle"] label p { font-size:7px !important; } [class*="st-key-top_status_controls"] [role="switch"] { transform:scale(.38) !important; } [class*="st-key-top_status_controls"] iframe { height:34px !important; min-height:34px !important; max-height:34px !important; } }
  [class*="st-key-sound_enabled_toggle"] { padding:5px 8px; border:1px solid #393326; border-radius:12px; background:#15191F; }
  [class*="st-key-sound_enabled_toggle"] label { font-size:.92rem !important; font-weight:650 !important; }
  [class*="st-key-sound_enabled_toggle"] [role="switch"] { transform:scale(.88); transform-origin:center; }
  [data-testid="stStatusWidget"] { display:none !important; }
  [class*="st-key-control_row"] { flex-wrap:nowrap !important; align-items:flex-start !important; justify-content:flex-start !important; }
  [class*="st-key-control_row"] [data-testid="stButton"] { width:auto !important; flex:0 0 auto !important; }
  [class*="st-key-control_row"] [data-testid="stButton"] button { width:auto !important; min-width:150px !important; }
  [class*="st-key-control_row"] button[kind="primary"] {
    background:#FFE34D !important; background-color:#FFE34D !important; color:#090A0D !important;
    border:1px solid #FFF29A !important; font-weight:800 !important;
    box-shadow:0 0 0 1px rgba(255,227,77,.22),0 0 16px rgba(255,211,36,.32) !important;
    transition:background .18s ease,box-shadow .18s ease,transform .18s ease !important;
  }
  [class*="st-key-control_row"] button[kind="primary"]:hover {
    background:#FFF078 !important; background-color:#FFF078 !important; color:#090A0D !important;
    border-color:#FFF6BD !important; box-shadow:0 0 20px rgba(255,227,77,.5) !important;
  }
  [class*="st-key-control_row"] button[kind="primary"] p {
    color:#090A0D !important; font-weight:800 !important;
  }
  /* Barra de escaneo premium: pista oscura, progreso dorado y brillo móvil. */
  [class*="st-key-scan-progress"] { margin:2px 0 10px !important; padding:0 !important; }
  [class*="st-key-scan-progress"] [data-testid="stProgress"] { margin:5px 0 0 !important; padding:0 !important; }
  [class*="st-key-scan-progress"] [data-testid="stProgress"] > div,
  [class*="st-key-scan-progress"] [data-testid="stProgress"] [role="progressbar"] {
    height:10px !important; min-height:10px !important; border-radius:999px !important;
    overflow:hidden !important; background:#25231B !important; border:1px solid #3C3212 !important;
    box-shadow:inset 0 1px 3px rgba(0,0,0,.65),0 0 10px rgba(250,204,21,.06) !important;
  }
  [class*="st-key-scan-progress"] [data-testid="stProgress"] > div > div,
  [class*="st-key-scan-progress"] [data-testid="stProgress"] [role="progressbar"] > div,
  [class*="st-key-scan-progress"] [data-testid="stProgress"] [role="progressbar"] > div > div {
    height:100% !important; border-radius:999px !important;
    background:linear-gradient(90deg,#8A6A0A 0%,#D4A72C 28%,#FFE566 58%,#FACC15 82%,#FFF2A6 100%) !important;
    background-size:220% 100% !important; animation:fl-progress-shimmer 1.8s linear infinite !important;
    box-shadow:0 0 9px rgba(250,204,21,.45) !important;
  }
  .fl-scan-progress-head { display:flex; align-items:center; justify-content:space-between; gap:12px; margin:7px 0 0; font-family:system-ui,-apple-system,sans-serif; }
  /* Separación estructural: evita que la primera barra se monte sobre el título y el porcentaje. */
  [class*="st-key-scan-progress"] .fl-scan-progress-head {
    box-sizing:border-box !important;
    position:relative !important;
    z-index:2 !important;
    display:flex !important;
    align-items:center !important;
    justify-content:space-between !important;
    width:100% !important;
    min-height:26px !important;
    padding:3px 0 7px !important;
    margin:0 0 7px !important;
    overflow:visible !important;
    clear:both !important;
  }
  [class*="st-key-scan-progress"] [data-testid="stProgress"] {
    position:relative !important;
    z-index:1 !important;
    display:block !important;
    clear:both !important;
    width:100% !important;
    margin:5px 0 0 !important;
    padding:0 !important;
  }
  [class*="st-key-scan-progress"] [data-testid="stProgress"] > div {
    box-sizing:border-box !important;
  }

  [class*="st-key-scan-progress"] .fl-scan-progress-head { display:flex !important; visibility:visible !important; opacity:1 !important; min-height:16px !important; }
  [class*="st-key-scan-progress"] .fl-scan-progress-title { color:#FFF1A8 !important; -webkit-text-fill-color:#FFF1A8 !important; opacity:1 !important; visibility:visible !important; display:inline-block !important; font-size:11px !important; line-height:1.25 !important; font-weight:900 !important; letter-spacing:.12em; text-transform:uppercase; }
  [class*="st-key-scan-progress"] .fl-scan-progress-percent { color:#FFE45C !important; -webkit-text-fill-color:#FFE45C !important; opacity:1 !important; visibility:visible !important; display:inline-block !important; font-size:12px !important; line-height:1.25 !important; font-weight:900 !important; font-variant-numeric:tabular-nums; text-shadow:0 0 10px rgba(250,204,21,.24); }
  [class*="st-key-scan-progress"] .fl-scan-progress-caption { display:flex !important; visibility:visible !important; align-items:center; gap:6px; color:#D6D3B8 !important; -webkit-text-fill-color:#D6D3B8 !important; opacity:1 !important; font-size:10px !important; line-height:1.35 !important; margin:4px 0 0; }
  .fl-scan-progress-caption .fl-live-dot { width:5px; height:5px; flex:0 0 5px; border-radius:50%; background:#FACC15; box-shadow:0 0 8px #FACC15; animation:fl-live-pulse 1.2s ease-in-out infinite; }
  .fl-scan-progress-caption.is-done { color:#F1E8BF !important; -webkit-text-fill-color:#F1E8BF !important; opacity:1 !important; }
  .fl-scan-progress-caption.is-done .fl-live-dot { background:#86EFAC; box-shadow:0 0 7px #86EFAC; animation:none; }
  @keyframes fl-progress-shimmer { from { background-position:100% 0; } to { background-position:-120% 0; } }
  @keyframes fl-live-pulse { 0%,100% { opacity:.45; transform:scale(.85); } 50% { opacity:1; transform:scale(1.15); } }
  @media(prefers-reduced-motion:reduce) {
    [class*="st-key-scan-progress"] [data-testid="stProgress"] [role="progressbar"] > div,
    [class*="st-key-scan-progress"] [data-testid="stProgress"] [role="progressbar"] > div > div { animation:none !important; }
    .fl-scan-progress-caption .fl-live-dot { animation:none !important; }
  }
  [class*="st-key-control_row"] button { min-height:2.45rem !important; padding:.35rem .65rem !important; border-radius:10px !important; font-size:.88rem !important; white-space:nowrap; }
  @media(max-width:640px) {
    [class*="st-key-control_row"] { gap:.45rem !important; }
    [class*="st-key-control_row"] button { font-size:.78rem !important; padding:.3rem .4rem !important; }
    [class*="st-key-control_row"] label { font-size:.78rem !important; }

    /* Ajuste móvil: progreso alineado al ancho útil, sin desbordes ni escala excesiva. */
    [class*="st-key-scan-progress"] {
      display:block !important;
      width:calc(100% - 18px) !important;
      max-width:100% !important;
      min-width:0 !important;
      margin:8px auto 12px !important;
      padding:0 !important;
      box-sizing:border-box !important;
    }
    [class*="st-key-scan-progress"] > div,
    [class*="st-key-scan-progress"] [data-testid="stVerticalBlock"],
    [class*="st-key-scan-progress"] [data-testid="stElementContainer"] {
      width:100% !important;
      max-width:100% !important;
      min-width:0 !important;
      box-sizing:border-box !important;
    }
    [class*="st-key-scan-progress"] [data-testid="stProgress"] {
      width:100% !important;
      margin:5px 0 0 !important;
    }
    [class*="st-key-scan-progress"] [data-testid="stProgress"] > div,
    [class*="st-key-scan-progress"] [data-testid="stProgress"] [role="progressbar"] {
      height:8px !important;
      min-height:8px !important;
    }
    .fl-scan-progress-head {
      width:100% !important;
      gap:8px !important;
      margin:5px 0 0 !important;
    }
    .fl-scan-progress-title {
      font-size:10px !important;
      letter-spacing:.095em !important;
      line-height:1.2 !important;
    }
    .fl-scan-progress-percent {
      flex:0 0 auto !important;
      font-size:11px !important;
    }
    .fl-scan-progress-caption {
      width:100% !important;
      max-width:100% !important;
      font-size:9px !important;
      line-height:1.3 !important;
      white-space:normal !important;
      overflow-wrap:anywhere !important;
    }
    .scan-running-status {
      width:calc(100% - 18px) !important;
      max-width:100% !important;
      margin:8px auto 22px !important;
      padding:10px 12px !important;
      gap:9px !important;
      box-sizing:border-box !important;
      font-size:.82rem !important;
    }
    .scan-code-icon { font-size:1.65rem !important; }
    .scan-running-subtitle { font-size:.74rem !important; }
  }

  [class*="st-key-sound_enabled_toggle"] { padding:5px 8px; border:1px solid #393326; border-radius:12px; background:#15191F; }
  [class*="st-key-sound_enabled_toggle"] label { font-size:.92rem !important; font-weight:650 !important; }
  [class*="st-key-sound_enabled_toggle"] [role="switch"] { transform:scale(.88); transform-origin:center; }
  [class*="st-key-sound_enabled_toggle"] [role="switch"][aria-checked="true"],
  [data-testid="stToggle"] [role="switch"][aria-checked="true"],
  button[role="switch"][aria-checked="true"] { background:#FACC15 !important; background-color:#FACC15 !important; border-color:#FFE566 !important; }
  [class*="st-key-sound_enabled_toggle"] [role="switch"][aria-checked="true"] > div,
  [data-testid="stToggle"] [role="switch"][aria-checked="true"] > div,
  button[role="switch"][aria-checked="true"] > div { background:#111419 !important; }
  [class*="st-key-sound_enabled_toggle"] [role="switch"][aria-checked="false"],
  [data-testid="stToggle"] [role="switch"][aria-checked="false"],
  button[role="switch"][aria-checked="false"] { background:#FF4B4B !important; background-color:#FF4B4B !important; border-color:#FF4B4B !important; }
  [class*="st-key-sound_enabled_toggle"] [role="switch"][aria-checked="false"] > div,
  [data-testid="stToggle"] [role="switch"][aria-checked="false"] > div,
  button[role="switch"][aria-checked="false"] > div { background:#FFFFFF !important; }
  /* Tipografía y color idénticos a Alertas en los tres controles */
  [class*="st-key-auto_refresh_control_card"] [data-testid="stToggle"] label,
  [class*="st-key-auto_refresh_control_card"] [data-testid="stToggle"] label p,
  [class*="st-key-auto_refresh_control_card"] [data-testid="stToggle"] label span,
  [class*="st-key-sound_control_card"] [data-testid="stToggle"] label,
  [class*="st-key-sound_control_card"] [data-testid="stToggle"] label p,
  [class*="st-key-sound_control_card"] [data-testid="stToggle"] label span {
    color:#F4D778 !important;
    font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif !important;
    font-size:11px !important;
    font-weight:600 !important;
    line-height:1.1 !important;
    letter-spacing:0 !important;
    white-space:nowrap !important;
  }
  [class*="st-key-auto_refresh_control_card"] [data-testid="stToggle"] label p,
  [class*="st-key-sound_control_card"] [data-testid="stToggle"] label p { margin:0 !important; }
  [class*="st-key-auto_refresh_control_card"] [data-testid="stToggle"] label *,
  [class*="st-key-sound_control_card"] [data-testid="stToggle"] label * {
    color:#F4D778 !important;
    fill:#F4D778 !important;
  }
  /* Ajuste final: tres tarjetas del mismo tamaño y controles dorados */
  [class*="st-key-auto_refresh_control_card"], [class*="st-key-sound_control_card"] {
    width:100% !important; height:48px !important; min-height:48px !important; max-height:48px !important;
    margin:0 !important; padding:0 4px !important; border:1px solid #D4A72C !important;
    border-radius:11px !important; background:linear-gradient(145deg,#201D14,#111419) !important;
    box-sizing:border-box !important; overflow:hidden !important;
  }
  [class*="st-key-auto_refresh_control_card"] [data-testid="stToggle"],
  [class*="st-key-sound_control_card"] [data-testid="stToggle"] {
    width:100% !important; height:46px !important; min-height:46px !important; max-height:46px !important;
    margin:0 !important; padding:0 !important; border:0 !important; border-radius:0 !important;
    background:transparent !important; box-sizing:border-box !important;
  }
  [class*="st-key-auto_refresh_control_card"] [data-testid="stToggle"] label p,
  [class*="st-key-sound_control_card"] [data-testid="stToggle"] label p {
    color:#F4D778 !important; font-size:.72rem !important; font-weight:650 !important;
  }
  [class*="st-key-auto_refresh_control_card"] [role="switch"],
  [class*="st-key-sound_control_card"] [role="switch"] {
    background:#242014 !important; background-color:#242014 !important; border:1px solid #D4A72C !important;
    box-shadow:none !important; transform:scale(.72) !important;
  }
  [class*="st-key-auto_refresh_control_card"] [role="switch"][aria-checked="true"],
  [class*="st-key-sound_control_card"] [role="switch"][aria-checked="true"],
  [class*="st-key-auto_refresh_control_card"] button[role="switch"][aria-checked="true"],
  [class*="st-key-sound_control_card"] button[role="switch"][aria-checked="true"] {
    background:#FACC15 !important; background-color:#FACC15 !important; border-color:#FFE566 !important;
  }
  [class*="st-key-auto_refresh_control_card"] [role="switch"][aria-checked="true"] > div,
  [class*="st-key-sound_control_card"] [role="switch"][aria-checked="true"] > div { background:#111419 !important; }
  [class*="st-key-auto_refresh_control_card"] [role="switch"][aria-checked="false"],
  [class*="st-key-sound_control_card"] [role="switch"][aria-checked="false"] {
    background:#242014 !important; background-color:#242014 !important; border-color:#D4A72C !important;
  }
  [class*="st-key-auto_refresh_control_card"] [role="switch"][aria-checked="false"] > div,
  [class*="st-key-sound_control_card"] [role="switch"][aria-checked="false"] > div { background:#D4A72C !important; }
  [class*="st-key-top_status_controls"] iframe body { margin:0 !important; padding:0 !important; }
 
   /* Acciones principales en una sola fila: escáner a la izquierda y actualizar a la derecha. */
   [class*="st-key-scan_actions_row"] [data-testid="stHorizontalBlock"] {
     display:grid !important; grid-template-columns:minmax(0,1.35fr) minmax(0,1fr) !important;
     align-items:center !important; gap:12px !important;
   }
   [class*="st-key-scan_actions_row"] [data-testid="column"] {
     min-width:0 !important; width:auto !important; flex:none !important;
   }
   [class*="st-key-scan_actions_row"] [data-testid="stButton"] { width:100% !important; }
   [class*="st-key-scan_actions_row"] [data-testid="stButton"] > button {
     width:100% !important; box-sizing:border-box !important; min-width:0 !important;
   }
   [class*="st-key-control_row"] { margin:0 !important; width:100% !important; }
   [class*="st-key-control_row"] [data-testid="stButton"] > button {
     min-height:145px !important; height:145px !important; white-space:normal !important;
     padding:12px !important; font-size:clamp(.9rem,2vw,1.05rem) !important;
   }
   @media(max-width:640px) {
     [class*="st-key-scan_actions_row"] [data-testid="stHorizontalBlock"] {
       grid-template-columns:minmax(0,1.25fr) minmax(0,.9fr) !important; gap:8px !important;
     }
     [class*="st-key-scan_cta_card"] { margin-top:20px !important; }
     [class*="st-key-scan_cta_card"] [data-testid="stButton"] button,
     [class*="st-key-scan_cta_card"] button[kind="primary"] {
       min-height:116px !important; height:116px !important; padding:9px 7px 9px 43% !important;
       border-radius:16px !important; font-size:.75rem !important; line-height:1.32 !important;
     }
     [class*="st-key-scan_cta_card"] [data-testid="stButton"] button::before {
       left:4% !important; width:34% !important; border-width:2px !important;
     }
     [class*="st-key-scan_cta_card"] [data-testid="stButton"] button::after {
       left:21% !important; width:28px !important; height:28px !important; font-size:1.65rem !important;
     }
     [class*="st-key-control_row"] [data-testid="stButton"] > button {
       min-height:126px !important; height:126px !important; padding:8px 6px !important;
       border-radius:14px !important; font-size:.86rem !important; white-space:normal !important;
       line-height:1.25 !important;
     }
   }
   /* Tarjeta compacta de acción principal del escáner */
  [class*="st-key-scan_cta_card"] { margin-top:10px !important; margin-bottom:0 !important; }
  /* En móvil, separar la fila completa del encabezado fijo para que no tape el escáner. */
  @media(max-width:640px) {
    [class*="st-key-scan_actions_row"] {
      padding-top:30px !important; box-sizing:border-box !important;
    }
    [class*="st-key-scan_actions_row"] [data-testid="stHorizontalBlock"] {
      margin-top:24px !important; align-items:center !important;
    }
    /* El espacio se controla desde la fila completa para que no cambie tras el scan. */
    [class*="st-key-scan_cta_card"] { margin-top:0 !important; margin-bottom:0 !important; }
    [class*="st-key-control_row"] { align-self:center !important; margin-top:0 !important; }
  }
  [class*="st-key-analysis_scan_cta"] { margin:.35rem 0 .65rem !important; }
  /* Botones grandes y llamativos dentro de las secciones de goles y córners. */
  [class*="st-key-analysis_scan_cta"] [data-testid="stButton"] > button {
      width:100% !important; min-height:108px !important; height:108px !important;
      box-sizing:border-box !important; padding:16px 12px !important;
      border-radius:18px !important; border:2px solid #FACC15 !important;
      background:radial-gradient(ellipse at 50% 0%,rgba(250,204,21,.16),transparent 65%),linear-gradient(145deg,#24221A,#111318) !important;
      color:#FFE36A !important; font-size:clamp(.95rem,2.8vw,1.15rem) !important;
      line-height:1.35 !important; font-weight:850 !important; white-space:normal !important;
      box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 0 0 1px rgba(250,204,21,.12),0 5px 18px rgba(0,0,0,.25) !important;
      transition:transform .18s ease,background .18s ease,box-shadow .18s ease,border-color .18s ease !important;
  }
  [class*="st-key-analysis_scan_cta"] [data-testid="stButton"] > button:hover {
      background:radial-gradient(ellipse at 50% 0%,rgba(250,204,21,.24),transparent 65%),linear-gradient(145deg,#39311A,#191A1F) !important;
      border-color:#FFF09A !important; color:#FFF09A !important;
      box-shadow:inset 0 1px 0 rgba(255,255,255,.12),0 0 18px rgba(250,204,21,.22) !important;
      transform:translateY(-2px) !important;
  }
  [class*="st-key-analysis_scan_cta"] [class*="st-key-analysis_scan_radar"] button {
      background:radial-gradient(ellipse at 50% 0%,rgba(250,204,21,.22),transparent 65%),linear-gradient(145deg,#292516,#111318) !important;
  }
  @media(max-width:640px) {
    [class*="st-key-analysis_scan_cta"] [data-testid="stButton"] > button {
      min-height:92px !important; height:92px !important; padding:12px 6px !important;
      border-radius:15px !important; font-size:.9rem !important; line-height:1.3 !important;
    }
  }
  [class*="st-key-analysis_scan_cta"] [data-testid="stButton"] > button:hover {
     background:linear-gradient(135deg,#FFF0A3,#FFD629) !important; border-color:#FFF0A3 !important;
  }
  [class*="st-key-analysis_scan_radar"] [data-testid="stButton"] > button {
     position:relative !important; overflow:hidden !important; padding-left:2.4rem !important;
     background:linear-gradient(135deg,#1A1B20,#101115) !important; color:#FACC15 !important;
     border-color:#7D6820 !important;
  }
  [class*="st-key-analysis_scan_radar"] [data-testid="stButton"] > button::before {
     content:""; position:absolute; left:.55rem; top:50%; width:1.25rem; height:1.25rem;
     transform:translateY(-50%); border:2px solid #FACC15; border-radius:50%;
     background:repeating-radial-gradient(circle,transparent 0 3px,#FACC15 4px 5px,transparent 6px 8px);
     animation:scanner-radar-spin 1.8s linear infinite;
  }
  /* Acercar el panel En vivo ahora al escáner principal */
  [class*="st-key-live_now_section"] { margin-top:-64px !important; padding-top:0 !important; }
  [class*="st-key-live_now_section"] > div { padding-top:0 !important; }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] button, [class*="st-key-scan_cta_card"] button[kind="primary"] { position:relative !important; overflow:hidden !important; width:100% !important; min-height:145px !important; white-space:pre-line !important; text-align:left !important; padding:18px 18px 18px 49% !important; border-radius:22px !important; border:2px solid #FACC15 !important; background-color:#090A0D !important; background-image:radial-gradient(ellipse at 20% 50%,rgba(250,204,21,.10),transparent 42%),linear-gradient(135deg,#090A0D,#111319) !important; color:#F4F4F5 !important; font-size:clamp(1rem,3.8vw,1.35rem) !important; line-height:1.55 !important; font-weight:800 !important; box-shadow:inset 0 0 24px rgba(250,204,21,.06),0 0 0 1px rgba(250,204,21,.08) !important; }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] button::before { content:""; position:absolute; left:4%; top:50%; width:min(38%,170px); aspect-ratio:1; height:auto; transform:translateY(-50%); border-radius:50%; border:3px solid #FACC15; background-color:#090A0D; background-image:radial-gradient(circle at center,#FACC15 0 6%,#14151A 7% 14%,transparent 15%),repeating-radial-gradient(circle at center,transparent 0 10px,rgba(250,204,21,.55) 11px 13px,transparent 14px 20px),conic-gradient(from 0deg,transparent 0 12%,rgba(250,204,21,.95) 16%,transparent 28% 48%,rgba(250,204,21,.45) 53%,transparent 68%); box-shadow:0 0 20px rgba(250,204,21,.45),inset 0 0 18px rgba(250,204,21,.25); animation:scanner-radar-spin 3s linear infinite; }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] button::after { content:"⚽"; position:absolute; left:23%; top:50%; transform:translate(-50%,-50%); width:40px; height:40px; display:flex; align-items:center; justify-content:center; font-size:clamp(1.8rem,6vw,2.7rem); filter:drop-shadow(0 0 10px rgba(250,204,21,.75)); animation:scanner-ball-orbit 2s ease-in-out infinite; }

   /* Tipografía del escáner: jerarquía clara y texto compacto sin alterar la tarjeta ni el balón. */
   [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button {
     text-align:left !important; white-space:pre-line !important;
     letter-spacing:.01em !important; overflow-wrap:normal !important; word-break:normal !important;
     font-weight:750 !important;
   }
   [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p {
     line-height:1.42 !important; margin:0 !important;
   }
   @media(max-width:640px) {
     [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button {
       font-size:.76rem !important; line-height:1.4 !important; letter-spacing:0 !important;
     }
     [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p {
       line-height:1.45 !important;
     }
   }  @keyframes scanner-ball-orbit {
    0% { transform:translate(-50%,-50%) rotate(0deg) scale(1); }
    50% { transform:translate(-50%,-50%) rotate(180deg) scale(1.08); }
    100% { transform:translate(-50%,-50%) rotate(360deg) scale(1); }
  }
  @keyframes scanner-radar-spin {
    from { transform:translateY(-50%) rotate(0deg); }
    to { transform:translateY(-50%) rotate(360deg); }
  }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] button:hover, [class*="st-key-scan_cta_card"] button[kind="primary"]:hover { border-color:#FFE36A !important; background-color:#090A0D !important; background-image:radial-gradient(ellipse at 20% 50%,rgba(250,204,21,.13),transparent 42%),linear-gradient(135deg,#14151A,#1A180F) !important; color:#FFE36A !important; }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] button:active { transform:scale(.99); }
  .scan-refresh-feedback { margin:8px 2px 12px; padding:11px 14px 12px; border:1px solid rgba(250,204,21,.42); border-radius:13px; color:#FFE36A; background:linear-gradient(110deg,#17191F,#0B0D10); }
  .scan-refresh-feedback-top { display:flex; align-items:center; gap:11px; font-size:.94rem; font-weight:900; letter-spacing:.35px; }
  .scan-refresh-feedback .scan-code-icon { font-size:1.25rem; animation:scan-refresh-spin 1.3s linear infinite; }
  .scan-refresh-feedback.is-done { border-color:rgba(74,222,128,.55); color:#86EFAC; background:linear-gradient(110deg,#102019,#0B0D10); }
  .scan-refresh-feedback.is-done .scan-code-icon { animation:none; }
  .scan-refresh-track { height:7px; margin-top:10px; overflow:hidden; border-radius:99px; background:#292A2D; }
  .scan-refresh-fill { height:100%; border-radius:99px; background:linear-gradient(90deg,#B58D0B,#FFE566); transition:width .35s ease; }
  .scan-refresh-feedback:not(.is-done) .scan-refresh-fill { animation:scan-refresh-progress 1.8s ease-in-out infinite alternate; }
  @keyframes scan-refresh-spin { to { transform:rotate(360deg); } }
  @keyframes scan-refresh-progress { from { width:24% !important; } to { width:82% !important; } }
  /* Fallback directo para botones secundarios: algunos wrappers de Streamlit no conservan el selector por key */
  [data-testid="stBaseButton-secondary"] { background:linear-gradient(135deg,#292416,#17191F) !important; background-color:#17191F !important; color:#FFE36A !important; border:1px solid #D6B84C !important; }
  [data-testid="stBaseButton-secondary"]:hover { background:linear-gradient(135deg,#443819,#242018) !important; background-color:#242018 !important; color:#FFF1A8 !important; border-color:#FFE566 !important; }
  /* Botón Histórico de córners: compacto, premium y coherente con Football Lab */
  [class*="st-key-corner_h2h_"] [data-testid="stButton"] > button {
     position:relative !important; display:flex !important; align-items:center !important; justify-content:flex-start !important;
     gap:10px !important; width:100% !important; min-height:52px !important; padding:10px 42px 10px 14px !important;
     border:1px solid #80661B !important; border-radius:13px !important;
     background:linear-gradient(110deg,#211E14 0%,#17191F 58%,#101115 100%) !important; background-color:#17191F !important;
     color:#FFE36A !important; font-size:.88rem !important; font-weight:900 !important; letter-spacing:.045em !important;
     line-height:1.2 !important; text-align:left !important; white-space:normal !important;
     box-shadow:inset 0 1px 0 rgba(255,255,255,.045),0 3px 10px rgba(0,0,0,.22) !important;
     transition:border-color .18s ease,background .18s ease,box-shadow .18s ease,transform .14s ease !important;
  }
  [class*="st-key-corner_h2h_"] [data-testid="stButton"] > button::before {
     content:"▥" !important; position:absolute !important; z-index:5 !important; pointer-events:none !important;
     left:14px !important; top:50% !important; transform:translateY(-50%) !important;
     display:flex !important; align-items:center !important; justify-content:center !important;
     width:30px !important; height:30px !important; box-sizing:border-box !important;
     border:1px solid rgba(250,204,21,.42) !important; border-radius:8px !important;
     background:linear-gradient(145deg,#332B12,#1A1B20) !important; color:#FACC15 !important;
     font-size:1.15rem !important; line-height:1 !important; box-shadow:inset 0 1px 0 rgba(255,255,255,.05) !important;
  }
  [class*="st-key-corner_h2h_"] [data-testid="stButton"] > button::after {
     content:"↗" !important; position:absolute !important; z-index:5 !important; pointer-events:none !important;
     right:14px !important; top:50% !important; transform:translateY(-50%) !important;
     display:flex !important; align-items:center !important; justify-content:center !important;
     width:24px !important; height:24px !important; color:#FACC15 !important; font-size:1.05rem !important; font-weight:900 !important;
     transition:transform .18s ease,color .18s ease !important;
  }
  [class*="st-key-corner_h2h_"] [data-testid="stButton"] > button:hover {
     border-color:#FFE566 !important; background:linear-gradient(110deg,#3A3016 0%,#242018 58%,#17191F 100%) !important;
     background-color:#242018 !important; color:#FFF1A8 !important;
     box-shadow:0 0 0 1px rgba(250,204,21,.08),0 0 16px rgba(250,204,21,.16) !important;
  }
  [class*="st-key-corner_h2h_"] [data-testid="stButton"] > button:hover::after { color:#FFE566 !important; transform:translate(2px,-50%) !important; }
  [class*="st-key-corner_h2h_"] [data-testid="stButton"] > button:hover::before { border-color:#FFE566 !important; box-shadow:0 0 10px rgba(250,204,21,.18) !important; }
  [class*="st-key-corner_h2h_"] [data-testid="stButton"] > button:active { transform:scale(.985) !important; }
  @media(prefers-reduced-motion:reduce) { [class*="st-key-corner_h2h_"] [data-testid="stButton"] > button { transition:none !important; } }
  .scan-running-status { position:relative; display:flex; align-items:center; gap:12px; overflow:hidden; color:#FACC15; margin:8px 2px 22px !important; padding:12px 14px; border:1px solid rgba(250,204,21,.35); border-radius:14px; background:linear-gradient(110deg,#17191F,#0B0D10); font-size:.92rem; font-weight:700; }
  .scan-code-icon { display:inline-block; flex:0 0 auto; font-size:2rem; transform-origin:center; animation:scanner-spiral-spin .8s linear infinite !important; will-change:transform; text-shadow:0 0 12px rgba(250,204,21,.8); }
  @keyframes scanner-spiral-spin { from { transform:rotate(0deg); } to { transform:rotate(360deg); } }
  .scan-running-subtitle { color:#A1A1AA; font-size:.82rem; font-weight:500; margin-top:3px; }
  .scan-sweep { position:absolute; left:0; right:0; bottom:0; height:2px; background:linear-gradient(90deg,transparent,#FACC15,transparent); animation:scanner-sweep 1.4s ease-in-out infinite; }
  /* Intro cinematográfica híbrida: estadio nocturno + visualización de datos ligera */
  .football-splash { position:fixed; inset:0; z-index:999999; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:0; overflow:hidden; padding:20px; box-sizing:border-box; background:radial-gradient(ellipse at 50% 48%,rgba(163,112,15,.19) 0%,rgba(10,14,20,.96) 42%,#05070A 82%); color:#fff; pointer-events:none; transform-origin:center; animation:splash-dismiss 4.1s cubic-bezier(.65,0,.35,1) forwards; }
  .football-splash:before { content:""; position:absolute; inset:-18%; pointer-events:none; background:repeating-linear-gradient(112deg,transparent 0 13%,rgba(255,210,75,.045) 13.2%,transparent 13.5% 27%),radial-gradient(ellipse at 50% 100%,rgba(250,204,21,.18),transparent 55%); animation:splash-stadium-glow 3.4s ease-in-out both; }
  .football-splash:after { content:""; position:absolute; inset:0; pointer-events:none; opacity:.4; background:repeating-linear-gradient(90deg,transparent 0 9.5%,rgba(250,204,21,.07) 9.7%,transparent 10%),linear-gradient(180deg,transparent 0 70%,rgba(250,204,21,.05)); }
  .splash-pitch { position:relative; width:min(82vw,520px); height:min(39vh,260px); border:1px solid rgba(250,204,21,.65); border-radius:12px; background:radial-gradient(ellipse at 50% 55%,rgba(250,204,21,.12),transparent 55%),linear-gradient(180deg,rgba(18,25,33,.76),rgba(5,8,12,.9)); box-shadow:0 0 28px rgba(250,204,21,.12),inset 0 0 36px rgba(250,204,21,.05); overflow:hidden; transform:perspective(600px) rotateX(7deg); animation:splash-pitch-in .7s ease-out both; }
  .splash-pitch:before { content:""; position:absolute; inset:0 25%; border-left:1px solid rgba(255,226,120,.52); border-right:1px solid rgba(255,226,120,.52); background:linear-gradient(90deg,transparent 49.7%,rgba(255,226,120,.35) 50%,transparent 50.3%); }
  .splash-pitch:after { content:""; position:absolute; width:27%; aspect-ratio:1; left:36.5%; top:36%; border:1px solid rgba(255,226,120,.65); border-radius:50%; box-shadow:0 0 20px rgba(250,204,21,.14),inset 0 0 18px rgba(250,204,21,.08); }
  .splash-goal { position:absolute; right:0; top:29%; width:14%; height:42%; border:1px solid rgba(255,231,143,.9); border-right:0; background:repeating-linear-gradient(0deg,transparent 0 12px,rgba(255,226,120,.22) 13px 14px),repeating-linear-gradient(90deg,transparent 0 12px,rgba(255,226,120,.22) 13px 14px); box-shadow:0 0 0 rgba(250,204,21,0); animation:splash-goal-hit .55s ease 1.25s both; }
  .splash-data-orbit { position:absolute; left:50%; top:50%; width:min(36vw,180px); aspect-ratio:1; border:1px solid rgba(250,204,21,.55); border-radius:50%; box-shadow:0 0 18px rgba(250,204,21,.13),inset 0 0 18px rgba(250,204,21,.08); transform:translate(-50%,-50%) scale(.75); opacity:0; animation:splash-orbit-in .85s ease-out .35s both,splash-orbit-spin 8s linear .35s infinite; }
  .splash-data-orbit:before,.splash-data-orbit:after { content:""; position:absolute; inset:12%; border:1px dashed rgba(255,224,112,.48); border-radius:50%; transform:rotateX(62deg) rotateZ(24deg); }
  .splash-data-orbit:after { inset:0; border-style:solid; transform:rotateX(68deg) rotateZ(-28deg); }
  .splash-ball { position:absolute; left:9%; top:66%; z-index:2; font-size:clamp(2.2rem,7vw,3.8rem); filter:drop-shadow(0 0 10px rgba(250,204,21,.65)) drop-shadow(0 8px 4px #0008); animation:splash-shot 1.55s cubic-bezier(.2,.72,.25,1) .18s forwards; }
  .splash-brand { position:relative; z-index:3; margin-top:25px; font-size:clamp(1.8rem,6vw,3.5rem); font-weight:950; letter-spacing:clamp(.08em,.16em,.16em); text-align:center; opacity:0; transform:translateY(18px) scale(.86); background:linear-gradient(105deg,#8a5a10 0%,#f9df82 18%,#fff3b0 32%,#c58a19 48%,#fff0a0 62%,#a66c0c 80%,#ffe7a0 100%); background-size:220% auto; -webkit-background-clip:text; background-clip:text; color:transparent; -webkit-text-fill-color:transparent; filter:drop-shadow(0 4px 18px rgba(250,204,21,.25)); animation:splash-brand-in .8s cubic-bezier(.16,1,.3,1) 1.45s both,splash-gold-shine 2.2s linear 2.2s infinite; }
  .splash-tagline { position:relative; z-index:3; margin-top:9px; color:#e5dfcb; font-size:clamp(.62rem,2.2vw,.76rem); letter-spacing:clamp(.12em,2vw,.24em); text-align:center; opacity:0; transform:translateY(8px); animation:splash-tag-in .55s ease 1.8s both; }
  .splash-techline { position:absolute; z-index:3; left:50%; bottom:calc(50% - min(39vh,260px)/2 - 27px); transform:translateX(-50%); display:flex; align-items:center; gap:8px; color:#FACC15; font-size:clamp(.55rem,1.8vw,.68rem); font-weight:800; letter-spacing:.2em; white-space:nowrap; opacity:0; animation:splash-tag-in .5s ease 2s both; }
  .splash-techline:before,.splash-techline:after { content:""; width:24px; height:1px; background:#FACC15; box-shadow:0 0 8px #FACC15; }
  @keyframes splash-shot { 0%{left:9%;top:66%;transform:rotate(0) scale(1);opacity:1} 38%{left:48%;top:28%;transform:rotate(330deg) scale(.82);opacity:1} 62%{left:77%;top:40%;transform:rotate(600deg) scale(.62);opacity:1} 76%{left:88%;top:44%;transform:rotate(780deg) scale(.48);opacity:1} 86%{left:94%;top:45%;transform:rotate(900deg) scale(.3);opacity:.95} 100%{left:96%;top:45%;transform:rotate(980deg) scale(.18);opacity:0} }
  @keyframes splash-goal-hit { 0%,65%{box-shadow:0 0 0 rgba(250,204,21,0)} 72%{box-shadow:0 0 34px rgba(250,204,21,.95),0 0 70px rgba(250,204,21,.45)} 100%{box-shadow:0 0 12px rgba(250,204,21,.28)} }
  @keyframes splash-pitch-in { from{opacity:0;transform:perspective(600px) rotateX(15deg) scale(.94)} to{opacity:1;transform:perspective(600px) rotateX(7deg) scale(1)} }
  @keyframes splash-stadium-glow { 0%{opacity:0;transform:scale(1.08)} 35%{opacity:1} 100%{opacity:.82;transform:scale(1)} }
  @keyframes splash-orbit-in { to{opacity:.92;transform:translate(-50%,-50%) scale(1)} }
  @keyframes splash-orbit-spin { to{rotate:360deg} }
  @keyframes splash-brand-in { 0%{opacity:0;transform:translateY(18px) scale(.86);filter:blur(8px) drop-shadow(0 4px 18px rgba(250,204,21,.25))} 70%{opacity:1;transform:translateY(-2px) scale(1.035);filter:blur(0) drop-shadow(0 4px 24px rgba(250,204,21,.48))} 100%{opacity:1;transform:translateY(0) scale(1);filter:blur(0) drop-shadow(0 4px 18px rgba(250,204,21,.25))} }
  @keyframes splash-tag-in { to{opacity:1;transform:translateY(0)} }
  @keyframes splash-gold-shine { to{background-position:-220% center} }
  @keyframes splash-dismiss { 0%,76%{opacity:1;visibility:visible;transform:scale(1);filter:blur(0)} 88%{opacity:1;visibility:visible;transform:scale(1.01);filter:blur(0)} 100%{opacity:0;visibility:hidden;transform:scale(1.04);filter:blur(7px)} }
  @media(max-width:640px) { .splash-pitch { width:min(88vw,520px);height:min(34vh,220px); } .splash-data-orbit { width:min(42vw,150px); } .splash-techline { bottom:calc(50% - min(34vh,220px)/2 - 24px); letter-spacing:.12em; } .splash-brand { margin-top:22px; letter-spacing:.08em; } }
  @media(prefers-reduced-motion:reduce) { .football-splash,.football-splash:before,.splash-pitch,.splash-ball,.splash-goal,.splash-data-orbit,.splash-brand,.splash-tagline,.splash-techline { animation-duration:.01ms !important; animation-delay:0s !important; } }
  /* Header de "En vivo ahora": pill amarilla con ondas y chevrón a la derecha */
  [class*="st-key-live_now_section"] [data-testid="stExpander"] { background:transparent !important; border:0 !important; border-radius:18px !important; }
  /* Toda la sección En vivo alineada al borde izquierdo y usando el ancho disponible */
  [class*="st-key-live_now_section"] { padding-left:0 !important; padding-right:0 !important; margin-left:0 !important; margin-right:0 !important; }
  [class*="st-key-live_now_section"] > div { gap:0 !important; row-gap:0 !important; }
  [class*="st-key-live_now_section"] > div > [data-testid="stExpander"] { width:100% !important; max-width:100% !important; margin-left:0 !important; margin-right:0 !important; }
  [class*="st-key-live_now_section"] > div > [data-testid="stExpander"] > details > summary { min-height:68px !important; display:flex !important; flex-direction:row-reverse !important; justify-content:space-between !important; align-items:center !important; gap:12px !important; padding:12px 16px 12px 20px !important; border:1px solid #34363D !important; border-radius:20px !important; background:#0B0D10 !important; }
  [class*="st-key-live_now_section"] > div > [data-testid="stExpander"] > details > summary [data-testid="stExpanderToggleIcon"] { display:none !important; }
  [class*="st-key-live_now_section"] > div > [data-testid="stExpander"] > details > summary::after { content:"◖))  ﹀"; display:flex; align-items:center; justify-content:center; min-width:108px; height:48px; padding:0 14px; border-radius:28px; background:#FACC15; color:#111419; font-size:23px; font-weight:700; letter-spacing:1px; box-sizing:border-box; }
  [class*="st-key-live_now_section"] > div > [data-testid="stExpander"] > details[open] > summary::after { content:"◖))  ⌃"; }
  [class*="st-key-live_now_section"] > div > [data-testid="stExpander"] > details > summary p { color:#FACC15 !important; font-size:clamp(1.2rem,3.8vw,1.8rem) !important; font-weight:750 !important; margin:0 !important; }
  /* Encabezados de ligas: selector basado en expanders anidados dentro de En vivo.
     Evita depender de la clase key que Streamlit cambia según la versión. */
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] > details > summary {
    width:100% !important; box-sizing:border-box !important;
  }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] > details > summary [data-testid="stMarkdownContainer"] {
    display:block !important; width:100% !important; min-width:0 !important; flex:1 1 auto !important;
  }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] > details > summary [data-testid="stMarkdownContainer"] p {
    display:flex !important; align-items:center !important; gap:8px !important;
    width:100% !important; min-width:0 !important; box-sizing:border-box !important;
  }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] > details > summary [data-testid="stMarkdownContainer"] p > strong:last-of-type {
    margin-left:auto !important; padding-left:16px !important; white-space:nowrap !important;
    flex:0 0 auto !important;
  }
  /* Resalte discreto de toda la fila al pasar el cursor, no solo de la flecha. */
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] > details > summary {
    transition:background-color .18s ease,border-color .18s ease,box-shadow .18s ease !important;
  }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] > details > summary:hover {
    background:#171A20 !important; border-color:#7C681F !important;
    box-shadow:inset 3px 0 0 #B89527,0 0 7px rgba(250,204,21,.07) !important;
  }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] > details > summary:hover p {
    color:#FFE566 !important;
  }
  /* Filas de ligas y partidos alineadas al borde izquierdo, sin huecos de los contenedores Streamlit */
  [class*="st-key-live_now_section"] [data-testid="stExpander"] details[open] > div,
  [class*="st-key-live_now_section"] [data-testid="stExpander"] details[open] > div > [data-testid="stVerticalBlock"] { padding:0 !important; margin:0 !important; gap:0 !important; row-gap:0 !important; }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stVerticalBlock"] { gap:0 !important; row-gap:0 !important; }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stElementContainer"] { margin:0 !important; padding:0 !important; }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] { width:100% !important; max-width:100% !important; margin:0 !important; padding:0 !important; }
  /* Filas de ligas: compactas, separadas y sin bordes dobles visuales. */
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] summary {
    min-height:44px !important; padding:6px 12px !important; box-sizing:border-box !important;
    border:1px solid #343840 !important; border-radius:9px !important;
    background:linear-gradient(100deg,#101216,#0B0D10) !important;
    transition:background .18s ease,border-color .18s ease,box-shadow .18s ease !important;
  }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] details { margin:0 !important; padding:0 !important; }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] + [data-testid="stExpander"] { margin-top:3px !important; }
  /* Quitar el espacio que Streamlit reserva entre expander de ligas */
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] [data-testid="stVerticalBlock"] { gap:0 !important; row-gap:0 !important; }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] [data-testid="stElementContainer"] { margin-block:0 !important; padding-block:0 !important; }
  /* Filas de partidos dentro de cada liga: pegadas entre sí y sin márgenes del wrapper */
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] [data-testid="stExpander"] { display:block !important; margin:0 !important; padding:0 !important; width:100% !important; max-width:100% !important; }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] [data-testid="stElementContainer"]:has(> [data-testid="stExpander"]) { margin:0 !important; padding:0 !important; }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"] { margin:0 !important; padding:0 !important; }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] [data-testid="stExpander"] details { margin:0 !important; padding:0 !important; }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] [data-testid="stExpander"] summary { min-height:34px !important; margin:0 !important; padding:3px 8px !important; border-radius:5px !important; }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] [data-testid="stExpander"] + [data-testid="stExpander"] { margin-top:-5px !important; }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] [data-testid="stExpander"] [data-testid="stVerticalBlock"] { gap:0 !important; row-gap:0 !important; }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] [data-testid="stExpander"] [data-testid="stElementContainer"] { margin-block:0 !important; padding-block:0 !important; }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] summary::after { content:none !important; display:none !important; }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] summary [data-testid="stExpanderToggleIcon"] { display:flex !important; color:#FACC15 !important; }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] summary p { color:#E5E7EB !important; font-size:clamp(.9rem,3vw,1.05rem) !important; font-weight:650 !important; margin:0 !important; line-height:1.25 !important; }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] details[open] > div { padding-top:5px !important; }
  @media(max-width:640px) {
    [class*="st-key-live_now_section"] { padding-left:0 !important; padding-right:0 !important; margin-left:0 !important; margin-right:0 !important; }
    [class*="st-key-live_now_section"] > div > [data-testid="stExpander"] { width:100% !important; max-width:100% !important; margin-left:0 !important; margin-right:0 !important; }
    [class*="st-key-live_now_section"] > div > [data-testid="stExpander"] > details > summary { min-height:58px !important; padding:8px 10px 8px 14px !important; }
    [class*="st-key-live_now_section"] > div > [data-testid="stExpander"] > details > summary::after { min-width:78px; height:40px; font-size:19px; padding:0 9px; }
    [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] { width:100% !important; max-width:100% !important; margin:0 !important; padding:0 !important; }
    [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] summary { min-height:34px !important; padding:3px 10px !important; border-radius:4px !important; }
    [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] + [data-testid="stExpander"] { margin-top:-7px !important; }
    [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] [data-testid="stVerticalBlock"] { gap:0 !important; row-gap:0 !important; }
    [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] [data-testid="stElementContainer"] { margin-block:0 !important; padding-block:0 !important; }
    [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] [data-testid="stExpander"] { margin:0 !important; padding:0 !important; width:100% !important; max-width:100% !important; }
    [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] [data-testid="stExpander"] summary { min-height:32px !important; margin:0 !important; padding:2px 7px !important; border-radius:4px !important; }
    [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] [data-testid="stExpander"] + [data-testid="stExpander"] { margin-top:-5px !important; }
    [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] [data-testid="stExpander"] [data-testid="stVerticalBlock"] { gap:0 !important; row-gap:0 !important; }
    [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] [data-testid="stExpander"] [data-testid="stElementContainer"] { margin-block:0 !important; padding-block:0 !important; }
  }
  /* Live section header and compact team crests in fixture rows */
  [data-testid="stExpander"] summary img { width:20px !important; height:20px !important; object-fit:contain !important; vertical-align:middle !important; margin:0 3px !important; }
  [data-testid="stExpander"] summary p { display:flex; align-items:center; flex-wrap:wrap; gap:4px; }
    [data-testid="stTabs"] button[role="tab"] { color: #D4D4D8; font-weight: 650; }
  [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    color: #FACC15; border-bottom-color: #FACC15;
  }
  [data-testid="stDataFrame"] { border: 1px solid #3A3426; border-radius: 10px; overflow: hidden; }
  [data-testid="stExpander"] { background: #15191F; border: 1px solid #3A3426; border-radius: 12px; }
  hr { border-color: #38342B; }
  .brand-header { display:block; padding:15px 20px 12px; margin:0 0 14px 0; background:#0B0D10; border:1px solid #34363B; border-radius:22px; color:#F4F4F5; }
  /* Cabecera global: siempre por encima del menú lateral, sin quedar recortada. */
  .brand-header {
    position:fixed !important;
    top:54px !important;
    left:0 !important;
    right:0 !important;
    z-index:2147483000 !important;
    width:100vw !important;
    max-width:none !important;
    min-height:96px !important;
    box-sizing:border-box !important;
    margin:0 !important;
    padding:10px clamp(18px,3.2vw,48px) !important;
    border:0 !important;
    border-top:1px solid rgba(250,204,21,.42) !important;
    border-bottom:0 !important;
    border-radius:0 !important;
    background:linear-gradient(105deg,#0B0D10 0%,#15171B 48%,#0B0D10 100%) !important;
    box-shadow:0 10px 28px rgba(0,0,0,.42),inset 0 1px 0 rgba(250,204,21,.08),inset 0 -1px 0 rgba(250,204,21,.12) !important;
    backdrop-filter:blur(12px) !important;
    overflow:visible !important;
  }
  .brand-header-main { max-width:none !important; width:100% !important; min-height:72px !important; }
  .brand-mark { box-shadow:0 0 22px rgba(250,204,21,.16) !important; }
  [data-testid="stSidebar"] { z-index:1000 !important; }\n  [data-testid="stSidebar"] > div:first-child { padding-top:126px !important; }
  section.main > div.block-container { padding-top:144px !important; }
  @media(max-width:640px) {
    .brand-header { top:44px !important; min-height:110px !important; padding:7px 10px !important; }
    .brand-header-main { min-height:96px !important; gap:8px !important; align-items:flex-start !important; padding-top:3px !important; }
    .brand-mark { width:42px !important; height:42px !important; flex:0 0 42px !important; border-radius:12px !important; }
    .brand-mark svg { width:25px !important; height:25px !important; }
    .brand-title { font-size:clamp(1.05rem,4.8vw,1.45rem) !important; letter-spacing:0 !important; }
    .brand-subtitle { font-size:.62rem !important; letter-spacing:.7px !important; margin-top:2px !important; }
    .brand-pill { position:absolute !important; right:clamp(112px,20vw,145px) !important; top:-88px !important; transform:translateY(-48px) !important; margin:0 !important; padding:3px 7px !important; font-size:.58rem !important; }
    [data-testid="stSidebar"] { z-index:1000 !important; }\n    [data-testid="stSidebar"] > div:first-child { padding-top:96px !important; }
    section.main > div.block-container { padding-top:214px !important; }
  }
  @media(max-width:360px) {
    .brand-header-main { gap:6px !important; }
    .brand-mark { width:36px !important; height:36px !important; flex-basis:36px !important; }
    .brand-mark svg { width:21px !important; height:21px !important; }
    .brand-title { font-size:1rem !important; }
    .brand-subtitle { font-size:.55rem !important; }
    .brand-pill { padding:3px 5px !important; font-size:.56rem !important; }
  }
  .brand-header-main { display:flex; align-items:center; gap:14px; min-width:0; }
  .brand-mark { width:60px; height:60px; flex:0 0 60px; display:flex; align-items:center; justify-content:center; background:#FACC15; border:1px solid #FFE566; border-radius:18px; box-shadow:none; color:#0B0D10; }
  .brand-mark svg { width:34px; height:34px; }
  .brand-wordmark { min-width:0; }
  .brand-title { font-size:clamp(1.45rem,3.8vw,2.2rem); line-height:1.12; letter-spacing:.5px; font-weight:600; color:#F4F4F5; white-space:nowrap; }
  .brand-title span { color:#FACC15; }
  .brand-subtitle { color:#A1A1AA; font-size:clamp(.78rem,2vw,1.1rem); letter-spacing:1.5px; margin-top:4px; white-space:nowrap; }
  .brand-pill { position:absolute !important; right:145px !important; top:62px !important; margin:0 !important; white-space:nowrap; color:#22C55E; border:1px solid #103B25; background:#062719; border-radius:999px; padding:6px 11px; font-size:.78rem; font-weight:700; }
  .brand-divider { height:1px; background:#292B30; margin:10px 0 8px; }
  .brand-update { display:flex; align-items:center; gap:9px; min-width:0; min-height:34px; padding:5px 9px; border:1px solid #2C2A20; border-radius:10px; background:linear-gradient(90deg,#141610,#101216); transform-origin:center left; }
  .brand-update-intro { animation:update-arrive .9s cubic-bezier(.16,1,.3,1) 5.75s both; }
  .brand-clock { color:#FACC15; width:20px; height:20px; flex:0 0 20px; }
  .brand-update-copy { min-width:0; flex:1; display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
  .brand-update-label { color:#A1A1AA; font-size:.7rem; letter-spacing:1px; font-weight:750; white-space:nowrap; }
  .brand-update-time { color:#F4F4F5; font-size:.82rem; font-weight:600; margin-top:0; overflow-wrap:anywhere; }
  .brand-refresh { color:#FACC15; width:18px; height:18px; flex:0 0 18px; }
  @keyframes update-arrive { 0%{opacity:0;transform:translateY(-5px) scale(.96);filter:blur(2px)} 100%{opacity:1;transform:translateY(0) scale(1);filter:blur(0)} }
  .update-toast { position:fixed; z-index:1000001; left:50%; top:43%; width:min(88vw,370px); display:flex; align-items:center; gap:12px; padding:16px 42px 16px 17px; border:1px solid rgba(250,204,21,.7); border-radius:16px; background:linear-gradient(145deg,rgba(30,31,29,.98),rgba(10,12,14,.98)); box-shadow:0 18px 65px rgba(0,0,0,.72),0 0 30px rgba(250,204,21,.16); color:#F4F4F5; opacity:0; transform:translate(-50%,18px) scale(.9); animation:update-toast-life .7s cubic-bezier(.2,.8,.2,1) 5.8s forwards; }
  .update-toast-icon { display:flex;align-items:center;justify-content:center;width:42px;height:42px;flex:0 0 42px;border-radius:12px;background:rgba(250,204,21,.12);color:#FACC15;font-size:30px; }
  .update-toast-title { color:#FACC15;font-size:.72rem;font-weight:850;letter-spacing:1.2px; }
  .update-toast-time { margin-top:4px;font-size:.92rem;font-weight:650; }
  .update-toast-check { margin-left:auto;color:#4ADE80;font-size:1.25rem;font-weight:900; }
  .update-toast-toggle { position:fixed; width:1px; height:1px; opacity:0; pointer-events:none; }
  .update-toast-toggle:checked + .update-toast { display:none !important; }
  .update-toast-close { position:absolute; top:7px; right:8px; width:28px; height:28px; display:flex;align-items:center;justify-content:center; border:1px solid #49402A; border-radius:8px; background:#FACC15; color:#111419; font-size:20px; line-height:1; cursor:pointer; padding:0; }
  .update-toast-close:hover { background:#FFE566; color:#111419; border-color:#FFE566; }
  @keyframes update-toast-life { 0%{opacity:0;transform:translate(-50%,18px) scale(.9);filter:blur(5px)} 70%{opacity:1;transform:translate(-50%,0) scale(1.03);filter:blur(0)} 100%{opacity:1;transform:translate(-50%,0) scale(1);filter:blur(0)} }
  @media(max-width:640px) { .brand-header { padding:12px 12px 10px; border-radius:17px; } .brand-header-main { gap:10px; } .brand-mark { width:46px; height:46px; flex-basis:46px; border-radius:13px; } .brand-mark svg { width:27px; height:27px; } .brand-title { font-size:clamp(1.2rem,5vw,1.7rem); } .brand-subtitle { font-size:.68rem; letter-spacing:1px; } .brand-pill { padding:5px 8px; font-size:.68rem; } .brand-update { gap:7px; padding:5px 7px; } .brand-update-copy { gap:5px 8px; } .brand-update-label { font-size:.62rem; } .brand-update-time { font-size:.74rem; } }
  .loading-brand { display:flex; align-items:center; gap:12px; padding:14px; margin:8px 0; border:1px solid #393326; border-radius:14px; background:linear-gradient(120deg,#171B21,#101216); }
  .loading-orbit { width:36px; height:36px; border:3px solid #393326; border-top-color:#FACC15; border-right-color:#FACC15; border-radius:50%; animation:lab-spin .8s linear infinite; flex:0 0 36px; }
  @keyframes lab-spin { to {transform:rotate(360deg);} }
  .loading-title { color:#FACC15; font-weight:800; letter-spacing:.5px; }
  .loading-subtitle { color:#A1A1AA; font-size:12px; margin-top:3px; }
  [data-testid="stExpander"] summary p { font-weight:700; }
  .signal-card { animation:matchFlipIn .38s cubic-bezier(.2,.75,.25,1) both; margin:.65rem 0 1rem; padding:1.15rem 1.2rem; border-radius:18px; border:1px solid #FACC15; background:radial-gradient(circle at 92% 8%,rgba(250,204,21,.18),transparent 34%),linear-gradient(135deg,#242014 0%,#171B21 58%,#111419 100%); box-shadow:0 8px 28px rgba(0,0,0,.24); }
  .signal-kicker { color:#FACC15; font-size:.76rem; font-weight:850; letter-spacing:1.4px; text-transform:uppercase; }
  .signal-title { color:#F4F4F5; font-size:1.12rem; font-weight:750; margin-top:.35rem; }
  .signal-pick { color:#FACC15; font-size:clamp(1.8rem,5vw,2.65rem); font-weight:900; line-height:1.15; margin:.45rem 0; }
  .signal-meta { color:#D4D4D8; font-size:.82rem; margin-top:.4rem; }
  .tip-section-heading { display:flex; align-items:center; gap:9px; margin:1.1rem 0 .65rem; color:#F4F4F5; font-size:clamp(1.05rem,3.4vw,1.35rem); font-weight:850; letter-spacing:.35px; }
  .tip-heading-icon { color:#FACC15; font-size:1.5rem; text-shadow:0 0 12px rgba(250,204,21,.35); }
  .tip-heading-status { margin-left:auto; padding:4px 8px; border:1px solid rgba(250,204,21,.4); border-radius:999px; color:#FACC15; font-size:.62rem; font-weight:800; letter-spacing:1px; white-space:nowrap; }
  .risk-heading .tip-heading-icon { color:#FFE566; }
  .tip-card { animation:matchFlipIn .38s cubic-bezier(.2,.75,.25,1) both; margin:.55rem 0 1rem; padding:1.05rem 1.1rem; border-radius:18px; border:1.5px solid #FACC15; background:radial-gradient(circle at 92% 8%,rgba(250,204,21,.15),transparent 36%),linear-gradient(135deg,#242014 0%,#171B21 58%,#111419 100%); box-shadow:0 8px 26px rgba(0,0,0,.25),0 0 0 1px rgba(250,204,21,.06); }
  .risk-tip-card { border-color:#FFE566; background:radial-gradient(circle at 92% 8%,rgba(255,229,102,.13),transparent 36%),linear-gradient(135deg,#252216 0%,#171B21 58%,#111419 100%); }
  .tip-card-label { color:#FACC15; font-size:.72rem; font-weight:900; letter-spacing:1.5px; text-transform:uppercase; }
  .risk-tip-card .tip-card-label { color:#FFE566; }
  .tip-card-title { color:#FFFFFF; font-size:clamp(1.15rem,3.8vw,1.5rem); font-weight:850; line-height:1.3; margin:.45rem 0 .55rem; overflow-wrap:anywhere; }
  .tip-card-meta { color:#FACC15; font-size:.84rem; font-weight:650; line-height:1.5; }
  .risk-tip-card .tip-card-meta { color:#FFE566; }
  .tip-card-empty .tip-card-title { color:#F4F4F5; font-size:1.05rem; }
  .tip-card-empty .tip-card-meta { color:#D4D4D8; font-weight:500; }
  @media(max-width:640px) { .tip-card { padding:.95rem; } .tip-card-meta { font-size:.78rem; } .tip-heading-status { font-size:.55rem; padding:4px 6px; } }
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

  .live-stats-panel { margin:.65rem 0 1rem; overflow:hidden; border:1px solid #E9BD26; border-radius:17px; background:radial-gradient(ellipse at 50% 0%,#29230E 0%,#101216 42%,#080A0D 100%); box-shadow:0 0 0 1px #FACC1520,0 10px 30px #0007; color:#F4F4F5; }
  .live-stats-heading { display:flex; align-items:center; gap:10px; padding:13px 14px 10px; color:#FFD43B; font-weight:900; font-size:1.08rem; border-bottom:1px solid #8A6A16; text-shadow:0 0 12px #FACC1530; }
  .live-stats-heading-icon { color:#FFD43B; letter-spacing:-3px; font-size:1.1rem; }
  .live-stats-live { margin-left:auto; display:flex; align-items:center; gap:5px; white-space:nowrap; color:#FF6969; font-size:.62rem; font-weight:900; }
  .live-stats-live i { width:7px; height:7px; display:inline-block; border-radius:50%; background:#FF4545; box-shadow:0 0 9px #FF4545; }
  .live-stats-scoreboard { padding:12px 12px 14px; background:linear-gradient(180deg,#141820,#0A0C10); }
  .live-stats-league { color:#C7CBD3; font-size:.68rem; font-weight:850; text-align:center; letter-spacing:.6px; text-transform:uppercase; margin-bottom:12px; }
  .live-stats-league span { color:#FACC15; padding:0 4px; }
  .live-stats-teams { display:grid; grid-template-columns:minmax(0,1fr) auto minmax(0,1fr); align-items:center; gap:7px; }
  .live-stats-team { display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; gap:7px; min-width:0; font-size:.78rem; }
  .live-stats-team img { width:52px; height:52px; object-fit:contain; filter:drop-shadow(0 3px 7px #0009); }
  .live-stats-team strong { line-height:1.2; overflow-wrap:anywhere; }
  .stats-team-fallback { font-size:40px; line-height:52px; }
  .live-stats-score { background:#050608; color:#FFD52E; border:1px solid #4B4224; border-radius:11px; padding:7px 11px; font-size:1.7rem; font-weight:950; white-space:nowrap; text-shadow:0 0 14px #FACC1533; }
  .live-stats-pitch { position:relative; height:190px; margin-top:17px; overflow:hidden; border:2px solid #A8E47A; border-radius:8px; background:repeating-linear-gradient(90deg,#247A24 0,#247A24 12.5%,#2C8B2A 12.5%,#2C8B2A 25%); box-shadow:inset 0 0 22px #0005; }
  .live-stats-pitch:before { content:""; position:absolute; inset:10px; border:1.5px solid #DFFFD4; }
  .pitch-half { position:absolute; top:10px; bottom:10px; left:50%; border-left:1.5px solid #DFFFD4; }
  .pitch-circle { position:absolute; width:68px; height:68px; left:50%; top:50%; transform:translate(-50%,-50%); border:1.5px solid #DFFFD4; border-radius:50%; }
  .pitch-box { position:absolute; top:34%; width:14%; height:32%; border:1.5px solid #DFFFD4; }
  .pitch-box-left { left:10px; border-left:0; } .pitch-box-right { right:10px; border-right:0; }
  .pitch-minute { position:absolute; top:7px; left:50%; transform:translateX(-50%); background:#111A13E8; border:1px solid #A8E47A; border-radius:20px; padding:3px 11px; font-size:.72rem; font-weight:900; }
  .pitch-score { position:absolute; top:50%; left:50%; transform:translate(-50%,-50%); background:#080B0DEB; border:1px solid #FACC15; border-radius:9px; padding:4px 12px; color:#FFD52E; font-size:1.3rem; font-weight:950; }
  .pitch-team { position:absolute; top:57%; display:flex; flex-direction:column; align-items:center; gap:3px; width:36%; font-size:.65rem; font-weight:850; text-align:center; }
  .pitch-team img { width:43px; height:43px; object-fit:contain; filter:drop-shadow(0 2px 4px #0009); }
  .pitch-team span { max-width:100%; overflow-wrap:anywhere; background:#071009D9; border-radius:7px; padding:3px 5px; }
  .pitch-team-left { left:4%; } .pitch-team-right { right:4%; }
  .live-stats-metrics { padding:7px 13px 14px; }
  .live-stat-row { padding:7px 0 5px; }
  .live-stat-values { display:grid; grid-template-columns:38px minmax(0,1fr) 38px; gap:5px; align-items:center; font-size:.78rem; }
  .live-stat-values strong:first-child { text-align:left; } .live-stat-values strong:last-child { text-align:right; }
  .live-stat-values strong { color:#F8FAFC; font-weight:900; }
  .live-stat-values span { text-align:center; color:#D4D4D8; }
  .live-stat-track { height:7px; display:flex; gap:3px; margin-top:5px; border-radius:99px; overflow:hidden; background:#333946; }
  .live-stat-home { display:block; height:100%; border-radius:99px; background:linear-gradient(90deg,#D8A90A,#FFE34D); box-shadow:0 0 8px #FACC1544; }
  .live-stat-away { display:block; height:100%; margin-left:auto; border-radius:99px; background:linear-gradient(90deg,#69758B,#A8B0C0); }
  @media (max-width:420px) { .live-stats-heading {font-size:.95rem;padding:11px;} .live-stats-team img {width:39px;height:39px;} .live-stats-score {font-size:1.35rem;padding:6px 8px;} .live-stats-pitch {height:160px;} .pitch-team img {width:34px;height:34px;} .live-stats-metrics {padding:6px 9px 11px;} .live-stat-values {grid-template-columns:32px minmax(0,1fr) 32px;font-size:.69rem;gap:3px;} }


  [class*="st-key-main_stats_"] button, [class*="st-key-main_h2h_"] button, [class*="st-key-main_market_"] button { min-height:3.4rem; white-space:normal; line-height:1.15; padding:.45rem .3rem; border-radius:12px; border:1px solid #49402A; background:linear-gradient(145deg,#20252D,#111419); color:#E5E7EB; box-shadow:inset 0 1px 0 #ffffff0b; transition:transform .18s ease, background .22s ease, border-color .22s ease, box-shadow .22s ease; }
  /* Keep the four match actions on one horizontal row, including narrow mobile screens. */
  [data-testid="stHorizontalBlock"]:has([class*="st-key-main_stats_"]) {
    display:grid !important; grid-template-columns:repeat(4,minmax(0,1fr)) !important;
    grid-auto-flow:column !important; align-items:stretch !important; gap:5px !important;
    width:100% !important; max-width:100% !important; min-width:0 !important;
    box-sizing:border-box !important; overflow:hidden !important;
  }
  [data-testid="stHorizontalBlock"]:has([class*="st-key-main_stats_"]) > [data-testid="column"] {
    display:block !important; min-width:0 !important; width:100% !important; max-width:100% !important;
    flex:none !important; padding:0 !important; margin:0 !important; box-sizing:border-box !important;
  }
  [data-testid="stHorizontalBlock"]:has([class*="st-key-main_stats_"]) [data-testid="stButton"],
  [data-testid="stHorizontalBlock"]:has([class*="st-key-main_stats_"]) [class*="st-key-main_stats_"],
  [data-testid="stHorizontalBlock"]:has([class*="st-key-main_stats_"]) [class*="st-key-main_market_"],
  [data-testid="stHorizontalBlock"]:has([class*="st-key-main_stats_"]) [class*="st-key-main_h2h_"] { min-width:0 !important; width:100% !important; max-width:100% !important; }
  [data-testid="stHorizontalBlock"]:has([class*="st-key-main_stats_"]) button {
    box-sizing:border-box !important; min-width:0 !important; width:100% !important; max-width:100% !important;
    min-height:2rem !important; height:2rem !important; padding:0 !important;
    font-size:clamp(1rem,4.2vw,1.45rem) !important; font-weight:900 !important; text-shadow:0 0 8px #FACC1580 !important;
    line-height:1.05 !important; white-space:normal !important; overflow-wrap:anywhere !important;
    border:1px solid #B58A19 !important; border-radius:9px !important;
    background:linear-gradient(145deg,#1A1B1F,#0B0D10) !important; color:#F6D365 !important;
    box-shadow:inset 0 0 0 1px #FACC1522,0 0 12px #FACC1517 !important;
  }
  [class*="st-key-main_stats_"] button:hover, [class*="st-key-main_h2h_"] button:hover, [class*="st-key-main_market_"] button:hover { transform:translateY(-2px); border-color:#FACC15; background:linear-gradient(145deg,#3B3216,#211D12); color:#FFE566; box-shadow:0 5px 16px #0006,0 0 14px #FACC1517; }
  [class*="st-key-main_stats_"] button:active, [class*="st-key-main_h2h_"] button:active, [class*="st-key-main_market_"] button:active { transform:scale(.98) rotateX(3deg); background:#FACC15; color:#101216; }
  [class*="st-key-main_stats_"] button[kind="secondary"], [class*="st-key-main_h2h_"] button[kind="secondary"], [class*="st-key-main_market_"] button[kind="secondary"] { background:linear-gradient(145deg,#20252D,#111419) !important; color:#E5E7EB !important; border-color:#49402A !important; }
  [class*="st-key-main_stats_"] button[kind="primary"], [class*="st-key-main_h2h_"] button[kind="primary"], [class*="st-key-main_market_"] button[kind="primary"] { background:#FACC15 !important; color:#101216 !important; border-color:#FFE566 !important; box-shadow:0 0 0 1px #FACC1544,0 5px 18px #FACC1520; }
  .match-analysis-panel { animation:matchFlipIn .38s cubic-bezier(.2,.75,.25,1) both; border:1px solid #5B4A19; border-radius:15px; padding:14px; margin:.65rem 0 1rem; background:radial-gradient(circle at 100% 0,rgba(250,204,21,.15),transparent 38%),linear-gradient(140deg,#242014,#171B21 55%,#101216); box-shadow:0 9px 28px #0005; transform-origin:top center; }
  .match-analysis-kicker { color:#FACC15; font-size:.72rem; font-weight:900; letter-spacing:1.2px; text-transform:uppercase; }
  .match-analysis-title { color:#F4F4F5; font-size:1.08rem; font-weight:850; margin:.25rem 0 .65rem; }
  .goals-section-title {
    display:flex !important; align-items:center !important; gap:9px !important;
    margin:8px 0 18px !important; padding:0 !important; width:100% !important;
    border:0 !important; border-bottom:0 !important; box-shadow:none !important;
    color:#F1F3F6 !important; font-size:clamp(1.28rem,2.35vw,1.58rem) !important;
    font-weight:800 !important; letter-spacing:.005em !important; line-height:1.25 !important;
    text-shadow:none !important;
  }
  .goals-section-title::first-letter { font-size:.94em !important; }
  .h2h-match-row { display:grid; grid-template-columns:82px minmax(0,1fr) 70px minmax(0,1fr); gap:8px; align-items:center; padding:9px 4px; border-bottom:1px solid #34302A; font-size:.8rem; }
  .h2h-team { display:flex; align-items:center; gap:6px; min-width:0; overflow-wrap:anywhere; }
  .h2h-team img { width:22px; height:22px; object-fit:contain; flex:0 0 22px; }
  .h2h-match-row, .corner-h2h-row { animation:matchFlipIn .32s ease both; }
  .corner-h2h-row { display:grid; grid-template-columns:82px minmax(0,1fr) 70px minmax(0,1fr) 88px; gap:8px; align-items:center; padding:9px 4px; border-bottom:1px solid #34302A; font-size:.8rem; }
  .corner-history-grid {grid-template-columns:76px minmax(0,1fr) 48px minmax(0,1fr) 48px 48px 48px 58px;}
  .corner-h2h-value { color:#FACC15; font-weight:850; text-align:center; white-space:nowrap; }
  .h2h-score { text-align:center; color:#FACC15; font-weight:900; white-space:nowrap; }
  @keyframes matchFlipIn { from {opacity:0; transform:perspective(900px) rotateX(-8deg) translateY(-7px)} to {opacity:1; transform:perspective(900px) rotateX(0) translateY(0)} }
  @media(max-width:620px) {
    .match-action-grid {grid-template-columns:repeat(2,minmax(0,1fr));}
    .h2h-match-row {grid-template-columns:65px minmax(0,1fr) 48px minmax(0,1fr);font-size:.7rem;gap:4px;}
    /* Histórico de córners en móvil: ocho columnas compactas, incluyendo PT y ST. */
    .corner-h2h-row.corner-history-grid {grid-template-columns:48px minmax(0,1fr) 20px minmax(0,1fr) 20px 25px 25px 29px;column-gap:2px;row-gap:0;padding:7px 3px;font-size:.60rem;line-height:1.25;min-width:0;width:100%;box-sizing:border-box;}
    .corner-h2h-row.corner-history-grid > span {min-width:0;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;box-sizing:border-box;}
    .corner-h2h-row.corner-history-grid > span:first-child {font-size:.57rem;}
    .corner-h2h-row.corner-history-grid .h2h-team {display:flex;align-items:center;gap:3px;min-width:0;overflow:hidden;white-space:nowrap;}
    .corner-h2h-row.corner-history-grid .h2h-team img {width:13px;height:13px;flex:0 0 13px;object-fit:contain;}
    .corner-h2h-row.corner-history-grid .corner-h2h-value {text-align:center;font-size:.62rem;}
    .corner-h2h-row.corner-history-grid.corner-history-header {font-size:.55rem;padding-left:4px;padding-right:4px;}
    .corner-h2h-row.corner-history-grid.corner-history-header > span {overflow:visible;text-overflow:clip;white-space:normal;line-height:1.1;}
    .corner-h2h-row.corner-history-grid.corner-history-header > span:nth-child(3),
    .corner-h2h-row.corner-history-grid.corner-history-header > span:nth-child(5) {font-size:0;}
    .corner-h2h-row.corner-history-grid.corner-history-header > span:nth-child(3)::after {content:"C-L";font-size:.56rem;}
    .corner-h2h-row.corner-history-grid.corner-history-header > span:nth-child(5)::after {content:"C-V";font-size:.56rem;}
    .corner-h2h-row.corner-history-grid.corner-history-header > span:nth-child(6),
    .corner-h2h-row.corner-history-grid.corner-history-header > span:nth-child(7),
    .corner-h2h-row.corner-history-grid.corner-history-header > span:nth-child(8) {font-size:0;}
    .corner-h2h-row.corner-history-grid.corner-history-header > span:nth-child(6)::after {content:"PT";font-size:.56rem;}
    .corner-h2h-row.corner-history-grid.corner-history-header > span:nth-child(7)::after {content:"ST";font-size:.56rem;}
    .corner-h2h-row.corner-history-grid.corner-history-header > span:nth-child(8)::after {content:"Total";font-size:.56rem;}
    .corner-h2h-total-label {display:none !important;}
  }

  @media (max-width: 420px) { .fixture-hero-team {font-size:.72rem;} .fixture-hero-team img {width:31px;height:31px;} .fixture-hero-score {font-size:1.25rem;padding:6px 9px;} }

  .scan-action {display:flex;align-items:center;gap:10px;padding:10px 13px;margin:.3rem 0 .6rem;border:1px solid #51451E;border-radius:13px;background:linear-gradient(120deg,#171B21,#101216);color:#FACC15;font-weight:800;}
  .scan-ball {display:inline-block;font-size:1.3rem;animation:ball-bob 1.2s ease-in-out infinite;}
  @keyframes ball-bob {0%,100%{transform:translateY(0) rotate(0)}50%{transform:translateY(-3px) rotate(18deg)}}
  .history-table { width:100%; border-collapse:separate; border-spacing:0; border:1px solid #4A4024; border-radius:12px; overflow:hidden; font-size:.9rem; margin:.5rem 0 1rem; }
  .history-table th { background:#FACC15; color:#151515; text-align:left; padding:.72rem .65rem; font-weight:850; }
  .history-table td { background:#15191F; color:#F4F4F5; padding:.68rem .65rem; border-top:1px solid #34302A; }
  .history-table tr:nth-child(even) td { background:#1B2027; }

  .goal-live-summary { border:1px solid #3C3524; border-left:3px solid #FACC15; border-radius:12px; padding:12px 13px; margin:.65rem 0 .8rem; background:linear-gradient(135deg,#191C22,#101216); }
  .goal-live-summary-title { color:#FACC15; font-weight:900; font-size:.78rem; letter-spacing:1.2px; margin-bottom:6px; }
  .goal-live-summary p { color:#D4D4D8; font-size:.88rem; line-height:1.45; margin:0; }
  .goal-deep-heading { display:block; clear:both; position:relative; z-index:1; color:#FACC15; font-size:.78rem; letter-spacing:1.1px; font-weight:900; margin:1.9rem 0 1.1rem; padding:0 0 .2rem; line-height:1.6; }
  .goal-match-stats-table{box-sizing:border-box;margin:10px 0 13px;padding:0;border:1px solid #3B414D;border-top:2px solid #D6A900;border-radius:13px;background:linear-gradient(155deg,#1B2029 0%,#12161D 100%);overflow:hidden;box-shadow:0 5px 16px rgba(0,0,0,.18)}
  .goal-match-stats-table table{width:100%;border-collapse:separate;border-spacing:0;font-size:12px;color:#E8ECF2;font-variant-numeric:tabular-nums}
  .goal-match-stats-table thead th{padding:11px 9px;background:linear-gradient(180deg,#292F3A,#222833);color:#F4C928;font-size:10px;font-weight:900;letter-spacing:.45px;text-align:center;border-bottom:1px solid #515866;line-height:1.25}
  .goal-match-stats-table thead th:first-child{text-align:left;width:42%}
  .goal-match-stats-table thead th:not(:first-child){width:29%;overflow-wrap:anywhere}
  .goal-stats-team-heading{display:inline-flex;align-items:center;justify-content:center;gap:6px;max-width:100%;vertical-align:middle;white-space:normal}
  .goal-stats-team-score{display:inline-flex;align-items:center;justify-content:center;min-width:22px;height:22px;padding:0 6px;border-radius:6px;background:linear-gradient(180deg,#FFE477,#FACC15);color:#171717;font-size:11px;font-weight:950;line-height:1;box-shadow:0 1px 5px rgba(250,204,21,.22);font-variant-numeric:tabular-nums}

  .goal-stats-scoreboard{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);align-items:start;gap:8px;padding:14px 10px 12px;background:linear-gradient(155deg,#191F29,#11151C);border-bottom:1px solid rgba(214,169,0,.45)}
  .goal-stats-live-team{display:flex;min-width:0;flex-direction:column;align-items:center;text-align:center;gap:6px;color:#F4F6FA}
  .goal-stats-live-team img{width:48px;height:48px;object-fit:contain}
  .goal-stats-live-team strong{font-size:12px;line-height:1.25;overflow-wrap:anywhere}
  .goal-stats-live-score{align-self:start;margin-top:12px;padding:8px 10px;border:1px solid #66551B;border-radius:10px;background:#090C11;color:#FACC15;font-size:22px;font-weight:950;white-space:nowrap;font-variant-numeric:tabular-nums}
  .goal-stats-scorers{width:100%;display:flex;flex-direction:column;gap:5px;margin-top:2px}
  .goal-stats-scorer{font-size:10px;line-height:1.35;color:#D9DEE7;overflow-wrap:anywhere}
  .goal-stats-no-scorer{font-size:10px;color:#8E98A8}
  @media(max-width:480px){.goal-stats-scoreboard{gap:4px;padding:12px 6px}.goal-stats-live-team img{width:39px;height:39px}.goal-stats-live-team strong{font-size:10px}.goal-stats-live-score{font-size:19px;padding:7px 8px}.goal-stats-scorer{font-size:9px}}
  .goal-match-stats-table tbody th,.goal-match-stats-table tbody td{padding:10px 9px;border-bottom:1px solid rgba(148,163,184,.14);line-height:1.25}
  .goal-match-stats-table tbody tr:nth-child(even){background:rgba(255,255,255,.035)}
  .goal-match-stats-table tbody tr:last-child th,.goal-match-stats-table tbody tr:last-child td{border-bottom:0}
  .goal-match-stats-table tbody th{text-align:left;color:#BFC8D5;font-size:11px;font-weight:650}
  .goal-match-stats-table tbody td{text-align:center;color:#F4F6FA;font-size:12px;font-weight:800}
  .goal-match-goals{margin:0 10px 10px;padding:10px 11px;border:1px solid rgba(250,204,21,.2);border-radius:9px;background:rgba(250,204,21,.055);color:#D5DCE6;font-size:11px;line-height:1.6;overflow-wrap:anywhere}
  .goal-match-goals b{color:#F4C928;font-weight:900}
  @media(max-width:480px){.goal-match-stats-table table{font-size:11px}.goal-match-stats-table thead th{padding:10px 6px;font-size:9px}.goal-match-stats-table tbody th,.goal-match-stats-table tbody td{padding:9px 6px}.goal-match-stats-table tbody th{font-size:10px}.goal-match-stats-table tbody td{font-size:11px}}
  [class*="st-key-goal_form_front_"]{box-sizing:border-box;width:100%;padding:8px 0 14px;margin:7px 0 13px;border-bottom:1px solid rgba(250,204,21,.22)}
  [class*="st-key-goal_form_front_"]:last-of-type{margin-bottom:4px;border-bottom:0;padding-bottom:4px}
  .goal-form-card { box-sizing:border-box; border:1px solid #393326; border-radius:11px; padding:12px; margin-top:5px; background:linear-gradient(145deg,#191D24,#101216); min-height:170px; height:100%; }
  .goal-form-back { box-sizing:border-box; border:1px solid #FACC15; border-radius:11px; padding:11px; margin-top:5px; background:linear-gradient(145deg,#20232B,#12151A); min-height:170px; height:100%; }
  @keyframes goal-card-flip-in { 0% { opacity:.15; transform:perspective(900px) rotateY(-180deg) scale(.94); } 70% { opacity:1; transform:perspective(900px) rotateY(12deg) scale(1.01); } 100% { opacity:1; transform:perspective(900px) rotateY(0deg) scale(1); } }
  .goal-form-card, .goal-form-back { animation:goal-card-flip-in .62s cubic-bezier(.2,.75,.25,1) both; transform-origin:center; transform-style:preserve-3d; backface-visibility:visible; }
  [class*="st-key-goal_form_flip_btn_"] button { width:32px !important; min-width:32px !important; height:32px !important; min-height:32px !important; padding:0 !important; border-radius:50% !important; border:1px solid #FACC15 !important; background:radial-gradient(circle at 35% 25%,#FFF1A6 0%,#FACC15 45%,#B77908 100%) !important; color:#171717 !important; font-size:1rem !important; line-height:1 !important; box-shadow:0 0 0 2px #FACC1525,0 0 12px #FACC1545,inset 0 1px 2px #FFF8C5 !important; }
  [class*="st-key-goal_form_flip_btn_"] button:hover { transform:rotate(-10deg) scale(1.08) !important; box-shadow:0 0 0 3px #FACC1535,0 0 17px #FACC1580 !important; }
  @media (prefers-reduced-motion: reduce) { .goal-form-card, .goal-form-back { animation:none; } }
  @media (prefers-reduced-motion: reduce) { .goal-form-card, .goal-form-back { animation:none; } }
  .goal-form-back-title { color:#FACC15; font-size:.72rem; font-weight:900; margin-bottom:8px; line-height:1.35; }
  .goal-form-back { animation:goal-card-flip-in .62s cubic-bezier(.2,.75,.25,1) both; transform-origin:center; }
  .goal-form-match-meta { color:#FACC15; font-size:.68rem; font-weight:800; letter-spacing:.25px; margin:9px 0 5px; white-space:nowrap; }
  .goal-form-team-lines,.goal-form-score-lines {display:flex;flex-direction:column;justify-content:center;gap:5px;min-height:48px}
  .goal-form-team-lines>div {color:#E4E4E7;font-size:.76rem;font-weight:700;line-height:1.3;white-space:nowrap;overflow:hidden;text-overflow:clip}
  .goal-form-score-lines>div {color:#F4F4F5;font-size:.82rem;font-weight:950;line-height:1.3;text-align:center}
  .goal-form-actions {display:flex;justify-content:center;align-items:center;margin:0}
  .goal-form-actions .goal-form-result {margin:0}
  [class*="st-key-goal_timeline_btn_"] {display:flex;justify-content:flex-end;width:100%}
  [class*="st-key-goal_timeline_btn_"] button {margin-left:auto!important}
  .goal-form-result {display:inline-flex;justify-content:center;align-items:center;min-width:22px;padding:3px 6px;border-radius:5px;font-size:.65rem;font-weight:900}
  .goal-form-result-v {color:#FFFFFF;background:#16A34A}
  .goal-form-result-e {color:#FFFFFF;background:#6B7280}
  .goal-form-result-d {color:#FFFFFF;background:#DC2626}
   [class*="st-key-goal_form_back_"]{box-sizing:border-box;border:1px solid #FACC15;border-radius:11px;padding:11px;margin-top:5px;background:linear-gradient(145deg,#20232B,#12151A);min-height:170px;animation:goal-card-flip-in .62s cubic-bezier(.2,.75,.25,1) both;transform-origin:center;transform-style:preserve-3d;backface-visibility:visible}[class*="st-key-goal_timeline_btn_"] button{width:25px!important;min-width:25px!important;height:25px!important;min-height:25px!important;padding:0!important;border-radius:50%!important;border:1px solid #FACC15!important;background:radial-gradient(circle at 35% 25%,#FFF1A6 0%,#FACC15 55%,#9A7000 100%)!important;color:#171717!important;font-size:12px!important;box-shadow:0 0 7px #FACC1545!important}[class*="st-key-goal_timeline_btn_"] button:hover{transform:rotate(-10deg) scale(1.08)!important;box-shadow:0 0 0 3px #FACC1535,0 0 17px #FACC1580!important}.goal-event-timeline{margin:5px 0 12px;padding:8px 10px;border:1px solid rgba(250,204,21,.28);border-radius:11px;background:rgba(17,20,25,.72)}.goal-event-row{display:grid;grid-template-columns:42px 20px minmax(0,1fr) auto;align-items:center;gap:7px;padding:8px 2px;border-bottom:1px solid rgba(255,255,255,.08)}.goal-event-row:last-child{border-bottom:0}.goal-event-minute{color:#FACC15;font-size:.72rem;white-space:nowrap}.goal-event-ball{font-size:14px}.goal-event-info{display:flex;flex-direction:column;min-width:0;gap:2px}.goal-event-info strong{color:#F4F4F5;font-size:.72rem;overflow-wrap:anywhere}.goal-event-info span,.goal-event-info small{color:#A1A1AA;font-size:.62rem;overflow-wrap:anywhere}.goal-event-score{color:#FACC15;font-size:.78rem;white-space:nowrap}
  @media (max-width: 700px) {
    /* En móvil, apilar los dos historiales reales y expandir cada tarjeta. */
    div[data-testid="stHorizontalBlock"]:has([class*="st-key-goal_form_back_"]){flex-direction:column!important;flex-wrap:nowrap!important;align-items:stretch!important;gap:12px!important}
    div[data-testid="stHorizontalBlock"]:has([class*="st-key-goal_form_back_"]) > div[data-testid="column"]{flex:1 1 100%!important;width:100%!important;min-width:100%!important}
    [class*="st-key-goal_form_back_"]{width:100%!important;max-width:100%!important;box-sizing:border-box!important;padding:14px!important}
    .stHorizontalBlock:has(.goal-form-header){flex-wrap:wrap!important;gap:12px!important}
    .stHorizontalBlock:has(.goal-form-header) > [data-testid="column"]{flex:1 1 100%!important;width:100%!important;min-width:100%!important}
    .goal-form-header{gap:11px;margin:3px 0 8px}
    .goal-form-logo{width:42px;height:42px;flex-basis:42px}
    .goal-form-team{font-size:.88rem;line-height:1.25;overflow-wrap:normal;word-break:normal}
    .goal-form-match-meta{font-size:.7rem;margin:10px 0 6px}
    .goal-form-team-lines,.goal-form-score-lines{gap:7px;min-height:52px}
    .goal-form-team-lines>div{font-size:.76rem;line-height:1.35;white-space:nowrap;overflow:hidden;text-overflow:clip}
    .goal-form-score-lines>div{font-size:.86rem}
    .goal-form-actions{justify-content:center}
    [class*="st-key-goal_timeline_btn_"]{display:flex;justify-content:flex-end;width:100%}
    [class*="st-key-goal_timeline_btn_"] button{margin-left:auto!important}
  }
  .goal-form-result { display:inline-flex; justify-content:center; min-width:22px; padding:2px 5px; border-radius:5px; font-size:.65rem; font-weight:900; }
  .goal-form-result-v { color:#FFFFFF; background:#16A34A; }
  .goal-form-result-e { color:#FFFFFF; background:#6B7280; }
  .goal-form-result-d { color:#FFFFFF; background:#DC2626; }
  .goal-form-header { display:flex; align-items:center; gap:10px; margin:2px 0 7px; min-width:0; width:100%; box-sizing:border-box; }
  .goal-form-logo { width:38px; height:38px; object-fit:contain; flex:0 0 38px; }
  .goal-form-team { display:block; flex:1 1 0%; min-width:0; max-width:100%; color:#E4E4E7; font-size:.78rem; font-weight:800; line-height:1.3; white-space:normal; overflow-wrap:break-word; word-break:normal; hyphens:none; }
  .goal-form-record { color:#FACC15; font-size:1.15rem; font-weight:900; margin:4px 0; }
  .goal-form-line { color:#BFC2CA; font-size:.62rem; line-height:1.35; }
  .goal-h2h-summary { margin:.5rem 0; border:1px solid #393326; border-radius:10px; padding:9px 11px; color:#D4D4D8; background:#15191F; font-size:.78rem; line-height:1.5; }
  .goal-last-goal { display:flex; align-items:center; flex-wrap:wrap; gap:8px; margin:1.65rem 0 1rem; padding:12px 14px; border:2px solid #FACC15; border-radius:12px; background:linear-gradient(135deg,rgba(250,204,21,.16),#191C22 52%,#101216); box-shadow:0 0 0 1px rgba(250,204,21,.22),0 0 16px rgba(250,204,21,.16); color:#F4F4F5; font-size:.84rem; line-height:1.5; }
  .goal-last-goal b { color:#FFE566; font-weight:950; letter-spacing:.35px; }
  .goal-last-goal span { display:inline-flex; align-items:center; justify-content:center; min-width:44px; padding:3px 8px; border:1px solid #FACC15; border-radius:7px; background:#FACC15; color:#111419; font-weight:950; font-size:.9rem; }
  @keyframes goal-minute-alarm {
    0%, 100% { opacity:1; transform:scale(1); box-shadow:0 0 0 0 rgba(250,204,21,.42); }
    50% { opacity:.62; transform:scale(.94); box-shadow:0 0 0 5px rgba(250,204,21,0); }
  }
  .goal-last-goal span { animation:goal-minute-alarm 1.15s ease-in-out infinite; transform-origin:center; }
  .corner-total-average { display:flex; align-items:center; flex-wrap:wrap; gap:7px; margin:16px 0 18px; padding:9px 12px; border:2px solid #FACC15; border-radius:12px; background:linear-gradient(135deg,rgba(250,204,21,.16),#191C22 52%,#101216); box-shadow:0 0 0 1px rgba(250,204,21,.22),0 0 16px rgba(250,204,21,.16); color:#F4F4F5; font-size:.84rem; line-height:1.5; width:fit-content; max-width:100%; clear:both; position:relative; }
  .corner-total-average b { color:#FFE566; font-weight:950; letter-spacing:.35px; }
  .corner-total-average span { display:inline-flex; align-items:center; justify-content:center; min-width:44px; padding:4px 9px; border:1px solid #FACC15; border-radius:7px; background:#FACC15; color:#111419; font-weight:950; font-size:.9rem; animation:goal-minute-alarm 1.15s ease-in-out infinite; transform-origin:center; }
  .corner-period-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; width:100%; margin:7px 0 16px; }
  .corner-period-card { min-width:0; padding:10px 11px; border:1px solid #51451D; border-radius:10px; background:linear-gradient(145deg,#1B1E23,#14161B); }
  .corner-period-label { color:#E8CC70; font-size:.68rem; font-weight:850; letter-spacing:.045em; line-height:1.35; }
  .corner-period-value { color:#FFE566; font-size:1.25rem; font-weight:950; line-height:1.35; margin-top:4px; }
  .corner-period-note { color:#AEB3BC; font-size:.65rem; line-height:1.35; margin-top:2px; }
  @media(max-width:390px) { .corner-period-card { padding:9px 8px; } .corner-period-value { font-size:1.1rem; } .corner-period-label { font-size:.62rem; } }
  @media (prefers-reduced-motion: reduce) { .corner-total-average span { animation:none; } }
  @media (prefers-reduced-motion: reduce) {
    .goal-last-goal span { animation:none; }
  }
  .goal-last-goal strong { color:#FFE566; }
  .goal-h2h-summary b { color:#FACC15; }
  .goal-comeback-card { box-sizing:border-box; display:flex; flex-direction:column; gap:6px; width:100%; min-height:126px; height:100%; border:1px solid #393326; border-radius:10px; padding:11px; background:linear-gradient(145deg,#191D24,#12151A); margin:.2rem 0 .45rem; overflow-wrap:anywhere; }
  .goal-comeback-card b { color:#FACC15; font-size:.75rem; line-height:1.35; min-height:1.35em; }
  .goal-comeback-card span { color:#E4E4E7; font-size:.72rem; line-height:1.45; }
  .goal-comeback-card small { color:#9CA3AF; font-size:.62rem; line-height:1.4; margin-top:auto; }
  [data-testid="stHorizontalBlock"]:has(.goal-comeback-card) { align-items:stretch !important; }
  [data-testid="stHorizontalBlock"]:has(.goal-comeback-card) [data-testid="column"] { display:flex !important; align-items:stretch !important; }
  [data-testid="stHorizontalBlock"]:has(.goal-comeback-card) [data-testid="column"] > div { width:100%; }
  .goal-history-wrap { border:1px solid #4A4024; border-radius:12px; overflow:hidden; margin:.6rem 0 1rem; background:#111419; }
  .goal-history-heading { display:flex; justify-content:space-between; align-items:center; gap:8px; padding:9px 10px; color:#FACC15; font-size:.82rem; font-weight:850; background:#191B20; }
  .goal-history-heading span { color:#A1A1AA; font-size:.65rem; font-weight:700; text-transform:uppercase; letter-spacing:.6px; }
  .goal-history-table { width:100%; border-collapse:collapse; font-size:.76rem; table-layout:fixed; }
  .goal-history-table th { background:#FACC15; color:#111; padding:7px 8px; text-align:left; font-weight:900; }
  .goal-history-table td { padding:8px; border-top:1px solid #30343B; background:#15191F; color:#E4E4E7; overflow-wrap:anywhere; line-height:1.25; }
  .goal-history-table tr:nth-child(even) td { background:#1B2027; }
  .goal-history-table th:nth-child(2), .goal-history-table th:nth-child(3), .goal-history-table td:nth-child(2), .goal-history-table td:nth-child(3) { text-align:center; width:19%; }
  @media (max-width:420px) { .goal-history-table {font-size:.68rem;} .goal-history-table th,.goal-history-table td {padding:7px 5px;} .goal-history-table th:nth-child(2),.goal-history-table th:nth-child(3),.goal-history-table td:nth-child(2),.goal-history-table td:nth-child(3) {width:15%;} .goal-live-summary p {font-size:.82rem;} }

  .history-table td:nth-child(2), .history-table td:nth-child(3), .history-table th:nth-child(2), .history-table th:nth-child(3) { text-align:center; }
  @media (max-width: 640px) { .history-table {font-size:.76rem;} .history-table th,.history-table td {padding:.55rem .4rem;} }
  [data-testid="stExpander"] summary:hover { color:#FACC15; }
  div[data-testid="stMetricLabel"] p { color:#A1A1AA !important; font-size: .78rem; }
  div[data-testid="stMetricValue"] { color:#FACC15 !important; }
  @media (max-width: 640px) {
    .block-container {padding-left: .8rem; padding-right: .8rem;}
    .brand-header {padding:12px 12px 9px; border-radius:18px;}
    .brand-header-main {gap:10px;}
    .brand-mark {width:48px;height:48px;flex-basis:48px;border-radius:14px;}
    .brand-mark svg {width:28px;height:28px;}
    .brand-title {font-size:clamp(1.2rem,5vw,1.65rem);letter-spacing:0;}
    .brand-subtitle {font-size:.68rem;margin-top:3px;letter-spacing:1px;}
    .brand-pill {padding:5px 8px;font-size:.66rem;}
    .brand-divider {margin:9px 0 7px;}
    .brand-update {gap:7px;min-height:28px;padding:3px 6px;}
    .brand-clock {width:15px;height:15px;flex-basis:15px;}
    .brand-update-copy {gap:6px;flex-wrap:nowrap;}
    .brand-update-label {font-size:.59rem;letter-spacing:.45px;}
    .brand-update-time {font-size:.7rem;line-height:1.1;white-space:nowrap;}
    .brand-refresh {width:14px;height:14px;flex-basis:14px;}
    h1 {font-size: 1.7rem !important;}
    h2 {font-size: 1.3rem !important;}
  }
  /* Override final para igualar exactamente la escala visual del botón Alertas */
  [class*="st-key-auto_refresh_control_card"] [data-testid="stToggle"] label,
  [class*="st-key-auto_refresh_control_card"] [data-testid="stToggle"] label *,
  [class*="st-key-sound_control_card"] [data-testid="stToggle"] label,
  [class*="st-key-sound_control_card"] [data-testid="stToggle"] label * {
    color:#F4D778 !important;
    -webkit-text-fill-color:#F4D778 !important;
    font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif !important;
    font-size:11px !important;
    font-weight:600 !important;
    line-height:1.1 !important;
    letter-spacing:0 !important;
    text-size-adjust:100% !important;
    -webkit-text-size-adjust:100% !important;
  }
  [class*="st-key-auto_refresh_control_card"] [data-testid="stToggle"] label p,
  [class*="st-key-sound_control_card"] [data-testid="stToggle"] label p {
    margin:0 !important; padding:0 !important;
  }

  /* Corrección definitiva: neutralizar los estilos antiguos que dibujaban tarjetas doradas. */
  [class*="st-key-auto_refresh_control_card"], [class*="st-key-sound_control_card"] {
    width:100% !important; height:22px !important; min-height:22px !important; max-height:22px !important;
    margin:0 !important; padding:0 !important; border:0 !important; border-width:0 !important; border-color:transparent !important;
    border-radius:0 !important; outline:0 !important; background:transparent !important; background-image:none !important;
    box-shadow:none !important; overflow:visible !important; box-sizing:border-box !important;
  }
  [class*="st-key-auto_refresh_control_card"]::before, [class*="st-key-auto_refresh_control_card"]::after,
  [class*="st-key-sound_control_card"]::before, [class*="st-key-sound_control_card"]::after { display:none !important; content:none !important; }
  [class*="st-key-auto_refresh_control_card"] [data-testid="stToggle"], [class*="st-key-sound_control_card"] [data-testid="stToggle"] {
    width:100% !important; height:22px !important; min-height:22px !important; max-height:22px !important; margin:0 !important;
    padding:0 !important; border:0 !important; border-radius:0 !important; background:transparent !important; box-shadow:none !important; overflow:visible !important;
  }
  [class*="st-key-auto_refresh_control_card"] [role="switch"], [class*="st-key-sound_control_card"] [role="switch"] {
    transform:scale(.40) !important; transform-origin:center center !important; border:0 !important; outline:0 !important; box-shadow:none !important;
  }
  [class*="st-key-auto_refresh_control_card"] [data-testid="stToggle"] label, [class*="st-key-sound_control_card"] [data-testid="stToggle"] label,
  [class*="st-key-auto_refresh_control_card"] [data-testid="stToggle"] label *, [class*="st-key-sound_control_card"] [data-testid="stToggle"] label * { font-size:8px !important; line-height:1 !important; font-weight:600 !important; }
  [class*="st-key-auto_refresh_control_card"] [data-testid="stMarkdownContainer"] > div, [class*="st-key-sound_control_card"] [data-testid="stMarkdownContainer"] > div { height:22px !important; min-height:22px !important; font-size:8px !important; line-height:1 !important; display:flex !important; align-items:center !important; }
  /* Cuatro tarjetas de acciones dentro de cada partido, adaptadas a pantallas móviles */
  [class*="st-key-live_match_"] [data-testid="stHorizontalBlock"] {
    display:flex !important; flex-wrap:nowrap !important; gap:.45rem !important; align-items:stretch !important;
  }
  [class*="st-key-live_match_"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
    min-width:0 !important; padding:0 !important; flex:1 1 0 !important;
  }
  [class*="st-key-live_match_"] [data-testid="stButton"] > button {
    width:100% !important; min-width:0 !important; min-height:62px !important; height:62px !important;
    padding:5px 3px !important; border-radius:12px !important; border:1px solid #655522 !important;
    background:linear-gradient(145deg,#20232A,#12151A) !important; color:#F4D778 !important;
    font-size:.76rem !important; font-weight:700 !important; line-height:1.2 !important;
    white-space:pre-line !important; overflow-wrap:anywhere !important;
    box-shadow:inset 0 0 0 1px rgba(250,204,21,.04) !important;
  }
  [class*="st-key-live_match_"] [data-testid="stButton"] > button:hover {
    border-color:#FACC15 !important; color:#FFE566 !important;
    background:linear-gradient(145deg,#302916,#17191F) !important;
  }
  [class*="st-key-live_match_"] [data-testid="stButton"] > button[kind="primary"] {
    background:linear-gradient(145deg,#FDE047,#FACC15) !important; color:#111419 !important;
    border-color:#FFE566 !important; box-shadow:0 0 12px rgba(250,204,21,.18) !important;
  }
  [class*="st-key-live_match_"] [data-testid="stButton"] > button p {
    font-size:inherit !important; line-height:inherit !important; margin:0 !important;
    white-space:pre-line !important; overflow-wrap:anywhere !important;
  }
  @media(max-width:420px) {
    [class*="st-key-live_match_"] [data-testid="stHorizontalBlock"] { gap:.3rem !important; }
    [class*="st-key-live_match_"] [data-testid="stButton"] > button {
      min-height:58px !important; height:58px !important; padding:4px 2px !important;
      font-size:.66rem !important; letter-spacing:-.2px !important; border-radius:10px !important;
    }
  }


  /* Selección directa de la tarjeta del marcador; el botón transparente no cambia el diseño visible. */
  [class*="st-key-live_match_"] { position:relative !important; }
  [class*="st-key-select_live_match_"] { position:absolute !important; top:0 !important; left:0 !important; right:0 !important; height:132px !important; min-height:132px !important; z-index:8 !important; opacity:0 !important; margin:0 !important; padding:0 !important; }
  [class*="st-key-select_live_match_"] [data-testid="stButton"], [class*="st-key-select_live_match_"] [data-testid="stButton"] > button { width:100% !important; height:132px !important; min-height:132px !important; max-height:132px !important; opacity:0 !important; background:transparent !important; border:0 !important; box-shadow:none !important; cursor:pointer !important; }
  .fl-match-scoreboard.is-selected { border-color:rgba(250,204,21,.8) !important; box-shadow:inset 0 0 10px rgba(250,204,21,.035),0 0 16px rgba(250,204,21,.10) !important; }
  [data-testid="stSidebar"] [class*="st-key-main_stats_"] button, [data-testid="stSidebar"] [class*="st-key-main_market_"] button, [data-testid="stSidebar"] [class*="st-key-main_h2h_"] button { position:relative !important; display:flex !important; align-items:center !important; justify-content:flex-start !important; gap:14px !important; min-height:68px !important; height:68px !important; width:100% !important; padding:0 18px 0 22px !important; border:1px solid #B58A19 !important; border-radius:15px !important; background:linear-gradient(145deg,#22252B,#17191E) !important; color:#FFE36A !important; font-size:.86rem !important; font-weight:850 !important; letter-spacing:.025em !important; box-shadow:inset 0 1px 0 rgba(255,255,255,.035),0 3px 10px rgba(0,0,0,.22) !important; transition:transform .18s ease,background .2s ease,border-color .2s ease,box-shadow .2s ease !important; }
  [data-testid="stSidebar"] [class*="st-key-main_stats_"] button::after, [data-testid="stSidebar"] [class*="st-key-main_market_"] button::after, [data-testid="stSidebar"] [class*="st-key-main_h2h_"] button::after { content:"›"; position:absolute; right:18px; top:50%; transform:translateY(-52%); color:#FACC15; font-size:1.8rem; font-weight:500; line-height:1; }
  [data-testid="stSidebar"] [class*="st-key-main_stats_"] button:hover, [data-testid="stSidebar"] [class*="st-key-main_market_"] button:hover, [data-testid="stSidebar"] [class*="st-key-main_h2h_"] button:hover { transform:translateY(-1px) !important; background:linear-gradient(145deg,#30343C,#22252B) !important; border-color:#FFE566 !important; box-shadow:0 5px 16px rgba(0,0,0,.35),0 0 14px rgba(250,204,21,.12) !important; }
  [data-testid="stSidebar"] [class*="st-key-main_stats_"] button[kind="primary"], [data-testid="stSidebar"] [class*="st-key-main_market_"] button[kind="primary"], [data-testid="stSidebar"] [class*="st-key-main_h2h_"] button[kind="primary"] { background:linear-gradient(145deg,#353126,#24262B) !important; color:#FFE36A !important; border:2px solid #FACC15 !important; box-shadow:inset 0 0 0 1px rgba(250,204,21,.12),0 0 18px rgba(250,204,21,.13) !important; }
  [data-testid="stSidebar"] [class*="st-key-main_stats_"] button [data-testid="stIconMaterial"], [data-testid="stSidebar"] [class*="st-key-main_market_"] button [data-testid="stIconMaterial"], [data-testid="stSidebar"] [class*="st-key-main_h2h_"] button [data-testid="stIconMaterial"] { color:#FACC15 !important; font-size:1.35rem !important; }
  [data-testid="stSidebar"] [class*="st-key-main_stats_"] button:hover, [data-testid="stSidebar"] [class*="st-key-main_market_"] button:hover, [data-testid="stSidebar"] [class*="st-key-main_h2h_"] button:hover { transform:translateY(-1px) !important; background:linear-gradient(145deg,#3B3216,#211D12) !important; border-color:#FFE566 !important; box-shadow:0 5px 16px #0006,0 0 14px #FACC1522 !important; }
  [data-testid="stSidebar"] [class*="st-key-main_stats_"] button[kind="primary"], [data-testid="stSidebar"] [class*="st-key-main_market_"] button[kind="primary"], [data-testid="stSidebar"] [class*="st-key-main_h2h_"] button[kind="primary"] { background:linear-gradient(135deg,#FACC15,#FFE566) !important; color:#101216 !important; border-color:#FFE566 !important; box-shadow:0 0 0 1px #FACC1544,0 5px 18px #FACC1520 !important; }
  [data-testid="stSidebar"] [class*="st-key-main_stats_"] button[kind="primary"] [data-testid="stIconMaterial"],
  [data-testid="stSidebar"] [class*="st-key-main_market_"] button[kind="primary"] [data-testid="stIconMaterial"],
  [data-testid="stSidebar"] [class*="st-key-main_h2h_"] button[kind="primary"] [data-testid="stIconMaterial"] {
    color:#111419 !important;
  }
  /* Marcador premium al abrir un partido */
  .fl-match-scoreboard {
    display:grid; grid-template-columns:100px minmax(0,1fr); gap:13px; align-items:center;
    margin:3px 0 7px; padding:12px; border:1px solid #343840; border-radius:15px;
    background:radial-gradient(ellipse at 10% 50%,rgba(250,204,21,.055),transparent 45%),linear-gradient(145deg,#171A20,#090A0D);
    box-shadow:inset 0 0 12px rgba(250,204,21,.025);
  }
  .fl-match-scoreboard { outline:none !important; transition:box-shadow .22s ease,border-color .22s ease,background .22s ease !important; }
  .fl-match-scoreboard:hover { border-color:rgba(250,204,21,.42) !important; box-shadow:inset 0 0 12px rgba(250,204,21,.025),0 0 20px rgba(250,204,21,.11) !important; }
  [class*="st-key-select_live_match_"] button,
  [class*="st-key-select_live_match_"] button:hover,
  [class*="st-key-select_live_match_"] button:focus,
  [class*="st-key-select_live_match_"] button:focus-visible,
  [class*="st-key-select_live_match_"] button:active { outline:none !important; border:0 !important; box-shadow:none !important; background:transparent !important; }
  .fl-match-clock {
    display:flex; min-height:80px; flex-direction:column; align-items:center; justify-content:center; gap:5px;
    border:0 !important; border-radius:0 !important; background:transparent !important;
    box-shadow:none !important; padding:5px 3px; box-sizing:border-box;
  }
  .fl-match-minute { display:flex; align-items:baseline; justify-content:center; gap:1px; color:#FFE566; font-size:1.22rem; line-height:1.1; font-weight:850; font-variant-numeric:tabular-nums; letter-spacing:.1px; text-shadow:0 0 12px rgba(250,204,21,.12); }
  .fl-match-minute-main { font-size:1.22rem; font-weight:950; }
  .fl-match-clock-separator { color:#FACC15; opacity:.9; font-size:1rem; font-weight:850; }
  .fl-match-seconds { color:#FFF0A3; font-size:.96rem; font-weight:800; }
  .fl-match-live { display:inline-flex; align-items:center; justify-content:center; gap:5px; color:#FFE9E7; background:rgba(226,61,50,.13); border:1px solid rgba(226,61,50,.55); border-radius:999px; padding:3px 7px; font-size:.54rem; line-height:1; font-weight:900; letter-spacing:.65px; white-space:nowrap; }
  .fl-match-live::before { content:""; width:5px; height:5px; flex:0 0 5px; border-radius:50%; background:#F04438; box-shadow:0 0 6px rgba(240,68,56,.45); }
  .fl-match-teams { min-width:0; display:flex; flex-direction:column; gap:9px; }
  .fl-match-team {
    display:grid; grid-template-columns:34px 26px minmax(0,1fr) auto; align-items:center; gap:8px;
    min-width:0; min-height:34px; color:#F4F4F5; font-size:.92rem; font-weight:600; line-height:1.15;
  }
  /* Jerarquía del marcador: el resultado debe leerse primero, seguido del escudo y el equipo. */
  .fl-match-goals {
    display:flex; align-items:center; justify-content:center; min-width:30px; min-height:31px; box-sizing:border-box;
    padding:2px 3px; border-radius:8px; color:#FFE566; font-size:1.52rem; font-weight:950;
    font-variant-numeric:tabular-nums; text-align:center; line-height:1;
    background:linear-gradient(145deg,rgba(250,204,21,.12),rgba(250,204,21,.035));
    text-shadow:0 0 12px rgba(250,204,21,.12);
  }
  .fl-match-crest { display:block; width:25px; height:25px; object-fit:contain; justify-self:center; }
  .fl-match-crest-empty { display:block; width:25px; text-align:center; color:#FACC15; justify-self:center; }
  .fl-match-team-name { display:block; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; letter-spacing:.05px; }
  .fl-red-card-badge { display:inline-flex; align-items:center; justify-self:start; white-space:nowrap; line-height:1; }
  /* Botones compactos: solo iconos; el nombre aparece con el tooltip al pasar/tocar */
  [class*="st-key-live_match_"] [data-testid="stHorizontalBlock"] { gap:.55rem !important; }
  [class*="st-key-live_match_"] [data-testid="stButton"] > button {
    position:relative !important; display:flex !important; align-items:center !important; justify-content:center !important;
    width:100% !important; min-width:0 !important; height:62px !important; min-height:62px !important;
    padding:4px !important; border-radius:13px !important; border:1px solid #41434A !important;
    background:linear-gradient(145deg,#20232A,#111318) !important;
    color:#D8C16A !important; font-size:1.42rem !important; font-weight:800 !important;
    box-shadow:inset 0 1px 0 rgba(255,255,255,.025),0 2px 5px rgba(0,0,0,.12) !important;
    transition:transform .18s ease,background .18s ease,box-shadow .18s ease,border-color .18s ease,color .18s ease !important;
    animation:none !important;
  }
  [class*="st-key-live_match_"] [data-testid="stButton"] > button p {
    display:flex !important; justify-content:center !important; align-items:center !important;
    font-size:0 !important; line-height:1 !important; margin:0 !important; min-width:0 !important;
  }
  [class*="st-key-live_match_"] [data-testid="stButton"] [data-testid="stIconMaterial"] {
    font-size:1.8rem !important; line-height:1 !important; color:inherit !important;
  }
  [class*="st-key-live_match_"] [data-testid="stButton"] svg {
    width:1.8rem !important; height:1.8rem !important; flex-shrink:0 !important;
  }
  [class*="st-key-live_match_"] [data-testid="stButton"] > button:hover {
    transform:translateY(-1px) !important; border-color:#D6B84C !important;
    color:#FFE566 !important;
    box-shadow:0 4px 12px rgba(250,204,21,.09),inset 0 0 0 1px rgba(250,204,21,.07) !important;
    background:linear-gradient(145deg,#29271E,#17191F) !important;
  }
  [class*="st-key-live_match_"] [data-testid="stButton"] > button[kind="primary"] {
    background:linear-gradient(145deg,#E9C94F,#C6A52B) !important; color:#111419 !important;
    border-color:#F5DB77 !important; box-shadow:0 0 0 1px rgba(250,204,21,.12),0 3px 12px rgba(250,204,21,.12) !important;
    animation:none !important;
  }
  @media(max-width:420px) {
    .fl-match-scoreboard { grid-template-columns:82px minmax(0,1fr); gap:10px; padding:10px 9px; border-radius:14px; }
    .fl-match-clock { min-height:76px; gap:5px; }
    .fl-match-minute { font-size:1.08rem; }
    .fl-match-minute-main { font-size:1.08rem; }
    .fl-match-clock-separator { font-size:.9rem; }
    .fl-match-seconds { font-size:.84rem; }
    .fl-match-live { gap:4px; padding:3px 6px; font-size:.5rem; letter-spacing:.5px; }
    .fl-match-live::before { width:4px; height:4px; flex-basis:4px; }
    .fl-match-team { grid-template-columns:29px 21px minmax(0,1fr) auto; gap:5px; min-height:30px; font-size:.77rem; }
    .fl-match-teams { gap:7px; }
    .fl-match-goals { min-width:27px; min-height:27px; padding:2px; border-radius:7px; font-size:1.28rem; }
    .fl-match-crest { width:21px; height:21px; }
    .fl-match-crest-empty { width:21px; }
    [class*="st-key-live_match_"] [data-testid="stHorizontalBlock"] { gap:.35rem !important; }
    [class*="st-key-live_match_"] [data-testid="stButton"] > button { height:58px !important; min-height:58px !important; font-size:1.22rem !important; border-radius:12px !important; }
  }
  @media(prefers-reduced-motion:reduce) {
    [class*="st-key-live_match_"] [data-testid="stButton"] > button { animation:none !important; transition:none !important; }
  }


  /* Ajuste final: eliminar el marco exterior duplicado y dar aire a cada liga, sin perder compacidad móvil. */
  [class*="st-key-live_now_section"] > div > [data-testid="stExpander"] {
    border:0 !important; outline:0 !important; box-shadow:none !important;
    background:transparent !important; border-radius:0 !important;
  }
  [class*="st-key-live_now_section"] > div > [data-testid="stExpander"] > details {
    border:0 !important; outline:0 !important; box-shadow:none !important;
    background:transparent !important;
  }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] {
    border:0 !important; outline:0 !important; box-shadow:none !important;
    background:transparent !important; overflow:visible !important;
  }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] > details > summary {
    min-height:43px !important; margin:0 !important; padding:6px 10px !important;
    border:1px solid #30343B !important; border-radius:8px !important;
    background:linear-gradient(100deg,#111419,#0B0D10) !important;
    box-shadow:none !important;
  }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] + [data-testid="stExpander"] {
    margin-top:4px !important;
  }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] > details[open] > summary {
    border-color:#6F5C1D !important;
    background:linear-gradient(100deg,#191A1C,#121419) !important;
    box-shadow:inset 3px 0 0 #D6B52F !important;
  }
  @media(max-width:640px) {
    [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] > details > summary {
      min-height:42px !important; padding:5px 9px !important; border-radius:7px !important;
    }
    [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] + [data-testid="stExpander"] {
      margin-top:3px !important;
    }
  }


  /* Estado seleccionado persistente; el salto se limita al momento de pulsar. */
  [class*="st-key-main_stats_"] [data-testid="stButton"] > button[kind="primary"],
  [class*="st-key-main_market_"] [data-testid="stButton"] > button[kind="primary"],
  [class*="st-key-main_h2h_"] [data-testid="stButton"] > button[kind="primary"],
  [class*="st-key-main_stats_"] [data-testid="stButton"] > button[data-testid="stBaseButton-primary"],
  [class*="st-key-main_market_"] [data-testid="stButton"] > button[data-testid="stBaseButton-primary"],
  [class*="st-key-main_h2h_"] [data-testid="stButton"] > button[data-testid="stBaseButton-primary"] {
    background:#FFD21F !important; background-image:linear-gradient(145deg,#FFE76A,#FACC15) !important;
    color:#111419 !important; border:2px solid #FFF09A !important;
    box-shadow:inset 0 1px 0 rgba(255,255,255,.35),0 0 0 2px rgba(250,204,21,.25),0 0 15px rgba(250,204,21,.3) !important;
    transform:none !important;
  }
  [class*="st-key-main_stats_"] [data-testid="stButton"] > button[kind="primary"] svg,
  [class*="st-key-main_market_"] [data-testid="stButton"] > button[kind="primary"] svg,
  [class*="st-key-main_h2h_"] [data-testid="stButton"] > button[kind="primary"] svg,
  [class*="st-key-main_stats_"] [data-testid="stButton"] > button[data-testid="stBaseButton-primary"] svg,
  [class*="st-key-main_market_"] [data-testid="stButton"] > button[data-testid="stBaseButton-primary"] svg,
  [class*="st-key-main_h2h_"] [data-testid="stButton"] > button[data-testid="stBaseButton-primary"] svg {
    color:#111419 !important; fill:#111419 !important; stroke:#111419 !important;
  }
  [class*="st-key-main_stats_"] [data-testid="stButton"] > button[kind="secondary"],
  [class*="st-key-main_market_"] [data-testid="stButton"] > button[kind="secondary"],
  [class*="st-key-main_h2h_"] [data-testid="stButton"] > button[kind="secondary"],
  [class*="st-key-main_stats_"] [data-testid="stButton"] > button[data-testid="stBaseButton-secondary"],
  [class*="st-key-main_market_"] [data-testid="stButton"] > button[data-testid="stBaseButton-secondary"],
  [class*="st-key-main_h2h_"] [data-testid="stButton"] > button[data-testid="stBaseButton-secondary"] {
    background:linear-gradient(145deg,#20232A,#111318) !important;
    color:#D8C16A !important; border:1px solid #41434A !important; box-shadow:none !important;
    transform:none !important;
  }
  [class*="st-key-main_stats_"] [data-testid="stButton"] > button:active,
  [class*="st-key-main_market_"] [data-testid="stButton"] > button:active,
  [class*="st-key-main_h2h_"] [data-testid="stButton"] > button:active {
    transform:translateY(-3px) scale(.97) !important;
    background:#FFE76A !important; color:#111419 !important;
  }

  /* RESTAURAR LOS BOTONES PRINCIPALES GRANDES: escáner en vivo y actualizar. */
  [class*="st-key-control_row"] [data-testid="stButton"] > button {
    display:flex !important; align-items:center !important; justify-content:center !important;
    width:100% !important; min-height:72px !important; height:auto !important;
    padding:16px 20px !important; box-sizing:border-box !important;
    border:2px solid #FACC15 !important; border-radius:16px !important;
    background:linear-gradient(135deg,#FFE36A,#D6A900) !important;
    color:#171717 !important; font-size:1.12rem !important; line-height:1.25 !important;
    font-weight:850 !important; white-space:normal !important;
    box-shadow:0 4px 18px rgba(250,204,21,.22) !important;
  }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button,
  [class*="st-key-scan_cta_card"] button[data-testid^="stBaseButton"] {
    display:block !important; position:relative !important; overflow:hidden !important;
    width:100% !important; min-width:100% !important; max-width:560px !important; min-height:160px !important; height:160px !important;
    box-sizing:border-box !important; padding:20px 18px 20px 49% !important;
    border-radius:25px !important; border:2px solid #F5CE4D !important;
    background-color:#090A0D !important;
    background-image:radial-gradient(ellipse at 18% 48%,rgba(250,204,21,.19),transparent 43%),radial-gradient(ellipse at 82% 10%,rgba(255,226,125,.07),transparent 38%),linear-gradient(132deg,#08090C 0%,#111318 58%,#19170F 100%) !important;
    color:#F4F4F5 !important; font-size:clamp(1rem,3.8vw,1.35rem) !important;
    line-height:1.5 !important; font-weight:850 !important; white-space:pre-line !important;
    text-align:left !important; box-shadow:inset 0 1px 0 rgba(255,245,190,.34),inset 0 0 28px rgba(250,204,21,.10),0 0 0 1px rgba(250,204,21,.22),0 8px 26px rgba(0,0,0,.34),0 0 22px rgba(250,204,21,.12) !important;
  }
  /* Solo jerarquía tipográfica del texto del CTA; geometría y animación permanecen intactas. */
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p { margin:0 !important; }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p:has(strong) {
    margin:0 0 5px !important; line-height:1.12 !important;
  }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button strong {
    display:block !important; color:#FFE27A !important;
    font-size:clamp(1.22rem,4.35vw,1.62rem) !important;
    font-weight:950 !important; letter-spacing:.055em !important;
    text-shadow:0 2px 12px rgba(250,204,21,.20) !important;
  }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p:not(:has(strong)) {
    color:#F1D66D !important; font-size:clamp(.88rem,2.8vw,1rem) !important;
    font-weight:750 !important; line-height:1.2 !important; margin:0 0 5px !important;
  }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p:nth-of-type(3) {
    color:#FFFFFF !important; -webkit-text-fill-color:#FFFFFF !important;
    font-size:clamp(.70rem,2.2vw,.82rem) !important;
    font-weight:650 !important; line-height:1.2 !important; margin-top:0 !important;
    letter-spacing:.015em !important; position:relative !important; top:-11px !important;
  }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button::before {
    content:"" !important; position:absolute !important; left:4% !important; top:50% !important;
    width:min(38%,170px) !important; aspect-ratio:1 !important; height:auto !important;
    transform:translateY(-50%); border-radius:50% !important; border:3px solid #FACC15 !important;
    background-color:#090A0D !important;
    background-image:radial-gradient(circle at center,#FACC15 0 6%,#14151A 7% 14%,transparent 15%),repeating-radial-gradient(circle at center,transparent 0 10px,rgba(250,204,21,.55) 11px 13px,transparent 14px 20px),conic-gradient(from 0deg,transparent 0 12%,rgba(250,204,21,.95) 16%,transparent 28% 48%,rgba(250,204,21,.45) 53%,transparent 68%) !important;
    box-shadow:0 0 25px rgba(250,204,21,.55),inset 0 0 22px rgba(250,204,21,.30),0 0 0 5px rgba(250,204,21,.045) !important;
    animation:scanner-radar-spin 3s linear infinite !important;
  }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button::after {
    content:"⚽" !important; position:absolute !important; left:23% !important; top:50% !important;
    transform:translate(-50%,-50%); width:40px !important; height:40px !important;
    display:flex !important; align-items:center !important; justify-content:center !important;
    font-size:clamp(1.8rem,6vw,2.7rem) !important; filter:sepia(1) saturate(2.2) hue-rotate(2deg) drop-shadow(0 0 12px rgba(250,204,21,.82)) !important;
    animation:scanner-ball-orbit 2s ease-in-out infinite !important;
  }
  /* Botones de escaneo/actualización dentro de Goles y Córners: selector por key para evitar que queden pequeños. */
  [class*="st-key-analysis_scan_radar_goals_"] [data-testid="stButton"] > button,
  [class*="st-key-analysis_scan_goals_"] [data-testid="stButton"] > button,
  [class*="st-key-analysis_scan_radar_corners_"] [data-testid="stButton"] > button,
  [class*="st-key-analysis_scan_corners_"] [data-testid="stButton"] > button {
    display:flex !important; align-items:center !important; justify-content:center !important;
    width:100% !important; min-width:100% !important; min-height:96px !important; height:96px !important;
    box-sizing:border-box !important; padding:14px 8px !important;
    border:2px solid #FACC15 !important; border-radius:16px !important;
    background:linear-gradient(145deg,#292516,#111318) !important; color:#FFE36A !important;
    font-size:clamp(.9rem,2.7vw,1.08rem) !important; line-height:1.3 !important;
    font-weight:850 !important; white-space:normal !important;
    box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 4px 15px rgba(0,0,0,.25) !important;
  }
  [class*="st-key-analysis_scan_radar_goals_"] [data-testid="stButton"] > button::before,
  [class*="st-key-analysis_scan_radar_corners_"] [data-testid="stButton"] > button::before {
    content:"◉" !important; display:inline-block !important; margin-right:7px !important;
    color:#FACC15 !important; font-size:1.35rem !important;
  }
  @media(max-width:640px) {
    [class*="st-key-control_row"] [data-testid="stButton"] > button {
      min-height:62px !important; padding:12px 8px !important; font-size:1rem !important;
    }
    [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button {
      min-height:145px !important; height:145px !important; padding:16px 12px 16px 49% !important;
      font-size:.95rem !important; line-height:1.4 !important;
    }
    [class*="st-key-analysis_scan_radar_goals_"] [data-testid="stButton"] > button,
    [class*="st-key-analysis_scan_goals_"] [data-testid="stButton"] > button,
    [class*="st-key-analysis_scan_radar_corners_"] [data-testid="stButton"] > button,
    [class*="st-key-analysis_scan_corners_"] [data-testid="stButton"] > button {
      min-height:84px !important; height:84px !important; padding:10px 5px !important; font-size:.84rem !important;
    }
  }

  /* CORRECCIÓN DEFINITIVA: las dos columnas de escaneo deben ocupar el ancho disponible. */
  [class*="st-key-analysis_scan_cta_goals_"],
  [class*="st-key-analysis_scan_cta_corners_"] {
    display:block !important; width:100% !important; min-width:0 !important; max-width:100% !important;
    overflow:visible !important; margin:12px 0 18px !important;
  }
  [class*="st-key-analysis_scan_cta_goals_"] [data-testid="stHorizontalBlock"],
  [class*="st-key-analysis_scan_cta_corners_"] [data-testid="stHorizontalBlock"] {
    display:grid !important; grid-template-columns:minmax(0,1fr) minmax(0,1fr) !important;
    gap:12px !important; width:100% !important; min-width:0 !important;
    align-items:stretch !important; overflow:visible !important;
  }
  [class*="st-key-analysis_scan_cta_goals_"] [data-testid="column"],
  [class*="st-key-analysis_scan_cta_corners_"] [data-testid="column"] {
    display:block !important; width:100% !important; min-width:0 !important; max-width:100% !important;
    flex:1 1 0 !important; overflow:visible !important;
  }
  [class*="st-key-analysis_scan_radar_goals_"],
  [class*="st-key-analysis_scan_goals_"],
  [class*="st-key-analysis_scan_radar_corners_"],
  [class*="st-key-analysis_scan_corners_"] {
    display:block !important; width:100% !important; min-width:0 !important; max-width:100% !important;
    flex:1 1 0 !important; overflow:visible !important;
  }
  [class*="st-key-analysis_scan_radar_goals_"] [data-testid="stButton"],
  [class*="st-key-analysis_scan_goals_"] [data-testid="stButton"],
  [class*="st-key-analysis_scan_radar_corners_"] [data-testid="stButton"],
  [class*="st-key-analysis_scan_corners_"] [data-testid="stButton"] {
    display:block !important; width:100% !important; min-width:0 !important; max-width:100% !important;
  }
  [class*="st-key-analysis_scan_radar_goals_"] [data-testid="stButton"] > button,
  [class*="st-key-analysis_scan_goals_"] [data-testid="stButton"] > button,
  [class*="st-key-analysis_scan_radar_corners_"] [data-testid="stButton"] > button,
  [class*="st-key-analysis_scan_corners_"] [data-testid="stButton"] > button {
    display:flex !important; align-items:center !important; justify-content:center !important;
    position:relative !important; width:100% !important; min-width:0 !important; max-width:100% !important;
    height:94px !important; min-height:94px !important; box-sizing:border-box !important;
    padding:12px 8px !important; margin:0 !important; overflow:hidden !important;
    white-space:normal !important; overflow-wrap:anywhere !important; text-align:center !important;
    border:2px solid #FACC15 !important; border-radius:16px !important;
    background:linear-gradient(145deg,#292516,#111318) !important; color:#FFE36A !important;
    font-size:clamp(.9rem,2.7vw,1.08rem) !important; line-height:1.3 !important; font-weight:850 !important;
    box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 4px 15px rgba(0,0,0,.25) !important;
  }
  /* El icono radar decorativo no debe alterar el ancho real del botón. */
  [class*="st-key-analysis_scan_radar_goals_"] [data-testid="stButton"] > button::before,
  [class*="st-key-analysis_scan_radar_corners_"] [data-testid="stButton"] > button::before {
    position:static !important; display:inline-block !important; flex:0 0 auto !important;
    width:auto !important; height:auto !important; aspect-ratio:auto !important;
    margin:0 7px 0 0 !important; transform:none !important; border:0 !important;
    background:none !important; box-shadow:none !important; animation:none !important;
    content:"◉" !important; color:#FACC15 !important; font-size:1.35rem !important;
  }
  /* SISTEMA VISUAL UNIFICADO: acciones y escáneres en Goles, Córners, Empates y Ambos marcan. */
  [class*="st-key-analysis_scan_cta"] [data-testid="stButton"] > button,
  [class*="st-key-analysis_scan_radar_goals_"] [data-testid="stButton"] > button,
  [class*="st-key-analysis_scan_goals_"] [data-testid="stButton"] > button,
  [class*="st-key-analysis_scan_radar_corners_"] [data-testid="stButton"] > button,
  [class*="st-key-analysis_scan_corners_"] [data-testid="stButton"] > button,
  [class*="st-key-corner_h2h_"] [data-testid="stButton"] > button {
    border:1.5px solid #D6B84C !important;
    border-radius:14px !important;
    background:linear-gradient(145deg,#1A1C22 0%,#111318 72%,#17160F 100%) !important;
    color:#FDE68A !important;
    box-shadow:inset 0 1px 0 rgba(255,255,255,.045),0 3px 12px rgba(0,0,0,.22),0 0 8px rgba(250,204,21,.045) !important;
    transition:background .18s ease,border-color .18s ease,box-shadow .18s ease,transform .18s ease !important;
  }
  [class*="st-key-analysis_scan_cta"] [data-testid="stButton"] > button:hover,
  [class*="st-key-analysis_scan_radar_goals_"] [data-testid="stButton"] > button:hover,
  [class*="st-key-analysis_scan_goals_"] [data-testid="stButton"] > button:hover,
  [class*="st-key-analysis_scan_radar_corners_"] [data-testid="stButton"] > button:hover,
  [class*="st-key-analysis_scan_corners_"] [data-testid="stButton"] > button:hover,
  [class*="st-key-corner_h2h_"] [data-testid="stButton"] > button:hover {
    background:linear-gradient(145deg,#292516 0%,#17191F 76%,#211D11 100%) !important;
    border-color:#FFE566 !important;color:#FFF1A8 !important;
    box-shadow:inset 0 1px 0 rgba(255,255,255,.075),0 4px 14px rgba(0,0,0,.25),0 0 13px rgba(250,204,21,.13) !important;
    transform:translateY(-1px) !important;
  }
  [class*="st-key-analysis_scan_cta"] [data-testid="stButton"] > button:active,
  [class*="st-key-analysis_scan_radar_goals_"] [data-testid="stButton"] > button:active,
  [class*="st-key-analysis_scan_goals_"] [data-testid="stButton"] > button:active,
  [class*="st-key-analysis_scan_radar_corners_"] [data-testid="stButton"] > button:active,
  [class*="st-key-analysis_scan_corners_"] [data-testid="stButton"] > button:active,
  [class*="st-key-corner_h2h_"] [data-testid="stButton"] > button:active {
    transform:scale(.99) !important;box-shadow:inset 0 1px 4px rgba(0,0,0,.25),0 0 9px rgba(250,204,21,.12) !important;
  }
  [class*="st-key-analysis_scan_cta"] [data-testid="stButton"] > button p,
  [class*="st-key-analysis_scan_radar_goals_"] [data-testid="stButton"] > button p,
  [class*="st-key-analysis_scan_goals_"] [data-testid="stButton"] > button p,
  [class*="st-key-analysis_scan_radar_corners_"] [data-testid="stButton"] > button p,
  [class*="st-key-analysis_scan_corners_"] [data-testid="stButton"] > button p,
  [class*="st-key-corner_h2h_"] [data-testid="stButton"] > button p {
    color:inherit !important;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif !important;
    font-weight:800 !important;letter-spacing:.01em !important;
  }
  @media(max-width:640px) {
    [class*="st-key-analysis_scan_cta"] [data-testid="stButton"] > button { border-radius:13px !important; }
    [class*="st-key-analysis_scan_radar_goals_"] [data-testid="stButton"] > button,
    [class*="st-key-analysis_scan_goals_"] [data-testid="stButton"] > button,
    [class*="st-key-analysis_scan_radar_corners_"] [data-testid="stButton"] > button,
    [class*="st-key-analysis_scan_corners_"] [data-testid="stButton"] > button {
      border-radius:13px !important; border-width:1.5px !important;
    }
  }
  @media(prefers-reduced-motion:reduce) {
    [class*="st-key-analysis_scan_cta"] [data-testid="stButton"] > button,
    [class*="st-key-analysis_scan_radar_goals_"] [data-testid="stButton"] > button,
    [class*="st-key-analysis_scan_goals_"] [data-testid="stButton"] > button,
    [class*="st-key-analysis_scan_radar_corners_"] [data-testid="stButton"] > button,
    [class*="st-key-analysis_scan_corners_"] [data-testid="stButton"] > button,
    [class*="st-key-corner_h2h_"] [data-testid="stButton"] > button { transition:none !important; }
  }
  /* El estilo de los botones superiores se define en la vista de análisis para evitar anchos automáticos conflictivos. */

  /* H2H responsive: full-width card, readable copy, and no clipped match rows. */
  .match-analysis-kicker, .match-analysis-title, .h2h-match-row,
  .match-analysis-panel {
    display:block;
    width:100% !important;
    max-width:100% !important;
    min-width:0 !important;
    box-sizing:border-box !important;
  }
  .match-analysis-kicker {
    margin:0 0 7px !important;
    color:#FACC15 !important;
    font-size:.72rem !important;
    font-weight:850 !important;
    line-height:1.45 !important;
    letter-spacing:.12em !important;
    text-transform:uppercase !important;
    overflow-wrap:anywhere !important;
  }
  .match-analysis-title {
    margin:0 0 10px !important;
    font-size:clamp(1.05rem,2vw,1.5rem) !important;
    font-weight:850 !important;
    line-height:1.3 !important;
    overflow-wrap:anywhere !important;
  }
  .h2h-match-row {
    display:grid !important;
    grid-template-columns:84px minmax(0,1fr) 64px minmax(0,1fr) !important;
    align-items:center !important;
    gap:10px !important;
    padding:12px 14px !important;
    margin:0 !important;
    overflow:hidden !important;
    border:1px solid rgba(250,204,21,.16) !important;
    border-bottom-color:rgba(250,204,21,.08) !important;
    background:linear-gradient(110deg,rgba(26,29,35,.96),rgba(15,17,21,.98)) !important;
    color:#E5E7EB !important;
    font-size:.88rem !important;
    line-height:1.4 !important;
  }
  .h2h-match-row:first-of-type { border-radius:12px 12px 0 0 !important; }
  .h2h-match-row:last-of-type { border-radius:0 0 12px 12px !important; border-bottom-color:rgba(250,204,21,.16) !important; }
  .h2h-match-row > span { min-width:0 !important; }
  .h2h-match-row .h2h-team {
    display:flex !important;
    align-items:center !important;
    gap:7px !important;
    min-width:0 !important;
    overflow:hidden !important;
    white-space:normal !important;
    overflow-wrap:anywhere !important;
    word-break:normal !important;
  }
  .h2h-match-row .h2h-team img {
    display:block !important;
    width:22px !important;
    height:22px !important;
    object-fit:contain !important;
    flex:0 0 22px !important;
  }
  .h2h-match-row .h2h-score {
    text-align:center !important;
    white-space:nowrap !important;
    color:#FACC15 !important;
    font-size:1rem !important;
    font-weight:900 !important;
    letter-spacing:.04em !important;
  }
  [data-testid="stCaptionContainer"] {
    min-width:0 !important;
    max-width:100% !important;
  }
  [data-testid="stCaptionContainer"] p {
    line-height:1.55 !important;
    overflow-wrap:anywhere !important;
  }
  @media(max-width:760px) {
    section.main > div.block-container {
      width:100% !important;
      max-width:100% !important;
      min-width:0 !important;
      padding-left:12px !important;
      padding-right:12px !important;
      box-sizing:border-box !important;
      overflow-x:hidden !important;
    }
    .match-analysis-kicker { font-size:.66rem !important; letter-spacing:.09em !important; }
    .match-analysis-title { font-size:1.08rem !important; line-height:1.3 !important; margin-bottom:8px !important; }
    .h2h-match-row {
      grid-template-columns:minmax(0,1fr) 44px minmax(0,1fr) !important;
      gap:6px !important;
      padding:10px 8px !important;
      font-size:.76rem !important;
      line-height:1.35 !important;
    }
    .h2h-match-row > span:first-child {
      grid-column:1 / -1 !important;
      padding-bottom:4px !important;
      color:#A8ADB7 !important;
      font-size:.68rem !important;
      letter-spacing:.02em !important;
    }
    .h2h-match-row .h2h-team { gap:4px !important; }
    .h2h-match-row .h2h-team img { width:18px !important; height:18px !important; flex-basis:18px !important; }
    .h2h-match-row .h2h-score { font-size:.84rem !important; }
    .match-analysis-panel { padding:10px !important; margin:8px 0 12px !important; }
  }
  @media(max-width:380px) {
    .h2h-match-row { grid-template-columns:minmax(0,1fr) 38px minmax(0,1fr) !important; gap:4px !important; padding:9px 6px !important; font-size:.69rem !important; }
    .h2h-match-row .h2h-team img { width:15px !important; height:15px !important; flex-basis:15px !important; }
    .h2h-match-row .h2h-score { font-size:.76rem !important; }
  }

  /* H2H: cabecera única, más visible y con menos espacio superior. */
  /* Ocultar el cursor de texto accidental en bloques de contenido no editables. */
  section.main [data-testid="stMarkdownContainer"],
  section.main [data-testid="stMarkdownContainer"] * {
    caret-color:transparent !important;
  }
  .h2h-description {
    display:block !important; width:100% !important; max-width:100% !important;
    min-width:0 !important; box-sizing:border-box !important;
    margin:8px 0 12px !important; padding:0 10px !important;
    color:#AEB3BC !important; font-size:.9rem !important; line-height:1.55 !important;
    white-space:normal !important; overflow:visible !important;
    overflow-wrap:anywhere !important; word-break:normal !important;
    text-indent:0 !important;
  }
  @media(max-width:640px) {
    .h2h-description {
      width:100% !important; max-width:100% !important; min-width:0 !important;
      margin:8px 0 12px !important; padding:0 10px !important;
      font-size:.82rem !important; line-height:1.5 !important;
      box-sizing:border-box !important; overflow-wrap:anywhere !important;
    }
  }
  .h2h-page-kicker, .h2h-page-kicker * {
    caret-color:transparent !important;
    user-select:none !important;
  }
  .h2h-summary-layout {
    display:flex !important; flex-direction:column !important; gap:10px !important;
    width:100% !important; max-width:100% !important; min-width:0 !important;
    box-sizing:border-box !important; margin:4px 0 14px !important;
  }
  .h2h-sample-card, .h2h-result-card, .h2h-secondary-card {
    min-width:0 !important; box-sizing:border-box !important;
    border:1px solid #302B20 !important; border-radius:14px !important;
    background:linear-gradient(145deg,#1B1E23,#14161B) !important;
    box-shadow:0 4px 12px rgba(0,0,0,.12) !important;
  }
  .h2h-sample-card { padding:12px 14px !important; text-align:center !important; }
  .h2h-sample-value { color:#E8CC70 !important; font-size:1.45rem !important; font-weight:900 !important; line-height:1.35 !important; margin-top:3px !important; }
  .h2h-results-grid {
    display:grid !important; grid-template-columns:repeat(3,minmax(0,1fr)) !important;
    gap:8px !important; width:100% !important; min-width:0 !important;
  }
  .h2h-result-card { padding:12px 8px !important; text-align:center !important; }
  .h2h-result-card .h2h-summary-label { min-height:2.5em !important; display:flex !important; align-items:center !important; justify-content:center !important; font-size:.66rem !important; letter-spacing:.015em !important; }
  .h2h-result-count { color:#F4F4F5 !important; font-size:1.2rem !important; font-weight:850 !important; line-height:1.35 !important; margin-top:5px !important; }
  .h2h-result-pct { color:#E8CC70 !important; font-size:1.25rem !important; font-weight:900 !important; line-height:1.3 !important; margin-top:3px !important; }
  .h2h-distribution { padding:14px 14px 12px !important; border:1px solid rgba(232,204,112,.48) !important; border-radius:14px !important; background:linear-gradient(135deg,rgba(232,204,112,.10),#111419 58%) !important; box-shadow:inset 0 1px 0 rgba(255,230,160,.08),0 5px 16px rgba(0,0,0,.16) !important; }
  .h2h-distribution-heading { display:flex !important; align-items:center !important; justify-content:space-between !important; gap:8px !important; color:#F0D98C !important; font-size:.76rem !important; font-weight:900 !important; letter-spacing:.09em !important; }
  .h2h-distribution-heading strong { color:#17191E !important; background:linear-gradient(135deg,#F4D982,#D9B94F) !important; border:1px solid rgba(255,238,180,.7) !important; border-radius:999px !important; padding:4px 10px !important; font-size:.78rem !important; font-weight:950 !important; box-shadow:0 2px 8px rgba(232,204,112,.18) !important; }
  .h2h-distribution-track { display:flex !important; overflow:hidden !important; width:100% !important; height:12px !important; margin:11px 0 9px !important; border-radius:99px !important; background:#292D34 !important; gap:1px !important; box-shadow:inset 0 1px 3px rgba(0,0,0,.35) !important; }
  .h2h-distribution-track span { display:block !important; min-width:0 !important; height:100% !important; }
  .h2h-distribution-home { background:#E8CC70 !important; }
  .h2h-distribution-draw { background:#858B98 !important; }
  .h2h-distribution-away { background:#75A9D6 !important; }
  .h2h-distribution-legend { display:flex !important; justify-content:space-between !important; flex-wrap:wrap !important; gap:6px 10px !important; color:#C3C7CF !important; font-size:.76rem !important; font-weight:650 !important; line-height:1.45 !important; }
  .h2h-secondary-grid { display:grid !important; grid-template-columns:repeat(2,minmax(0,1fr)) !important; gap:9px !important; width:100% !important; min-width:0 !important; }
  .h2h-secondary-card { padding:12px 13px !important; }
  .h2h-secondary-value { color:#E8CC70 !important; font-size:1.3rem !important; font-weight:900 !important; line-height:1.35 !important; margin-top:5px !important; }
  .h2h-secondary-pct, .h2h-secondary-note { color:#AEB3BC !important; font-size:.72rem !important; margin-top:2px !important; }
  .h2h-period-grid { display:grid !important; grid-template-columns:repeat(2,minmax(0,1fr)) !important; gap:9px !important; width:100% !important; min-width:0 !important; margin-top:9px !important; }
  .h2h-period-card { min-width:0 !important; box-sizing:border-box !important; padding:12px 13px !important; border:1px solid rgba(232,204,112,.42) !important; border-radius:13px !important; background:linear-gradient(145deg,#1B1E23,#14161B) !important; box-shadow:0 4px 12px rgba(0,0,0,.12) !important; }
  .h2h-period-value { color:#E8CC70 !important; font-size:1.3rem !important; font-weight:900 !important; line-height:1.35 !important; margin-top:5px !important; }
  .h2h-period-note { color:#AEB3BC !important; font-size:.68rem !important; line-height:1.4 !important; margin-top:3px !important; }
  @media(max-width:390px) { .h2h-period-card { padding:10px 9px !important; } .h2h-period-value { font-size:1.12rem !important; } .h2h-period-note { font-size:.62rem !important; } }
  @media(max-width:390px) {
    .h2h-result-card { padding:10px 5px !important; }
    .h2h-result-card .h2h-summary-label { font-size:.59rem !important; }
    .h2h-result-count { font-size:1.05rem !important; }
    .h2h-result-pct { font-size:1.12rem !important; }
    .h2h-distribution-legend { font-size:.68rem !important; gap:5px 7px !important; }
  }
  .h2h-summary-grid {
    display:grid !important; grid-template-columns:repeat(3,minmax(0,1fr)) !important;
    gap:10px !important; width:100% !important; max-width:100% !important;
    min-width:0 !important; box-sizing:border-box !important; margin:2px 0 14px !important;
  }
  .h2h-summary-card {
    min-width:0 !important; box-sizing:border-box !important; padding:12px 14px !important;
    border:1px solid #272A30 !important; border-radius:14px !important;
    background:linear-gradient(145deg,#1B1E23,#17191E) !important;
    box-shadow:0 4px 12px rgba(0,0,0,.12) !important;
  }
  .h2h-summary-label { color:#AEB3BC !important; font-size:.73rem !important; line-height:1.3 !important; text-transform:uppercase !important; letter-spacing:.025em !important; }
  .h2h-summary-value { color:#FFD52A !important; font-size:1.35rem !important; font-weight:850 !important; line-height:1.45 !important; margin-top:4px !important; }
  .h2h-summary-card:nth-child(4) .h2h-summary-value { color:#20C77A !important; }
  .h2h-summary-card:nth-child(5) .h2h-summary-value { color:#F04455 !important; }
  .h2h-summary-card:nth-child(6) .h2h-summary-value { font-size:1.05rem !important; }
  .h2h-history-list { width:100% !important; min-width:0 !important; }
  .h2h-match-row {
    display:grid !important; grid-template-columns:112px minmax(0,1fr) 82px minmax(0,1fr) !important;
    align-items:center !important; gap:12px !important; width:100% !important; min-width:0 !important;
    box-sizing:border-box !important; padding:12px 10px !important;
    border-bottom:1px solid #34302A !important; background:#15171C !important;
    transition:background .18s ease !important;
  }
  .h2h-match-row:nth-child(even) { background:#101216 !important; }
  .h2h-match-row:hover { background:#1B1E24 !important; }
  .h2h-match-row .h2h-date { color:#85868B !important; font-size:.8rem !important; white-space:nowrap !important; }
  .h2h-match-row .h2h-team { display:flex !important; align-items:center !important; gap:8px !important; min-width:0 !important; overflow:hidden !important; font-size:.88rem !important; font-weight:600 !important; line-height:1.3 !important; }
  .h2h-match-row .h2h-team img { width:25px !important; height:25px !important; flex:0 0 25px !important; object-fit:contain !important; }
  .h2h-match-row .h2h-team-name { overflow:hidden !important; text-overflow:ellipsis !important; white-space:nowrap !important; }
  .h2h-match-row .h2h-score { justify-self:center !important; display:inline-flex !important; align-items:center !important; justify-content:center !important; min-width:76px !important; box-sizing:border-box !important; padding:7px 10px !important; border-radius:10px !important; background:rgba(250,204,21,.11) !important; color:#FFD52A !important; font-size:1rem !important; font-weight:900 !important; white-space:nowrap !important; }
  @media(max-width:640px) {
    .h2h-summary-grid { gap:6px !important; margin-bottom:10px !important; }
    .h2h-summary-card { padding:9px 8px !important; border-radius:11px !important; }
    .h2h-summary-label { font-size:.58rem !important; }
    .h2h-summary-value { font-size:1.05rem !important; }
    .h2h-match-row { grid-template-columns:72px minmax(0,1fr) 58px minmax(0,1fr) !important; gap:5px !important; padding:10px 6px !important; }
    .h2h-match-row .h2h-date { font-size:.65rem !important; }
    .h2h-match-row .h2h-team { gap:4px !important; font-size:.68rem !important; }
    .h2h-match-row .h2h-team img { width:18px !important; height:18px !important; flex-basis:18px !important; }
    .h2h-match-row .h2h-score { min-width:54px !important; padding:6px 4px !important; font-size:.82rem !important; border-radius:8px !important; }
  }
  @media(max-width:380px) {
    .h2h-match-row { grid-template-columns:60px minmax(0,1fr) 48px minmax(0,1fr) !important; gap:3px !important; padding:9px 4px !important; }
    .h2h-match-row .h2h-date { font-size:.59rem !important; }
    .h2h-match-row .h2h-team { font-size:.61rem !important; gap:3px !important; }
    .h2h-match-row .h2h-team img { width:15px !important; height:15px !important; flex-basis:15px !important; }
    .h2h-match-row .h2h-score { min-width:46px !important; font-size:.74rem !important; }
  }
  .h2h-page-kicker {
    display:flex !important; align-items:center !important; gap:10px !important;
    flex-wrap:wrap !important; box-sizing:border-box !important; max-width:100% !important;
    margin-top:-80px !important; margin-right:0 !important; margin-bottom:14px !important; margin-left:0 !important;
    padding:12px 14px !important; color:#FFF1A8 !important;
    font-size:clamp(1.02rem,1.5vw,1.22rem) !important; font-weight:950 !important;
    letter-spacing:.055em !important; line-height:1.35 !important; text-transform:uppercase !important;
    text-shadow:0 0 18px rgba(250,204,21,.24) !important;
    background:linear-gradient(100deg,rgba(250,204,21,.13),rgba(250,204,21,.035) 68%,rgba(250,204,21,0)) !important;
    border:1px solid rgba(250,204,21,.30) !important; border-left:3px solid #FACC15 !important;
    border-radius:11px !important; box-shadow:inset 0 1px 0 rgba(255,255,255,.035),0 5px 18px rgba(0,0,0,.16) !important;
  }
  .h2h-page-kicker span { color:#C49A20 !important; padding:0 .25em !important; }
  /* H2H: quitar los bordes de TODOS los divs ancestros del encabezado.
     Las tarjetas internas no son ancestros y conservan sus propios contornos. */
  html body .stApp section.main div:has(.h2h-page-kicker) {
    border:0 !important;
    outline:0 !important;
    box-shadow:none !important;
  }
  html body .stApp section.main div:has(.h2h-page-kicker)::before,
  html body .stApp section.main div:has(.h2h-page-kicker)::after {
    border:0 !important;
    outline:0 !important;
    box-shadow:none !important;
    content:none !important;
    background-image:none !important;
  }
  html body .stApp .h2h-page-kicker {
    border-top:0 !important;
    border-right:0 !important;
    border-bottom:0 !important;
    box-shadow:none !important;
  }

  html body .stApp section.main:has(.h2h-page-kicker),
  html body .stApp section.main:has(.h2h-page-kicker) > div,
  html body .stApp section.main:has(.h2h-page-kicker) > div > div,
  html body .stApp section.main:has(.h2h-page-kicker) > div > div > div {
    border:0 !important;
    outline:0 !important;
    box-shadow:none !important;
  }
  html body .stApp .h2h-page-kicker {
    border-top:1px solid rgba(250,204,21,.30) !important;
    border-left:3px solid #FACC15 !important;
    border-right:0 !important;
    border-bottom:0 !important;
    box-shadow:none !important;
  }
  html body .stApp .h2h-page-kicker + div {
    border:0 !important;
    outline:0 !important;
    box-shadow:none !important;
  }
  html body .stApp .h2h-history-list {
    border-left:0 !important;
    border-right:0 !important;
    outline:0 !important;
    box-shadow:none !important;
  }
  /* H2H: panel compacto, con filas limpias y marcador siempre destacado. */
  .h2h-match-row {
    box-sizing:border-box !important; width:100% !important; min-width:0 !important;
    padding:11px 10px !important; border-bottom:1px solid rgba(250,204,21,.16) !important;
    background:linear-gradient(100deg,rgba(25,28,34,.96),rgba(17,19,24,.96)) !important;
    transition:background .18s ease,border-color .18s ease !important;
  }
  .h2h-match-row:hover { background:linear-gradient(100deg,#24251F,#191B20) !important; border-bottom-color:rgba(250,204,21,.42) !important; }
  .h2h-match-row .h2h-team { font-weight:600 !important; line-height:1.3 !important; }
  .h2h-match-row .h2h-score { font-size:.94rem !important; text-shadow:0 0 12px rgba(250,204,21,.12) !important; }
   /* Historial H2H: bandas alternas tipo Excel, sin separadores entre partidos. */
   html body .stApp .h2h-match-row-full.h2h-stripe-even { background:#15191F !important; border:0 !important; border-bottom:0 !important; }
   html body .stApp .h2h-match-row-full.h2h-stripe-odd { background:#1B2027 !important; border:0 !important; border-bottom:0 !important; }
  /* H2H oscuro: misma franja compacta del modo claro y balón dorado al extremo derecho. */
  html body .stApp [class*="st-key-h2h_history_row_"] {
    position:relative !important; width:100% !important; max-width:100% !important;
    overflow:visible !important; perspective:1000px !important; margin:0 !important;
  }
  html body .stApp [class*="st-key-h2h_history_row_"] .h2h-match-row-full {
    width:100% !important; min-height:52px !important; box-sizing:border-box !important;
    padding:8px 48px 8px 10px !important; gap:8px !important;
    grid-template-columns:82px minmax(0,1fr) 70px minmax(0,1fr) !important;
    position:relative !important; isolation:isolate !important;
  }
  html body .stApp [class*="st-key-h2h_history_row_"] [class*="st-key-h2h_goal_timeline_btn_"] {
    position:absolute !important; right:7px !important; top:50% !important;
    transform:translateY(-50%) !important; width:29px !important; min-width:29px !important;
    z-index:8 !important; margin:0 !important; padding:0 !important;
  }
  html body .stApp [class*="st-key-h2h_history_row_"] [class*="st-key-h2h_goal_timeline_btn_"] button {
    display:flex !important; align-items:center !important; justify-content:center !important;
    width:27px !important; min-width:27px !important; height:27px !important; min-height:27px !important;
    padding:0 !important; border-radius:50% !important; border:1px solid #FACC15 !important;
    background:radial-gradient(circle at 35% 25%,#FFF1A6 0%,#FACC15 55%,#9A7000 100%) !important;
    color:#171717 !important; font-size:12px !important; line-height:1 !important;
    box-shadow:0 0 7px #FACC1545 !important;
  }
  html body .stApp [class*="st-key-h2h_history_row_"] .h2h-match-row-full .h2h-score {
    position:relative !important; z-index:3 !important;
    display:inline-flex !important; align-items:center !important; justify-content:center !important;
    min-width:76px !important; min-height:36px !important; box-sizing:border-box !important;
    padding:6px 12px !important; border:1px solid #D6B84C !important; border-radius:9px !important;
    background:linear-gradient(145deg,rgba(250,204,21,.22),rgba(250,204,21,.10)) !important;
    color:#FFE566 !important; font-size:1rem !important; font-weight:900 !important;
    line-height:1 !important; font-variant-numeric:tabular-nums !important;
    box-shadow:0 0 0 3px #17191E,0 1px 5px rgba(250,204,21,.12) !important;
    text-shadow:0 0 10px rgba(250,204,21,.14) !important;
  }
  @media(max-width:640px) {
    html body .stApp [class*="st-key-h2h_history_row_"] .h2h-match-row-full {
      min-height:46px !important;
      grid-template-columns:60px minmax(0,1fr) 48px minmax(0,1fr) !important;
      padding:8px 40px 8px 5px !important; gap:3px !important;
    }
    html body .stApp [class*="st-key-h2h_history_row_"] [class*="st-key-h2h_goal_timeline_btn_"] {
      right:5px !important; width:25px !important; min-width:25px !important;
    }
    html body .stApp [class*="st-key-h2h_history_row_"] [class*="st-key-h2h_goal_timeline_btn_"] button {
      width:24px !important; min-width:24px !important; height:24px !important; min-height:24px !important;
    }
  }
  .h2h-page-kicker + div { margin-top:0 !important; }
  section.main > div.block-container:has(.h2h-page-kicker) {
    padding-top:22px !important;
  }
  @media(max-width:640px) {
    section.main > div.block-container:has(.h2h-page-kicker) {
      padding-top:14px !important; padding-left:12px !important; padding-right:12px !important;
      width:100% !important; max-width:100vw !important; box-sizing:border-box !important;
      overflow-x:hidden !important;
      border-left:0 !important;
      border-right:0 !important;
    }
    .h2h-page-kicker {
      width:calc(100% - 16px) !important; max-width:calc(100% - 16px) !important;
      margin-top:-65px !important; margin-right:auto !important; margin-bottom:12px !important; margin-left:auto !important;
      box-sizing:border-box !important; font-size:.94rem !important; letter-spacing:.045em !important;
      line-height:1.35 !important; padding:11px 10px !important;
      gap:7px !important; border-radius:9px !important;
    }
    .h2h-description {
      width:calc(100% - 16px) !important; max-width:calc(100% - 16px) !important;
      margin:8px auto 12px !important; padding:0 6px !important;
      box-sizing:border-box !important;
    }
    .h2h-summary-layout {
      width:calc(100% - 16px) !important; max-width:calc(100% - 16px) !important;
      margin:4px auto 14px !important; box-sizing:border-box !important;
    }
    .h2h-page-kicker + div {
      box-sizing:border-box !important; width:100% !important; max-width:100% !important;
      padding:0 8px !important; margin-left:0 !important; margin-right:0 !important;
      overflow-wrap:anywhere !important; word-break:normal !important;
    }
    .h2h-summary-grid {
      grid-template-columns:repeat(2,minmax(0,1fr)) !important; gap:8px !important;
      width:100% !important; max-width:100% !important; margin:2px 0 12px !important;
    }
    .h2h-summary-card {
      min-width:0 !important; padding:11px 10px !important; border-radius:10px !important;
      overflow:visible !important; text-align:left !important;
    }
    .h2h-summary-label { font-size:.66rem !important; line-height:1.3 !important; overflow-wrap:normal !important; white-space:normal !important; }
    .h2h-summary-value { font-size:1.08rem !important; line-height:1.35 !important; overflow-wrap:normal !important; white-space:normal !important; }
    .h2h-summary-card:nth-child(6) .h2h-summary-value { font-size:.92rem !important; }
    .h2h-history-list {
      width:calc(100% - 16px) !important; max-width:calc(100% - 16px) !important;
      margin-left:auto !important; margin-right:auto !important;
      box-sizing:border-box !important; overflow:hidden !important;
      border-left:1px solid rgba(232,204,112,.24) !important;
      border-right:1px solid rgba(232,204,112,.24) !important;
      border-radius:12px !important;
    }
    .h2h-match-row { grid-template-columns:64px minmax(0,1fr) 52px minmax(0,1fr) !important; gap:4px !important; padding:9px 5px !important; max-width:100% !important; overflow:hidden !important; }
    .h2h-match-row .h2h-date { font-size:.62rem !important; }
    .h2h-match-row .h2h-team { min-width:0 !important; gap:3px !important; font-size:.65rem !important; }
    .h2h-match-row .h2h-team img { width:16px !important; height:16px !important; flex-basis:16px !important; }
    .h2h-match-row .h2h-score { min-width:48px !important; padding:5px 3px !important; font-size:.78rem !important; border-radius:7px !important; }
  }

  /* H2H: Streamlit dibuja los marcos largos en stVerticalBlockBorderWrapper.
     Quitar SOLO esos contenedores estructurales; conservar las tarjetas internas. */
  html body .stApp section.main:has(.h2h-page-kicker) [data-testid="stVerticalBlockBorderWrapper"],
  html body .stApp section.main:has(.h2h-page-kicker) [data-testid="stVerticalBlockBorderWrapper"] > div {
    border:0 !important;
    outline:0 !important;
    box-shadow:none !important;
    background-image:none !important;
  }
  html body .stApp section.main:has(.h2h-page-kicker) [data-testid="stVerticalBlockBorderWrapper"]::before,
  html body .stApp section.main:has(.h2h-page-kicker) [data-testid="stVerticalBlockBorderWrapper"]::after {
    content:none !important;
    border:0 !important;
    outline:0 !important;
    box-shadow:none !important;
    background:none !important;
  }
  html body .stApp section.main:has(.h2h-page-kicker) > div.block-container {
    border-left:0 !important;
    border-right:0 !important;
    outline:0 !important;
    box-shadow:none !important;
  }

  /* H2H móvil: anular las dos reglas que reintroducían los marcos laterales. */
  @media(max-width:640px) {
    html body .stApp section.main > div.block-container:has(.h2h-page-kicker) {
      border-left:0 !important;
      border-right:0 !important;
    }
    html body .stApp .h2h-history-list {
      border-left:0 !important;
      border-right:0 !important;
    }
    html body .stApp .h2h-page-kicker {
      border-right:0 !important;
      border-bottom:0 !important;
      box-shadow:none !important;
    }
  }

  /* H2H oscuro: quitar el marco del contenedor padre que envuelve el análisis.
     Las tarjetas de muestra, distribución y resultados mantienen sus bordes. */
  @media (prefers-color-scheme: dark) {
    /* El marco visible que queda rodeando la lista es el propio .h2h-history-list. */
    html body .stApp section.main .h2h-history-list,
    html body .stApp section.main .h2h-history-list::before,
    html body .stApp section.main .h2h-history-list::after {
      border:0 !important;
      outline:0 !important;
      box-shadow:none !important;
      background-image:none !important;
      content:none !important;
    }
    html body .stApp section.main:has(.h2h-page-kicker) div[data-testid="stVerticalBlock"]:has(.h2h-page-kicker),
    html body .stApp section.main:has(.h2h-page-kicker) div[data-testid="stVerticalBlockBorderWrapper"],
    html body .stApp section.main:has(.h2h-page-kicker) [data-testid="column"]:has(.h2h-page-kicker),
    html body .stApp section.main:has(.h2h-page-kicker) .stColumn:has(.h2h-page-kicker) {
      border:0 !important;
      outline:0 !important;
      box-shadow:none !important;
      background-image:none !important;
    }
    html body .stApp section.main:has(.h2h-page-kicker) div[data-testid="stVerticalBlock"]:has(.h2h-page-kicker)::before,
    html body .stApp section.main:has(.h2h-page-kicker) div[data-testid="stVerticalBlock"]:has(.h2h-page-kicker)::after,
    html body .stApp section.main:has(.h2h-page-kicker) [data-testid="column"]:has(.h2h-page-kicker)::before,
    html body .stApp section.main:has(.h2h-page-kicker) [data-testid="column"]:has(.h2h-page-kicker)::after {
      border:0 !important;
      outline:0 !important;
      box-shadow:none !important;
      background:none !important;
      content:none !important;
    }
  }

  /* Corrección de foco: texto sólido sobre fondo opaco mientras se escribe. */
  html body [data-testid="stSidebar"] div[class*="st-key-search_goal_matches"] input[type="text"],
  html body [data-testid="stSidebar"] div[class*="st-key-search_goal_matches"] input[type="text"]:focus,
  html body [data-testid="stSidebar"] div[class*="st-key-search_goal_matches"] input[type="text"]:focus-visible,
  html body [data-testid="stSidebar"] div[class*="st-key-search_goal_matches"] input[type="text"]:active {
    background-color:#17191E !important;
    background-image:none !important;
    color:#FFFFFF !important;
    -webkit-text-fill-color:#FFFFFF !important;
    font-family:Arial,sans-serif !important;
    font-size:14px !important;
    font-weight:600 !important;
    opacity:1 !important;
    visibility:visible !important;
    position:relative !important;
    z-index:10 !important;
    filter:none !important;
    mix-blend-mode:normal !important;
  }
</style>
""", unsafe_allow_html=True)

show_splash_intro = not st.session_state.get("football_splash_shown", False)
if show_splash_intro:
    st.markdown("""
    <div class="football-splash" aria-label="Bienvenido a Football Lab">
      <div class="splash-pitch">
        <div class="splash-goal"></div>
        <div class="splash-data-orbit"></div>
        <div class="splash-ball">⚽</div>
      </div>
      <div class="splash-brand">FOOTBALL LAB</div>
      <div class="splash-tagline">ESCÁNER EN VIVO · DETECTA OPORTUNIDADES</div>
      <div class="splash-techline">ANÁLISIS EN TIEMPO REAL</div>
    </div>
    """, unsafe_allow_html=True)
    st.session_state["football_splash_shown"] = True

header_time = "Detectando hora local…"
st.markdown(f"""
<div class="brand-header">
  <div class="brand-header-main">
    <div class="brand-mark"><svg viewBox="0 0 64 64" aria-label="Football Lab trophy" fill="none" stroke="#0B0D10" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 10h24v14c0 11-5 17-12 17S20 35 20 24V10Z"/><path d="M20 15H10v5c0 9 6 14 13 14M44 15h10v5c0 9-6 14-13 14M32 41v8M22 54h20M25 49h14"/></svg></div>
    <div class="brand-wordmark">
      <div class="brand-title">FOOTBALL <span>LAB</span></div>
      <div class="brand-subtitle">LIVE ANALYTICS</div>
    </div>
    <div class="brand-pill">EN VIVO</div>
  </div>
</div>
{f'<input class="update-toast-toggle" type="checkbox" id="close-update-toast" aria-label="Ocultar notificación"><div class="update-toast" role="status"><div class="update-toast-icon">◷</div><div><div class="update-toast-title">ÚLTIMA ACTUALIZACIÓN</div><div class="update-toast-time" id="update-toast-time">{header_time}</div></div><div class="update-toast-check">✓</div><label class="update-toast-close" for="close-update-toast" role="button" tabindex="0" aria-label="Cerrar notificación" title="Cerrar">×</label></div>' if show_splash_intro else ''}
""", unsafe_allow_html=True)

st.markdown("""
<style>
div[class*="st-key-home_nav_bar"] {
 position:fixed !important; top:125px !important; left:0 !important; right:0 !important;
 z-index:2147483001 !important; width:100vw !important; max-width:100vw !important;
 padding:6px clamp(18px,3.2vw,48px) 10px !important; margin:0 !important;
 box-sizing:border-box !important; background:linear-gradient(105deg,#0B0D10 0%,#15171B 48%,#0B0D10 100%) !important;
 border-bottom:1px solid rgba(250,204,21,.62) !important;
 box-shadow:0 10px 22px rgba(0,0,0,.34),inset 0 -1px 0 rgba(250,204,21,.10) !important;
 backdrop-filter:blur(12px) !important;
}
@media(max-width:640px) {
 div[class*="st-key-home_nav_bar"] { top:129px !important; padding:6px 10px 10px !important; }
}
div[class*="st-key-home_nav_bar"] [data-testid="stHorizontalBlock"] { display:grid !important; grid-template-columns:repeat(5,minmax(0,1fr)) !important; grid-auto-flow:column !important; gap:0 !important; column-gap:0 !important; width:100% !important; min-width:0 !important; margin:0 !important; padding:0 !important; box-sizing:border-box !important; overflow:visible !important; }
div[class*="st-key-home_nav_bar"] [data-testid="column"] { display:block !important; flex:none !important; width:100% !important; max-width:100% !important; min-width:0 !important; padding:0 !important; margin:0 !important; box-sizing:border-box !important; }
div[class*="st-key-home_nav_bar"] [data-testid="column"]:nth-child(1) { grid-column:1 !important; }
div[class*="st-key-home_nav_bar"] [data-testid="column"]:nth-child(2) { grid-column:2 !important; }
div[class*="st-key-home_nav_bar"] [data-testid="column"]:nth-child(3) { grid-column:3 !important; }
div[class*="st-key-home_nav_bar"] [data-testid="column"]:nth-child(4) { grid-column:4 !important; }
div[class*="st-key-home_nav_bar"] [data-testid="column"]:nth-child(5) { grid-column:5 !important; }
div[class*="st-key-home_nav_bar"] [data-testid="column"] > div { width:100% !important; min-width:0 !important; margin:0 !important; }
div[class*="st-key-home_topnav_stats"] button, div[class*="st-key-home_topnav_goals"] button, div[class*="st-key-home_topnav_corners"] button, div[class*="st-key-home_topnav_h2h"] button, div[class*="st-key-home_topnav_tracker"] button {
 box-sizing:border-box !important; display:flex !important; align-items:center !important; justify-content:center !important;
 width:100% !important; min-width:0 !important; height:58px !important; min-height:58px !important; padding:5px 2px !important;
 border:1px solid #80661B !important; border-radius:12px !important; background:linear-gradient(145deg,#20242C,#111419) !important;
 color:#E8C85A !important; font-size:.68rem !important; font-weight:850 !important; letter-spacing:.075em !important;
 line-height:1.05 !important; white-space:nowrap !important; overflow:hidden !important;
 transition:background .2s ease,border-color .2s ease,box-shadow .2s ease,transform .18s ease !important;
}
div[class*="st-key-home_nav_bar"] button > div {
 display:flex !important; flex-direction:column !important; align-items:center !important; justify-content:center !important; gap:3px !important;
}
div[class*="st-key-home_nav_bar"] button [data-testid="stIconMaterial"] {
 font-size:21px !important; line-height:1 !important; color:inherit !important;
}
/* Navegación premium: icono centrado arriba y etiqueta debajo */
div[class*="st-key-home_nav_bar"] button {
 position:relative !important; display:block !important;
 height:66px !important; min-height:66px !important; padding:0 2px !important;
}
div[class*="st-key-home_nav_bar"] button [data-testid="stIconMaterial"] {
 position:absolute !important; top:8px !important; left:50% !important;
 transform:translateX(-50%) !important; margin:0 !important;
 font-size:21px !important; line-height:1 !important;
}
div[class*="st-key-home_nav_bar"] button [data-testid="stMarkdownContainer"] {
 position:absolute !important; left:2px !important; right:2px !important;
 bottom:7px !important; width:auto !important; margin:0 !important;
 text-align:center !important; line-height:1 !important;
}
div[class*="st-key-home_nav_bar"] button [data-testid="stMarkdownContainer"] p {
 margin:0 !important; padding:0 !important; text-align:center !important;
 font-size:.65rem !important; line-height:1 !important; letter-spacing:.045em !important;
 white-space:nowrap !important; overflow:visible !important; text-overflow:clip !important;
}
@media(max-width:640px) {
 div[class*="st-key-home_nav_bar"] button { height:64px !important; min-height:64px !important; }
 div[class*="st-key-home_nav_bar"] button [data-testid="stIconMaterial"] { top:7px !important; font-size:20px !important; }
 div[class*="st-key-home_nav_bar"] button [data-testid="stMarkdownContainer"] { bottom:7px !important; }
 div[class*="st-key-home_nav_bar"] button [data-testid="stMarkdownContainer"] p { font-size:.62rem !important; }
}
div[class*="st-key-home_topnav_stats"] button:hover, div[class*="st-key-home_topnav_goals"] button:hover,
div[class*="st-key-home_topnav_corners"] button:hover, div[class*="st-key-home_topnav_h2h"] button:hover, div[class*="st-key-home_topnav_tracker"] button:hover {
 border-color:#D5B33D !important; background:linear-gradient(145deg,#302A19,#191A1D) !important;
 color:#FFE477 !important; transform:translateY(-1px) !important;
}
div[class*="st-key-home_topnav_stats"] button[kind="primary"], div[class*="st-key-home_topnav_goals"] button[kind="primary"], div[class*="st-key-home_topnav_corners"] button[kind="primary"], div[class*="st-key-home_topnav_h2h"] button[kind="primary"], div[class*="st-key-home_topnav_tracker"] button[kind="primary"] {
 background:#E8CC70 !important; background-color:#E8CC70 !important;
 border:2px solid #F5E3A4 !important; color:#111419 !important;
 box-shadow:0 0 0 1px rgba(232,204,112,.16),0 0 12px rgba(232,204,112,.20) !important;
 font-weight:900 !important;
}
div[class*="st-key-home_topnav_stats"] button[kind="primary"]:hover,
div[class*="st-key-home_topnav_goals"] button[kind="primary"]:hover,
div[class*="st-key-home_topnav_corners"] button[kind="primary"]:hover,
div[class*="st-key-home_topnav_h2h"] button[kind="primary"]:hover, div[class*="st-key-home_topnav_tracker"] button[kind="primary"]:hover {
 background:#EED88F !important; border-color:#F8EBC1 !important;
 color:#111419 !important; box-shadow:0 0 15px rgba(232,204,112,.28) !important;
}
/* Buscador principal debajo de la marca, en su posición fija original. */
div[class*="st-key-home_search_form"] {
 position:static !important; top:auto !important; left:auto !important; right:auto !important;
 z-index:auto !important; width:auto !important; max-width:none !important;
 margin:0 !important; padding:0 !important; box-sizing:border-box !important;
 background:transparent !important;
}
div[class*="st-key-home_search_bar"] {
 position:fixed !important; top:215px !important; left:0 !important; right:0 !important;
 z-index:2147483002 !important; width:100vw !important; max-width:100vw !important;
 margin:0 !important; padding:0 !important; box-sizing:border-box !important;
 background:rgba(11,13,16,.98) !important;
}

div[class*="st-key-home_search_bar"] [data-testid="stHorizontalBlock"] { display:grid !important; grid-template-columns:minmax(0,1fr) 48px !important; grid-template-rows:48px !important; gap:0 !important; width:100vw !important; max-width:100vw !important; box-sizing:border-box !important; overflow:hidden !important; margin:0 !important; padding:0 !important; }
div[class*="st-key-home_search_bar"] [data-testid="column"]:nth-child(1) { grid-column:1 !important; width:100% !important; max-width:100% !important; min-width:0 !important; }
div[class*="st-key-home_search_bar"] [data-testid="column"]:nth-child(2) { grid-column:2 !important; width:48px !important; max-width:48px !important; min-width:48px !important; }
div[class*="st-key-home_search_bar"] [data-testid="column"] > div, div[class*="st-key-home_search_bar"] [data-testid="stTextInput"], div[class*="st-key-home_search_bar"] [data-testid="stTextInput"] > div { width:100% !important; min-width:0 !important; max-width:100% !important; margin:0 !important; }
div[class*="st-key-home_search_bar"] [data-testid="column"] { display:block !important; min-width:0 !important; padding:0 !important; margin:0 !important; }
div[class*="st-key-home_search_bar"] [data-testid="column"]:nth-child(1) { grid-column:1 !important; width:100% !important; max-width:100% !important; min-width:0 !important; }
div[class*="st-key-home_search_bar"] [data-testid="column"]:nth-child(2) { grid-column:2 !important; width:48px !important; max-width:48px !important; min-width:48px !important; }
div[class*="st-key-home_search_bar"] [data-testid="column"]:nth-child(2) > div,
div[class*="st-key-home_search_bar"] [class*="st-key-home_search_button"],
div[class*="st-key-home_search_bar"] [class*="st-key-home_search_button"] > div,
div[class*="st-key-home_search_bar"] [class*="st-key-home_search_button"] [data-testid="stButton"] { width:48px !important; min-width:48px !important; max-width:48px !important; margin:0 !important; padding:0 !important; }
div[class*="st-key-home_search_bar"] [data-testid="stHorizontalBlock"] > div { background:transparent !important; box-shadow:none !important; }
div[class*="st-key-home_search_bar"] [data-testid="stTextInput"] > div { border-radius:12px 0 0 12px !important; overflow:hidden !important; }
div[class*="st-key-home_search_button"] button { display:flex !important; align-items:center !important; justify-content:center !important; overflow:visible !important; }
div[class*="st-key-home_search_bar"] input,
div[class*="st-key-home_search_bar"] input:focus,
div[class*="st-key-home_search_bar"] input:focus-visible,
div[class*="st-key-home_search_bar"] input:active,
div[class*="st-key-home_search_bar"] input:not(:placeholder-shown) {
 min-height:48px !important; height:48px !important; padding:0 13px !important;
 border:1.5px solid #A88632 !important; border-right:0 !important; border-radius:12px 0 0 12px !important;
 background:linear-gradient(135deg,#202329,#111419) !important;
 color:#F5F5F5 !important;
 -webkit-text-fill-color:#F5F5F5 !important;
 -webkit-text-stroke:0 !important; mix-blend-mode:normal !important;
 caret-color:#F5F5F5 !important; opacity:1 !important; visibility:visible !important;
 text-shadow:none !important; filter:none !important;
 font-size:.86rem !important; font-weight:550 !important;
 box-shadow:inset 0 1px 0 #ffffff0a,0 3px 12px #0004 !important;
}
div[class*="st-key-home_search_bar"] input::placeholder { color:#A5AAB4 !important; -webkit-text-fill-color:#A5AAB4 !important; opacity:1 !important; }
div[class*="st-key-home_search_button"] { margin:0 !important; }
div[class*="st-key-home_search_button"] button {
 min-height:48px !important; height:48px !important; width:48px !important; min-width:48px !important; max-width:48px !important; padding:0 !important; box-sizing:border-box !important;
 border:1.5px solid #D4AD37 !important; border-left:0 !important; border-radius:0 12px 12px 0 !important;
 background:linear-gradient(145deg,#FFE566,#E6AD08) !important; color:#171717 !important;
}
div[class*="st-key-home_search_button"] button [data-testid="stIconMaterial"] { color:#171717 !important; }
@media(max-width:640px) {
 div[class*="st-key-home_nav_bar"] [data-testid="stHorizontalBlock"] { grid-template-columns:repeat(5,minmax(0,1fr)) !important; gap:5px !important; column-gap:7px !important; }
 div[class*="st-key-home_topnav_stats"] button, div[class*="st-key-home_topnav_goals"] button, div[class*="st-key-home_topnav_corners"] button, div[class*="st-key-home_topnav_h2h"] button, div[class*="st-key-home_topnav_tracker"] button {
  height:54px !important; min-height:54px !important; padding:4px 2px !important; font-size:1rem !important; letter-spacing:0 !important; border-radius:13px !important;
  box-shadow:0 3px 10px rgba(15,23,42,.10),inset 0 1px 0 rgba(255,255,255,.12) !important;
 }
}
</style>
""", unsafe_allow_html=True)
# El formulario evita reruns por cada carácter: solo envía la consulta al pulsar Enter o la lupa.
search_clicked = False
with st.form(key="home_search_form", clear_on_submit=False, border=False):
    with st.container(key="home_search_bar"):
        _home_search_cols = st.columns([12, 1], gap=None)
        with _home_search_cols[0]:
            st.text_input(
                "Buscar equipo o liga",
                key="search_goal_matches",
                placeholder="Buscar equipo, liga o partido...",
                label_visibility="collapsed",
            )
        with _home_search_cols[1]:
            search_clicked = st.form_submit_button("", key="home_search_button", icon=":material/search:", help="Buscar equipo o liga", use_container_width=True)
if not str(st.session_state.get("search_goal_matches", "") or "").strip():
    st.session_state.pop("live_search_query", None)
    st.session_state.pop("live_search_message", None)
    st.session_state.pop("live_search_submit_requested", None)
_home_selected_fixture = st.session_state.get("selected_live_fixture") or {}
_home_selected_id = str(((_home_selected_fixture.get("fixture") or {}).get("id")) or st.session_state.get("selected_live_fixture_id") or "")
_home_tool_state = st.session_state.get("main_fixture_tool") or {}
_home_active_tool = _home_tool_state.get("tool") if str(_home_tool_state.get("fixture_id")) == _home_selected_id else None
_home_active_market = _home_tool_state.get("market") if str(_home_tool_state.get("fixture_id")) == _home_selected_id else None
with st.container(key="home_nav_bar"):
    _home_nav_cols = st.columns(5, gap="small")
    with _home_nav_cols[0]:
        _home_stats_clicked = st.button("STATS", key="home_topnav_stats", icon=":material/query_stats:", use_container_width=True, type="primary" if _home_active_tool in {"stats", "standings"} else "secondary", disabled=not bool(_home_selected_id))
    with _home_nav_cols[1]:
        _home_goals_clicked = st.button("GOLES", key="home_topnav_goals", icon=":material/sports_soccer:", use_container_width=True, type="primary" if _home_active_market == "goals" else "secondary", disabled=not bool(_home_selected_id))
    with _home_nav_cols[2]:
        _home_corners_clicked = st.button("CÓRNERS", key="home_topnav_corners", icon=":material/flag:", use_container_width=True, type="primary" if _home_active_market == "corners" else "secondary", disabled=not bool(_home_selected_id))
    with _home_nav_cols[3]:
        _home_h2h_clicked = st.button("H2H", key="home_topnav_h2h", icon=":material/groups:", use_container_width=True, type="primary" if _home_active_tool == "h2h" else "secondary", disabled=not bool(_home_selected_id))
    with _home_nav_cols[4]:
        _home_tracker_clicked = st.button("TRACKER", key="home_topnav_tracker", icon=":material/sports_soccer:", use_container_width=True, type="primary" if _home_active_tool == "tracker" else "secondary", disabled=not bool(_home_selected_id))
    if _home_stats_clicked:
        st.session_state["main_fixture_tool"] = {"fixture_id": _home_selected_id, "tool": "stats"}
        st.rerun()
    if _home_goals_clicked:
        st.session_state["main_fixture_tool"] = {"fixture_id": _home_selected_id, "tool": "market", "market": "goals"}
        st.rerun()
    if _home_corners_clicked:
        st.session_state["main_fixture_tool"] = {"fixture_id": _home_selected_id, "tool": "market", "market": "corners"}
        st.rerun()
    if _home_h2h_clicked:
        st.session_state["main_fixture_tool"] = {"fixture_id": _home_selected_id, "tool": "h2h"}
        st.rerun()
    if _home_tracker_clicked:
        st.session_state["main_fixture_tool"] = {"fixture_id": _home_selected_id, "tool": "tracker"}
        st.rerun()

# Selector de apariencia: ubicado debajo de la navegación fija, visible en móvil y escritorio.
with st.container(key="appearance_switch"):
    st.radio(
        "Apariencia",
        options=["🌙", "☀️"],
        index=0,
        horizontal=True,
        key="appearance_mode",
        label_visibility="collapsed",
    )

if st.session_state.get("appearance_mode") in {"☀️", "☀️ Claro"}:
    st.markdown("""
    <style>
      /* PALETA CLARA FOOTBALL LAB — solo se activa al elegir ☀️ Claro. */
      :root { color-scheme:light; --fl-bg:#F4F6F9; --fl-surface:#FFFFFF; --fl-text:#20242C; --fl-muted:#68717F; --fl-gold:#B58A00; --fl-border:#DDE2E9; }
      /* Flecha de regreso: adaptar solo el botón al modo claro. */
      html body .stApp [class*="st-key-analysis_page_nav"] [class*="st-key-topnav_back_"] button {
        background:linear-gradient(145deg,#FFFFFF 0%,#FFFDF6 68%,#FFF4D4 100%) !important;
        border:2px solid #E5B800 !important;
        box-shadow:0 3px 12px rgba(181,138,0,.22),0 0 0 1px rgba(229,184,0,.10),inset 0 1px 0 rgba(255,255,255,.98) !important;
      }
      html body .stApp [class*="st-key-analysis_page_nav"] [class*="st-key-topnav_back_"] button::before {
        filter:drop-shadow(0 0 2px rgba(229,184,0,.28)) !important;
      }
      html body .stApp [class*="st-key-analysis_page_nav"] [class*="st-key-topnav_back_"] button:hover {
        background:linear-gradient(145deg,#FFFDF5 0%,#FFF3C4 100%) !important;
        border-color:#D6A600 !important;
        box-shadow:0 4px 15px rgba(181,138,0,.28),inset 0 1px 0 rgba(255,255,255,.98) !important;
      }
      /* Buscador fijo: paleta clara y unión real entre campo y lupa. */
      html body .stApp div[class*="st-key-home_search_bar"] { background:rgba(244,246,249,.98) !important; box-shadow:none !important; }
      html body .stApp div[class*="st-key-home_search_bar"] [data-testid="stHorizontalBlock"] { gap:0 !important; column-gap:0 !important; }
      html body .stApp div[class*="st-key-home_search_bar"] [data-testid="column"] { padding:0 !important; margin:0 !important; background:transparent !important; box-shadow:none !important; }
      html body .stApp div[class*="st-key-home_search_bar"] input,
      html body .stApp div[class*="st-key-home_search_bar"] input:focus,
      html body .stApp div[class*="st-key-home_search_bar"] input:focus-visible,
      html body .stApp div[class*="st-key-home_search_bar"] input:active,
      html body .stApp div[class*="st-key-home_search_bar"] input:not(:placeholder-shown) {
        background:linear-gradient(135deg,#FFFFFF 0%,#F8F9FB 62%,#FFF8E6 100%) !important;
        color:#303744 !important; -webkit-text-fill-color:#303744 !important;
        -webkit-text-stroke:0 !important; mix-blend-mode:normal !important;
        caret-color:#303744 !important; opacity:1 !important; visibility:visible !important;
        text-shadow:none !important; filter:none !important;
        border:1.5px solid #C7A43A !important; border-right:0 !important;
        box-shadow:inset 0 1px 0 rgba(255,255,255,.95) !important;
      }
      html body .stApp div[class*="st-key-home_search_bar"] input::placeholder { color:#7A8492 !important; -webkit-text-fill-color:#7A8492 !important; }
      html body .stApp div[class*="st-key-home_search_button"] button {
        background:linear-gradient(145deg,#FFE98A 0%,#F2C94C 52%,#DDAA16 100%) !important;
        color:#242424 !important; border:1.5px solid #C7A43A !important; border-left:0 !important;
        box-shadow:inset 0 1px 0 rgba(255,255,255,.65) !important;
      }
      html body .stApp div[class*="st-key-home_search_button"] button [data-testid="stIconMaterial"] { color:#242424 !important; }
      /* CTA principal: adaptar únicamente el color de los dos textos secundarios al modo claro. */
      html body .stApp [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p:nth-of-type(2) {
        color:#303744 !important;
        -webkit-text-fill-color:#303744 !important;
      }
      html body .stApp [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p:nth-of-type(3) {
        color:#68717F !important;
        -webkit-text-fill-color:#68717F !important;
      }
      /* H2H: adaptar tarjetas y métricas al modo claro sin alterar estructura ni cálculos. */
      html body .stApp .h2h-sample-card,
      html body .stApp .h2h-result-card,
      html body .stApp .h2h-secondary-card {
        background:linear-gradient(145deg,#FFFFFF 0%,#F5F7FA 100%) !important;
        border:1px solid #D8C27A !important;
        box-shadow:0 4px 12px rgba(31,41,55,.07) !important;
        color:#303744 !important;
      }
      html body .stApp .h2h-summary-label {
        color:#68717F !important;
        -webkit-text-fill-color:#68717F !important;
      }
      html body .stApp .h2h-sample-value,
      html body .stApp .h2h-result-count,
      html body .stApp .h2h-secondary-value {
        color:#987300 !important;
        -webkit-text-fill-color:#987300 !important;
      }
      /* Histórico de córners: reducir el amarillo y priorizar lectura en modo claro. */
      html body .stApp .corner-h2h-row.corner-history-grid {
        color:#394354 !important;
        border-bottom:1px solid #DDE2E9 !important;
        background:transparent !important;
      }
      html body .stApp .corner-h2h-row.corner-history-grid.corner-history-header {
        color:#68717F !important;
        background:#EEF1F5 !important;
        border-bottom:1px solid #D4DAE3 !important;
      }
      html body .stApp .corner-h2h-row.corner-history-grid.corner-history-header > span {
        color:#68717F !important;
        -webkit-text-fill-color:#68717F !important;
        font-weight:800 !important;
      }
      html body .stApp .corner-h2h-row.corner-history-grid:not(.corner-history-header) > span {
        color:#394354 !important;
        -webkit-text-fill-color:#394354 !important;
      }
      html body .stApp .corner-h2h-row.corner-history-grid .h2h-team {
        color:#586170 !important;
        -webkit-text-fill-color:#586170 !important;
        font-weight:600 !important;
      }
      html body .stApp .corner-h2h-row.corner-history-grid .corner-h2h-value {
        color:#394354 !important;
        -webkit-text-fill-color:#394354 !important;
        font-weight:750 !important;
      }
      html body .stApp .corner-h2h-row.corner-history-grid .corner-h2h-total {
        color:#987300 !important;
        -webkit-text-fill-color:#987300 !important;
        font-weight:850 !important;
      }
      html body .stApp .corner-h2h-row.corner-history-grid:not(.corner-history-header):nth-child(even) {
        background:rgba(238,241,245,.42) !important;
      }
      /* Promedio total de córners: adaptar solo colores en modo claro; conservar animación del valor. */
      html body .stApp .corner-total-average {
        background:linear-gradient(135deg,#FFFDF6 0%,#FBF3D8 58%,#F6E8B8 100%) !important;
        border-color:#D8C27A !important;
        box-shadow:0 0 0 1px rgba(216,194,122,.16),0 3px 12px rgba(31,41,55,.08) !important;
        color:#394354 !important;
      }
      html body .stApp .corner-total-average b {
        color:#68717F !important;
        -webkit-text-fill-color:#68717F !important;
      }
      html body .stApp .corner-total-average span {
        background:#F5E7B0 !important;
        background-color:#F5E7B0 !important;
        border-color:#D8C27A !important;
        color:#806000 !important;
        -webkit-text-fill-color:#806000 !important;
        /* Se conserva intacta la animación de titileo original. */
      }
      html body .stApp .corner-period-card { background:linear-gradient(145deg,#FFFFFF 0%,#F5F7FA 100%) !important; border-color:#D8C27A !important; }
      /* Botón VER HISTÓRICO de córners: forzar paleta clara en todos los niveles de Streamlit. */
      html body .stApp div[class*="st-key-corner_h2h_"] button,
      html body .stApp div[class*="st-key-corner_h2h_"] [data-testid="stBaseButton-secondary"],
      html body .stApp div[class*="st-key-corner_h2h_"] [data-testid="stBaseButton-primary"] {
        background:#F7F4EA !important;
        background-image:linear-gradient(145deg,#FFFFFF 0%,#F5F7FA 72%,#FBF6E6 100%) !important;
        background-color:#F7F4EA !important;
        border:1.5px solid #D8C27A !important;
        color:#806000 !important;
        -webkit-text-fill-color:#806000 !important;
        box-shadow:inset 0 1px 0 rgba(255,255,255,.95),0 3px 10px rgba(31,41,55,.09) !important;
      }
      html body .stApp div[class*="st-key-corner_h2h_"] button *,
      html body .stApp div[class*="st-key-corner_h2h_"] button p,
      html body .stApp div[class*="st-key-corner_h2h_"] button span {
        color:#806000 !important;
        -webkit-text-fill-color:#806000 !important;
      }
      html body .stApp div[class*="st-key-corner_h2h_"] button::before {
        background:linear-gradient(145deg,#F9F1D8,#EFE3BD) !important;
        border-color:#D8C27A !important;
        color:#987300 !important;
        -webkit-text-fill-color:#987300 !important;
      }
      html body .stApp div[class*="st-key-corner_h2h_"] button::after {
        color:#987300 !important;
        -webkit-text-fill-color:#987300 !important;
      }
      html body .stApp div[class*="st-key-corner_h2h_"] button:hover {
        background:#FFFDF5 !important;
        background-image:linear-gradient(145deg,#FFFDF5 0%,#F7EBC5 100%) !important;
        border-color:#B58A00 !important;
        color:#705400 !important;
        -webkit-text-fill-color:#705400 !important;
      }
      html body .stApp div[class*="st-key-corner_h2h_"] button:hover *,
      html body .stApp div[class*="st-key-corner_h2h_"] button:hover::after {
        color:#705400 !important;
        -webkit-text-fill-color:#705400 !important;
      }
      html body .stApp div[class*="st-key-corner_h2h_"] button:hover::before {
        background:#F3E5B8 !important;
        border-color:#B58A00 !important;
        color:#806000 !important;
      }
      /* Promedio de córners: adaptar el distintivo al modo claro. */
      html body .stApp .corner-average-pill {
        background:linear-gradient(145deg,#FFFFFF 0%,#F5F7FA 100%) !important;
        border-color:#D8C27A !important;
        box-shadow:0 3px 10px rgba(31,41,55,.08) !important;
      }
      html body .stApp .corner-average-pill span:first-child {
        color:#68717F !important;
        -webkit-text-fill-color:#68717F !important;
      }
      html body .stApp .corner-average-pill span:last-child {
        background:#F5E7B0 !important;
        border-color:#D8C27A !important;
        color:#806000 !important;
        -webkit-text-fill-color:#806000 !important;
      }
      html body .stApp .corner-period-label { color:#68717F !important; -webkit-text-fill-color:#68717F !important; }
      html body .stApp .corner-period-value { color:#987300 !important; -webkit-text-fill-color:#987300 !important; }
      html body .stApp .corner-period-note { color:#586170 !important; -webkit-text-fill-color:#586170 !important; }
      html body .stApp .h2h-period-card {
        background:linear-gradient(145deg,#FFFFFF 0%,#F5F7FA 100%) !important;
        border:1px solid #D8C27A !important;
        box-shadow:0 4px 12px rgba(31,41,55,.07) !important;
        color:#303744 !important;
      }
      html body .stApp .h2h-period-value {
        color:#987300 !important;
        -webkit-text-fill-color:#987300 !important;
      }
      html body .stApp .h2h-period-note {
        color:#586170 !important;
        -webkit-text-fill-color:#586170 !important;
      }
      html body .stApp .h2h-result-pct,
      html body .stApp .h2h-secondary-pct,
      html body .stApp .h2h-secondary-note {
        color:#586170 !important;
        -webkit-text-fill-color:#586170 !important;
      }
      html body .stApp .h2h-distribution {
        background:linear-gradient(135deg,#FFFFFF 0%,#F5F7FA 100%) !important;
        border:1px solid #D8C27A !important;
        box-shadow:0 4px 12px rgba(31,41,55,.06) !important;
      }
      html body .stApp .h2h-distribution-heading,
      html body .stApp .h2h-distribution-legend {
        color:#586170 !important;
        -webkit-text-fill-color:#586170 !important;
      }
      html body .stApp .h2h-distribution-heading strong {
        color:#FFFFFF !important;
        -webkit-text-fill-color:#FFFFFF !important;
        background:linear-gradient(135deg,#B58A00,#987300) !important;
        border-color:#B58A00 !important;
      }
      html body .stApp .h2h-distribution-track {
        background:#E5E9EF !important;
        box-shadow:inset 0 1px 3px rgba(31,41,55,.12) !important;
      }
      html body .stApp .h2h-distribution-track .h2h-distribution-home {
        background:#D5A91E !important;
      }
      html body .stApp .h2h-distribution-track .h2h-distribution-draw {
        background:#397FC4 !important;
      }
      html body .stApp .h2h-distribution-track .h2h-distribution-away {
        background:#29966B !important;
      }
      html body .stApp .h2h-distribution-legend span {
        display:inline-flex !important;
        align-items:center !important;
        gap:5px !important;
        color:#586170 !important;
        -webkit-text-fill-color:#586170 !important;
        font-weight:750 !important;
      }
      html body .stApp .h2h-distribution-legend i {
        display:inline-block !important;
        width:9px !important;
        height:9px !important;
        flex:0 0 9px !important;
        border-radius:50% !important;
      }
      html body .stApp .h2h-legend-local i { background:#D5A91E !important; }
      html body .stApp .h2h-legend-draw i { background:#397FC4 !important; }
      html body .stApp .h2h-legend-away i { background:#29966B !important; }
      html body .stApp .h2h-distribution-track .h2h-distribution-away {
        background:#3D9B78 !important;
      }
      html body .stApp .h2h-history-list,
      html body .stApp .h2h-match-row {
        background:#FFFFFF !important;
        color:#303744 !important;
        border-color:#DDE2E9 !important;
      }
      html body .stApp .h2h-date,
      html body .stApp .h2h-team {
        color:#586170 !important;
        -webkit-text-fill-color:#586170 !important;
      }
      /* H2H: una sola franja horizontal completa; el balón queda superpuesto al extremo */
      html body .stApp [class*="st-key-h2h_history_row_"] {
        position:relative !important; width:100% !important;
        max-width:100% !important; overflow:visible !important;
        perspective:1000px !important; margin:0 !important;
      }
      html body .stApp [class*="st-key-h2h_history_row_"] .h2h-row-front-open { display:none !important; }
       /* Historial H2H claro: alternancia blanco/gris suave, sin líneas divisorias. */
       html body .stApp [class*="st-key-h2h_history_row_"] .h2h-match-row-full.h2h-stripe-even { background:#FFFFFF !important; border:0 !important; border-bottom:0 !important; }
       html body .stApp [class*="st-key-h2h_history_row_"] .h2h-match-row-full.h2h-stripe-odd { background:#F6F7F9 !important; border:0 !important; border-bottom:0 !important; }
      html body .stApp [class*="st-key-h2h_history_row_"] .h2h-match-row-full {
        width:100% !important; min-height:52px !important; box-sizing:border-box !important;
        /* Canal exclusivo para el botón del balón: nunca invade el marcador. */
        padding:8px 48px 8px 10px !important; gap:8px !important;
        grid-template-columns:82px minmax(0,1fr) 70px minmax(0,1fr) !important;
        position:relative !important; isolation:isolate !important;
      }
      html body .stApp [class*="st-key-h2h_history_row_"] .h2h-match-row-full .h2h-score {
        position:relative !important; z-index:30 !important; justify-self:center !important;
        display:inline-flex !important; white-space:nowrap !important;
        background:#20232B !important; border:1px solid #D6B84C !important;
        border-radius:9px !important; padding:6px 10px !important;
      }
      /* El marcador queda visualmente por encima del separador entre partidos. */
      html body .stApp [class*="st-key-h2h_history_row_"] .h2h-match-row-full .h2h-score {
        position:relative !important; z-index:30 !important;
        justify-self:center !important;
        white-space:nowrap !important;
        background:#F5F7FA !important; box-shadow:0 0 0 3px #FFFFFF !important;
        margin:2px 0 !important;
      }
      html body .stApp [class*="st-key-h2h_history_row_"] [class*="st-key-h2h_goal_timeline_btn_"] {
        position:absolute !important; right:8px !important; top:12px !important;
        transform:none !important; width:29px !important;
        min-width:29px !important; z-index:8 !important;
        margin:0 !important; padding:0 !important;
      }
      html body .stApp [class*="st-key-h2h_history_row_"] [class*="st-key-h2h_goal_timeline_btn_"] button {
        width:27px !important; min-width:27px !important;
        height:27px !important; min-height:27px !important;
        padding:0 !important; border-radius:50% !important;
        border:1px solid #FACC15 !important;
        background:radial-gradient(circle at 35% 25%,#FFF1A6 0%,#FACC15 55%,#9A7000 100%) !important;
        color:#171717 !important; font-size:12px !important;
        box-shadow:0 0 7px #FACC1545 !important;
      }
      html body .stApp [class*="st-key-h2h_history_row_"] .h2h-goal-timeline {
        width:100% !important; box-sizing:border-box !important;
        margin:0 0 9px !important; padding:10px 14px !important;
        animation:h2hFlipReveal .48s cubic-bezier(.2,.75,.25,1) both !important;
        transform-origin:center center !important;
      }
      @keyframes h2hFlipReveal {
        0% { opacity:0; transform:rotateX(-72deg) scale(.985); }
        65% { opacity:1; transform:rotateX(8deg) scale(1.005); }
        100% { opacity:1; transform:rotateX(0) scale(1); }
      }
      @media(max-width:640px) {
        html body .stApp [class*="st-key-h2h_history_row_"] .h2h-match-row-full {
          min-height:46px !important;
          grid-template-columns:60px minmax(0,1fr) 48px minmax(0,1fr) !important;
          padding:8px 40px 8px 5px !important; gap:3px !important;
        }
        html body .stApp [class*="st-key-h2h_history_row_"] .h2h-match-row-full .h2h-score {
          z-index:30 !important; min-width:54px !important; justify-self:center !important;
          white-space:nowrap !important; padding:5px 4px !important;
        }
        html body .stApp [class*="st-key-h2h_history_row_"] [class*="st-key-h2h_goal_timeline_btn_"] {
          right:7px !important; top:9px !important; width:25px !important; min-width:25px !important;
          z-index:8 !important;
        }
        html body .stApp [class*="st-key-h2h_history_row_"] [class*="st-key-h2h_goal_timeline_btn_"] button {
          width:24px !important; min-width:24px !important;
          height:24px !important; min-height:24px !important;
        }
      }
      @media(max-width:640px) {
        html body .stApp [class*="st-key-h2h_history_row_"] .h2h-goal-timeline { grid-template-columns:repeat(2,minmax(0,1fr)) !important; gap:4px !important; padding:5px !important; }
        html body .stApp [class*="st-key-h2h_history_row_"] .h2h-goal-event-row { grid-template-columns:22px 11px minmax(0,1fr) 35px !important; gap:2px !important; padding:3px !important; }
        html body .stApp [class*="st-key-h2h_history_row_"] .h2h-goal-score { width:34px !important; min-width:0 !important; height:22px !important; font-size:.56rem !important; padding:2px 1px !important; }
        html body .stApp [class*="st-key-h2h_history_row_"] .h2h-goal-event-row strong { font-size:.59rem !important; }
        html body .stApp [class*="st-key-h2h_history_row_"] .h2h-goal-event-row small { font-size:.52rem !important; }
      }
      [class*="st-key-h2h_goal_timeline_btn_"] button {
        width:25px !important; min-width:25px !important;
        height:25px !important; min-height:25px !important;
        padding:0 !important; border-radius:50% !important;
        border:1px solid #FACC15 !important;
        background:radial-gradient(circle at 35% 25%,#FFF1A6 0%,#FACC15 55%,#9A7000 100%) !important;
        color:#171717 !important; font-size:12px !important;
        box-shadow:0 0 7px #FACC1545 !important;
      }
      [class*="st-key-h2h_goal_timeline_btn_"] button:hover {
        transform:rotate(-10deg) scale(1.08) !important;
        box-shadow:0 0 0 3px #FACC1535,0 0 17px #FACC1580 !important;
      }
      .h2h-goal-timeline {
        display:grid !important; grid-template-columns:repeat(auto-fit,minmax(145px,1fr)) !important;
        gap:6px !important; margin:0 0 8px !important; padding:7px !important;
        border:1px solid rgba(250,204,21,.32); border-radius:10px;
        background:linear-gradient(145deg,#20232B,#12151A);
      }
      .h2h-goal-event-row {
        display:grid; grid-template-columns:25px 13px minmax(0,1fr) 38px;
        align-items:center; gap:3px; min-width:0; padding:3px 4px;
        border:1px solid rgba(255,255,255,.10); border-radius:7px;
        background:rgba(255,255,255,.045); box-sizing:border-box;
      }
      .h2h-goal-event-row:last-child { border-bottom:1px solid rgba(255,255,255,.10); }
      .h2h-goal-minute { color:#FACC15; font-size:.65rem; white-space:nowrap; }
      .h2h-goal-event-row > div { display:flex; flex-direction:column; min-width:0; gap:1px; }
      .h2h-goal-event-row strong { color:#F4F4F5; font-size:.62rem; line-height:1.1; overflow-wrap:anywhere; }
      .h2h-goal-event-row small { color:#A1A1AA; font-size:.53rem; line-height:1.05; overflow-wrap:anywhere; }
      .h2h-goal-score { color:#FACC15; font-size:.60rem; white-space:nowrap; display:inline-flex; align-items:center; justify-content:center; justify-self:end; width:36px; min-width:0; height:23px; box-sizing:border-box; padding:2px; line-height:1; border:1px solid rgba(250,204,21,.55); border-radius:6px; background:#20232B; position:relative; z-index:2; }
      html body .stApp [class*="st-key-h2h_history_row_"] .h2h-goal-timeline {
        background:linear-gradient(145deg,#FFFFFF,#F5F7FA) !important;
        border-color:#D8C27A !important;
      }
      html body .stApp [class*="st-key-h2h_history_row_"] .h2h-goal-event-row { border-bottom-color:#E7EAF0 !important; }
      html body .stApp [class*="st-key-h2h_history_row_"] .h2h-goal-event-row strong { color:#263142 !important; }
      html body .stApp [class*="st-key-h2h_history_row_"] .h2h-goal-event-row small { color:#586170 !important; }
      html body .stApp [class*="st-key-h2h_history_row_"] .h2h-goal-minute,
      html body .stApp [class*="st-key-h2h_history_row_"] .h2h-goal-score { color:#806000 !important; background:#FFFFFF !important; border-color:#D8C27A !important; }
      html body .stApp [class*="st-key-h2h_history_row_"] .h2h-match-row-full .h2h-score {
        display:inline-flex !important; align-items:center !important; justify-content:center !important;
        min-width:76px !important; min-height:36px !important; box-sizing:border-box !important;
        padding:6px 12px !important; border:1px solid #D6B84C !important; border-radius:9px !important;
        background:linear-gradient(145deg,#FFF7DC,#F5E9BD) !important;
        color:#8A6800 !important; font-size:1rem !important; font-weight:900 !important;
        line-height:1 !important; font-variant-numeric:tabular-nums !important;
        box-shadow:0 1px 3px rgba(138,104,0,.12) !important;
      }
      @media(max-width:640px) {
        html body .stApp [class*="st-key-h2h_history_row_"] .h2h-match-row-full .h2h-score {
          min-width:54px !important; min-height:30px !important; padding:5px 4px !important;
          font-size:.82rem !important; border-radius:8px !important;
        }
      }
      html,body,.stApp,[data-testid="stAppViewContainer"],section.main,.main,.block-container {
        background:#F4F6F9 !important; color:#20242C !important;
      }
      /* Proyección de tarjetas: adaptar el panel completo a la paleta clara. */
      html body .stApp .fl-yellow-analysis {
        background:linear-gradient(145deg,#FFFFFF,#F3F6FA) !important;
        color:#303744 !important;border-color:#D6B84C !important;
      }
      html body .stApp .fl-yellow-analysis header,
      html body .stApp .fl-yellow-analysis header strong {
        color:#293448 !important; font-family:inherit !important;
        font-size:clamp(1.15rem,2.1vw,1.45rem) !important;
        font-weight:800 !important; letter-spacing:.005em !important;
        line-height:1.25 !important; text-transform:none !important;
      }
      html body .stApp .fl-yellow-analysis .fl-yellow-grid article {
        background:#FFFFFF !important;border-color:#DDE2E9 !important;
      }
      html body .stApp .fl-yellow-analysis .fl-yellow-grid small,
      html body .stApp .fl-yellow-analysis .fl-yellow-grid span,
      html body .stApp .fl-yellow-analysis p { color:#68717F !important; }
      html body .stApp .fl-yellow-analysis .fl-yellow-grid b,
      html body .stApp .fl-yellow-analysis .fl-yellow-estimate strong { color:#987300 !important; }
      html body .stApp .fl-yellow-analysis .fl-yellow-estimate {
        background:linear-gradient(135deg,#FFF3C4,#FFF9E8) !important;
        border:2px solid #D4A91F !important;
        box-shadow:0 0 0 1px rgba(212,169,31,.16),0 0 14px rgba(212,169,31,.14) !important;
      }
      html body .stApp .fl-yellow-analysis .fl-yellow-estimate small { color:#806000 !important; }
      html body .stApp .fl-yellow-analysis .fl-yellow-estimate strong { text-shadow:none !important; }
      html body .stApp .fl-yellow-analysis .fl-yellow-card-icon { filter:drop-shadow(0 0 7px rgba(212,169,31,.45)) !important; }
      [data-testid="stHeader"] { background:rgba(244,246,249,.96) !important; }
      [data-testid="stSidebar"],[data-testid="stSidebar"] > div:first-child { background:#FFFFFF !important; border-right:1px solid #DDE2E9 !important; }
      html body .stApp p,html body .stApp label,html body .stApp li,html body .stApp [data-testid="stMarkdownContainer"] { color:#303744; }
      html body .stApp h1,html body .stApp h2,html body .stApp h3 { color:#9A7400 !important; }
      html body .stApp [data-testid="stCaptionContainer"],html body .stApp small { color:#68717F !important; }
      [data-testid="stMetric"] { background:#FFFFFF !important; border:1px solid #DDE2E9 !important; color:#20242C !important; }
      [data-testid="stMetric"] label,[data-testid="stMetric"] [data-testid="stMetricValue"] { color:#20242C !important; }
      [data-testid="stTabs"] button[role="tab"] { color:#586170 !important; }
      [data-testid="stTabs"] button[role="tab"][aria-selected="true"] { color:#9A7400 !important; border-bottom-color:#C59A18 !important; }
      [data-testid="stExpander"] { background:#FFFFFF !important; border:1px solid #DDE2E9 !important; color:#20242C !important; }
      [data-testid="stExpander"] summary,[data-testid="stExpander"] summary p { color:#303744 !important; }
      [data-testid="stDataFrame"],[data-testid="stTable"] { background:#FFFFFF !important; border:1px solid #DDE2E9 !important; }
      .stTextInput input,.stNumberInput input,.stTextArea textarea,.stDateInput input,.stSelectbox [data-baseweb="select"] > div {
        background:#FFFFFF !important; color:#20242C !important; -webkit-text-fill-color:#20242C !important; border-color:#CBD2DC !important;
      }
      .stTextInput input::placeholder,.stTextArea textarea::placeholder { color:#8992A0 !important; -webkit-text-fill-color:#8992A0 !important; }
      div.stButton > button[kind="secondary"] { background:linear-gradient(145deg,#FFFFFF,#F0F2F5) !important; color:#354052 !important; border-color:#C7A43A !important; }
      div.stButton > button[kind="secondary"]:hover { background:#FFF5D5 !important; color:#785B00 !important; border-color:#B58A00 !important; }
      .brand-header {
        background:linear-gradient(105deg,#FFFFFF 0%,#F2F4F7 52%,#FFFFFF 100%) !important;
        border-top-color:#D6B84C !important; border-bottom-color:#D6B84C !important;
        box-shadow:0 8px 24px rgba(31,41,55,.10),inset 0 1px 0 rgba(255,255,255,.9) !important;
      }
      .brand-title { color:#20242C !important; }
      .brand-subtitle { color:#737B89 !important; }
      .brand-pill { color:#16834B !important; background:#E8F7EF !important; border-color:#B8E4C9 !important; }
      div[class*="st-key-home_nav_bar"] { background:rgba(255,255,255,.98) !important; box-shadow:0 7px 18px rgba(31,41,55,.10) !important; }
      div[class*="st-key-home_topnav_stats"] button,div[class*="st-key-home_topnav_goals"] button,div[class*="st-key-home_topnav_corners"] button,div[class*="st-key-home_topnav_h2h"] button, div[class*="st-key-home_topnav_tracker"] button {
        background:linear-gradient(145deg,#FFFFFF,#F0F2F5) !important; color:#947000 !important; border-color:#C7A43A !important;
      }
      div[class*="st-key-home_topnav_stats"] button[kind="primary"],div[class*="st-key-home_topnav_goals"] button[kind="primary"],div[class*="st-key-home_topnav_corners"] button[kind="primary"],div[class*="st-key-home_topnav_h2h"] button[kind="primary"], div[class*="st-key-home_topnav_tracker"] button[kind="primary"] {
        background:#F6E6A8 !important; color:#332800 !important; border-color:#C49A20 !important;
      }
      [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button {
        background-color:#FFFFFF !important;
        background-image:radial-gradient(ellipse at 18% 48%,rgba(250,204,21,.18),transparent 43%),linear-gradient(132deg,#FFFFFF 0%,#F8F8F5 58%,#F3EBD4 100%) !important;
        color:#20242C !important;
        border-color:#D6B84C !important;
        box-shadow:inset 0 1px 0 rgba(255,255,255,.95),inset 0 0 26px rgba(181,138,0,.08),0 0 0 1px rgba(181,138,0,.18),0 8px 24px rgba(31,41,55,.12) !important;
      }
      [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button strong { color:#947000 !important; text-shadow:0 2px 10px rgba(181,138,0,.18) !important; }
      [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p:not(:has(strong)) { color:#9A7400 !important; }
      [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p:nth-of-type(3) { color:#68717F !important; -webkit-text-fill-color:#68717F !important; }
      [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button::before { background-color:#FFFFFF !important; box-shadow:0 0 26px rgba(181,138,0,.30),inset 0 0 22px rgba(181,138,0,.18) !important; }
      [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button:hover { background-color:#FFFFFF !important; }

      /* Mantener el escáner claro también durante hover, pulsación y foco. */
      [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button:hover,
      [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button:active,
      [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button:focus,
      [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button:focus-visible {
        background-color:#FFFFFF !important;
        background-image:radial-gradient(ellipse at 20% 50%,rgba(250,204,21,.17),transparent 42%),linear-gradient(135deg,#FFFFFF,#F2F4F7) !important;
        color:#20242C !important;
        border-color:#D6B84C !important;
        box-shadow:inset 0 0 24px rgba(181,138,0,.07),0 5px 18px rgba(31,41,55,.12) !important;
        outline-color:#D6B84C !important;
      }
      [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button:active {
        transform:scale(.99) !important;
      }
      .scan-running-status {
        color:#806000 !important;
        background:linear-gradient(110deg,#FFFFFF,#FFF8E5) !important;
        border:1px solid #D6B84C !important;
        box-shadow:0 5px 16px rgba(31,41,55,.07) !important;
      }
      .scan-running-status strong { color:#947000 !important; }
      .scan-code-icon { color:#B58A00 !important; text-shadow:0 0 12px rgba(181,138,0,.28) !important; }
      .scan-running-subtitle { color:#68717F !important; }
      .scan-sweep { background:linear-gradient(90deg,transparent,#C49A20,transparent) !important; }

      /* Las dos barras reales de progreso: pista gris azulada y avance dorado. */
      [class*="st-key-scan-progress"] [data-testid="stProgress"] {
        background:transparent !important;
      }
      /* Primera línea: pista vacía gris azulada. */
      [class*="st-key-scan-progress"] [data-testid="stProgress"] > div {
        height:10px !important;
        min-height:10px !important;
        border-radius:999px !important;
        overflow:hidden !important;
        background:#E8EDF4 !important;
        border:1px solid #D5DEE9 !important;
        box-shadow:inset 0 1px 2px rgba(31,41,55,.06) !important;
      }
      /* Segunda línea: progreso dorado independiente. */
      [class*="st-key-scan-progress"] [data-testid="stProgress"] [role="progressbar"] {
        height:8px !important;
        min-height:8px !important;
        margin-top:2px !important;
        border-radius:999px !important;
        overflow:hidden !important;
        background:#E8EDF4 !important;
        border:1px solid #D5DEE9 !important;
        box-shadow:inset 0 1px 2px rgba(31,41,55,.06) !important;
      }
      [class*="st-key-scan-progress"] [data-testid="stProgress"] [role="progressbar"] > div,
      [class*="st-key-scan-progress"] [data-testid="stProgress"] [role="progressbar"] > div > div {
        height:100% !important;
        border:0 !important;
        border-radius:999px !important;
        background:linear-gradient(90deg,#D6B84C 0%,#E8C85F 48%,#F2D77D 100%) !important;
        background-size:100% 100% !important;
        box-shadow:0 0 7px rgba(181,138,0,.16) !important;
        animation:none !important;
      }
      [class*="st-key-scan-progress"] .fl-scan-progress-head {
        display:flex !important; visibility:visible !important; opacity:1 !important;
        min-height:16px !important; margin:7px 0 2px !important;
      }
      [class*="st-key-scan-progress"] .fl-scan-progress-title {
        display:inline-block !important; visibility:visible !important; opacity:1 !important;
        color:#755800 !important; -webkit-text-fill-color:#755800 !important;
        font-size:11px !important; font-weight:900 !important; line-height:1.25 !important;
      }
      [class*="st-key-scan-progress"] .fl-scan-progress-percent {
        display:inline-block !important; visibility:visible !important; opacity:1 !important;
        color:#755800 !important; -webkit-text-fill-color:#755800 !important;
        font-size:12px !important; font-weight:900 !important; text-shadow:none !important;
      }
      [class*="st-key-scan-progress"] .fl-scan-progress-caption {
        display:flex !important; visibility:visible !important; opacity:1 !important;
        color:#174A80 !important; -webkit-text-fill-color:#174A80 !important;
        font-size:10px !important; font-weight:600 !important; line-height:1.35 !important;
      }
      [class*="st-key-scan-progress"] .fl-scan-progress-caption.is-done {
        color:#174A80 !important; -webkit-text-fill-color:#174A80 !important;
      }
      .fl-scan-progress-caption .fl-live-dot { background:#C49A20 !important; box-shadow:none !important; }
      .fl-scan-progress-caption.is-done .fl-live-dot { background:#258653 !important; }

      [class*="st-key-analysis_scan_radar_goals_"] [data-testid="stButton"] > button:hover,
      [class*="st-key-analysis_scan_goals_"] [data-testid="stButton"] > button:hover,
      [class*="st-key-analysis_scan_radar_corners_"] [data-testid="stButton"] > button:hover,
      [class*="st-key-analysis_scan_corners_"] [data-testid="stButton"] > button:hover,
      [class*="st-key-analysis_scan_radar_goals_"] [data-testid="stButton"] > button:active,
      [class*="st-key-analysis_scan_goals_"] [data-testid="stButton"] > button:active,
      [class*="st-key-analysis_scan_radar_corners_"] [data-testid="stButton"] > button:active,
      [class*="st-key-analysis_scan_corners_"] [data-testid="stButton"] > button:active {
        background:linear-gradient(145deg,#FFF8E5,#F2E7C5) !important;
        color:#755800 !important;
        border-color:#D6B84C !important;
        box-shadow:0 4px 14px rgba(181,138,0,.13) !important;
      }

      [class*="st-key-search_goal_matches"] [data-testid="stTextInput"] > div { background:#FFFFFF !important; border-color:#C7A43A !important; }
      [class*="st-key-search_goal_matches"] input,[data-testid="stSidebar"] [class*="st-key-search_goal_matches"] input {
        color:#20242C !important; -webkit-text-fill-color:#20242C !important; caret-color:#9A7400 !important;
      }
      [class*="st-key-search_goal_matches"] input::placeholder { color:#8992A0 !important; -webkit-text-fill-color:#8992A0 !important; }
      [class*="st-key-auto_refresh_control_card"] [data-testid="stToggle"] label p,[class*="st-key-sound_control_card"] [data-testid="stToggle"] label p { color:#806000 !important; }
      [class*="st-key-auto_refresh_control_card"] [role="switch"],[class*="st-key-sound_control_card"] [role="switch"] { background:#F2E7C5 !important; }
      [class*="st-key-control_row"] button[kind="primary"] { background:#FACC15 !important; color:#171717 !important; }
      .signal-card,.tip-card,.risk-tip-card,.live-match-card,.fixture-hero,.loading-brand {
        background:linear-gradient(145deg,#FFFFFF 0%,#F3F5F8 100%) !important;
        border-color:#D4B65B !important; box-shadow:0 6px 20px rgba(31,41,55,.08) !important; color:#20242C !important;
      }
      .signal-title,.tip-card-title,.tip-card-empty .tip-card-title,.live-match-team,.fixture-hero-team { color:#20242C !important; }
      .signal-kicker,.signal-pick,.tip-card-label,.tip-card-meta,.live-match-league span,.fixture-clock,.loading-title { color:#947000 !important; }
      .signal-meta,.tip-card-empty .tip-card-meta,.live-match-league,.fixture-hero-top,.fixture-hero-league,.loading-subtitle { color:#68717F !important; }
      .live-match-score,.fixture-hero-score { background:#FFF7DC !important; color:#8A6800 !important; border-color:#D6B84C !important; }
      .live-stats-panel { background:linear-gradient(145deg,#FFFFFF,#F1F4F8) !important; color:#20242C !important; border-color:#D6B84C !important; box-shadow:0 8px 22px rgba(31,41,55,.09) !important; }
      .live-stats-heading { color:#947000 !important; border-bottom-color:#E3D39C !important; text-shadow:none !important; }
      .live-stats-scoreboard { background:linear-gradient(180deg,#F8FAFC,#EEF1F5) !important; }
      .live-stats-league,.live-stats-team,.live-stats-team strong { color:#303744 !important; }
      .live-stats-score { background:#FFFFFF !important; color:#947000 !important; border-color:#D6B84C !important; text-shadow:none !important; }
      .live-stats-metrics { color:#303744 !important; }
      /* Estadísticas: contraste azul oscuro para etiquetas y cifras en modo claro. */
      .live-stat-values,
      .live-stat-values span {
        color:#174A80 !important;
        -webkit-text-fill-color:#174A80 !important;
        font-weight:650 !important;
      }
      .live-stat-values strong,
      .live-stat-values strong:first-child,
      .live-stat-values strong:last-child {
        color:#123F70 !important;
        -webkit-text-fill-color:#123F70 !important;
        font-weight:900 !important;
      }
      .live-stat-track { background:#DCE4EF !important; }
      .live-stats-pitch .pitch-minute,
      .live-stats-pitch .pitch-score,
      .live-stats-pitch .pitch-team,
      .live-stats-pitch .pitch-team span {
        color:#FFFFFF !important;
      }

      .fl-standings-scroll { background:#FFFFFF !important; border-color:#D6B84C !important; box-shadow:0 8px 22px rgba(31,41,55,.08) !important; }
      .fl-standings-table { color:#303744 !important; }
      .fl-standings-table th { background:#F4F0E2 !important; color:#785B00 !important; border-bottom-color:#D8C47E !important; }
      .fl-standings-table td { background:#FFFFFF !important; color:#303744 !important; border-bottom-color:#E7EAF0 !important; }
      .fl-standings-table tbody tr:nth-child(even) td { background:#F6F7F9 !important; }
      .fl-standings-table .fl-standings-rank span { background:#F0F2F5 !important; color:#806000 !important; border-color:#DDE2E9 !important; }
      .fl-standings-table .fl-standings-team span { color:#20242C !important; }
      .fl-standings-table .fl-standings-points { color:#8A6800 !important; background:#FFF7DC !important; }
      .fl-standings-table tr.is-home-focus td { background:#E4F3FC !important; }
      .fl-standings-table tr.is-away-focus td { background:#FFF3C4 !important; }
      .fl-standings-table tr.is-home-focus .fl-standings-team span { color:#075985 !important; }
      .fl-standings-table tr.is-away-focus .fl-standings-team span { color:#806000 !important; }

      /* Resaltado de los dos equipos del partido en clasificación: mayor especificidad que el CSS interno de la tabla. */
      .fl-standings-scroll .fl-standings-table tbody tr.is-home-focus td {
        background:#E5F1FF !important;
        color:#174A80 !important;
        border-top:1px solid #9DBCE5 !important;
        border-bottom:1px solid #9DBCE5 !important;
      }
      .fl-standings-scroll .fl-standings-table tbody tr.is-home-focus td:first-child {
        box-shadow:inset 4px 0 0 #3978C8 !important;
      }
      .fl-standings-scroll .fl-standings-table tbody tr.is-home-focus .fl-standings-rank,
      .fl-standings-scroll .fl-standings-table tbody tr.is-home-focus .fl-standings-rank span {
        color:#174A80 !important;
        background:#D4E7FC !important;
        border-color:#8DB4E3 !important;
      }
      .fl-standings-scroll .fl-standings-table tbody tr.is-home-focus .fl-standings-team span {
        color:#123F70 !important;
        font-weight:950 !important;
      }
      .fl-standings-scroll .fl-standings-table tbody tr.is-away-focus td {
        background:#FFF3CC !important;
        color:#755800 !important;
        border-top:1px solid #E5CD7C !important;
        border-bottom:1px solid #E5CD7C !important;
      }
      .fl-standings-scroll .fl-standings-table tbody tr.is-away-focus td:first-child {
        box-shadow:inset 4px 0 0 #C49A20 !important;
      }
      .fl-standings-scroll .fl-standings-table tbody tr.is-away-focus .fl-standings-rank,
      .fl-standings-scroll .fl-standings-table tbody tr.is-away-focus .fl-standings-rank span {
        color:#755800 !important;
        background:#F9E7A7 !important;
        border-color:#D6B84C !important;
      }
      .fl-standings-scroll .fl-standings-table tbody tr.is-away-focus .fl-standings-team span {
        color:#684D00 !important;
        font-weight:950 !important;
      }

      .fl-standings-heading { background:linear-gradient(100deg,#FFF7DC,#FFFFFF) !important; border-color:#E2D39E !important; }
      .fl-standings-heading-title,.fl-standings-heading-league { color:#806000 !important; }
      .h2h-summary-card,.h2h-history-list,.h2h-match-row,.h2h-summary-layout {
        background:#FFFFFF !important; color:#303744 !important; border-color:#DDE2E9 !important;
      }
      .h2h-page-kicker,.h2h-summary-label,.h2h-match-row .h2h-date { color:#806000 !important; }
      .h2h-summary-value,.h2h-match-row .h2h-team { color:#20242C !important; }
      .fl-standings-table .fl-stat-win { color:#9A7400 !important; background:#FFF5CC !important; }
      .fl-standings-table .fl-stat-draw { color:#586170 !important; background:#EDF0F4 !important; }
      .fl-standings-table .fl-stat-loss { color:#C52F3B !important; background:#FDEBED !important; }
      /* Scanner en modo claro: estos overrides solo existen dentro del tema ☀️ Claro. */
      /* Liga del partido seleccionado: mismo dorado de selección, solo en modo claro. */
      [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"]:has(.fl-match-scoreboard.is-selected) > details > summary {
        background:linear-gradient(100deg,#FFF8E5,#FFF2C7) !important;
        border:1.5px solid #D6B84C !important;
        box-shadow:inset 3px 0 0 #B58A00,0 3px 9px rgba(181,138,0,.08) !important;
      }
      [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"]:has(.fl-match-scoreboard.is-selected) > details > summary p {
        color:#755800 !important;
        font-weight:800 !important;
      }
      [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"]:has(.fl-match-scoreboard.is-selected) > details > summary [data-testid="stExpanderToggleIcon"] {
        color:#947000 !important;
      }
      [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"]:has(.fl-match-scoreboard.is-selected) > details > summary:hover {
        background:#FFF2C7 !important;
        border-color:#B58A00 !important;
        box-shadow:inset 3px 0 0 #B58A00,0 4px 12px rgba(181,138,0,.11) !important;
      }

      [class*="st-key-live_now_section"] > div > [data-testid="stExpander"] > details > summary {
        background:#FFF2C7 !important; border:1px solid #D6B84C !important;
        box-shadow:0 5px 16px rgba(31,41,55,.07) !important;
      }
      [class*="st-key-live_now_section"] > div > [data-testid="stExpander"] > details > summary p {
        color:#755800 !important; text-shadow:none !important;
      }
      [class*="st-key-live_now_section"] > div > [data-testid="stExpander"] > details > summary::after {
        background:#E8CC70 !important; color:#332800 !important;
      }
      [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] > details > summary {
        background:linear-gradient(100deg,#FFFFFF,#F7F8FA) !important;
        border:1px solid #DDE2E9 !important; color:#263142 !important;
        box-shadow:0 2px 7px rgba(31,41,55,.035) !important;
      }
      [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] > details > summary p {
        color:#263142 !important;
      }
      [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] > details > summary [data-testid="stExpanderToggleIcon"] {
        color:#947000 !important;
      }
      [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] > details > summary:hover {
        background:#FFF8E5 !important; border-color:#D6B84C !important;
        box-shadow:inset 3px 0 0 #B58A00,0 3px 9px rgba(31,41,55,.06) !important;
      }
      [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] > details > summary:hover p {
        color:#755800 !important;
      }
      /* Toda liga abierta conserva el dorado en modo claro; evita heredar el negro del tema oscuro. */
      [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] > details[open] > summary {
        background:linear-gradient(100deg,#FFF8E5,#FFF2C7) !important;
        border:1.5px solid #D6B84C !important;
        box-shadow:inset 3px 0 0 #B58A00,0 3px 9px rgba(181,138,0,.08) !important;
      }
      [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] > details[open] > summary p {
        color:#755800 !important;
        font-weight:800 !important;
      }
      [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] > details[open] > summary [data-testid="stExpanderToggleIcon"] {
        color:#947000 !important;
      }
      .fl-match-scoreboard {
        background:linear-gradient(145deg,#FFFFFF 0%,#F7F8FA 100%) !important;
        border:1px solid #DDE2E9 !important;
        box-shadow:0 4px 13px rgba(31,41,55,.07) !important;
      }
      .fl-match-scoreboard.is-selected {
        background:linear-gradient(145deg,#E8F2FF 0%,#DDEBFC 100%) !important;
        border:2px solid #3978C8 !important;
        box-shadow:inset 0 0 0 1px rgba(57,120,200,.08),0 5px 16px rgba(36,99,166,.12) !important;
      }
      .fl-match-scoreboard.is-selected .fl-match-minute,
      .fl-match-scoreboard.is-selected .fl-match-minute-main,
      .fl-match-scoreboard.is-selected .fl-match-clock-separator,
      .fl-match-scoreboard.is-selected .fl-match-seconds,
      .fl-match-scoreboard.is-selected .fl-match-team,
      .fl-match-scoreboard.is-selected .fl-match-goals {
        color:#174A80 !important;
        text-shadow:none !important;
      }
      .fl-match-scoreboard.is-selected .fl-match-goals {
        background:linear-gradient(145deg,#DCEBFC,#CFE1F8) !important;
      }
      .fl-match-clock {
        background:transparent !important;
        border:0 !important;
        box-shadow:none !important;
      }
      .fl-match-minute,.fl-match-minute-main { color:#806000 !important; text-shadow:none !important; }
      .fl-match-clock-separator { color:#947000 !important; }
      .fl-match-seconds { color:#755800 !important; }
      .fl-match-team { color:#263142 !important; }
      .fl-match-goals {
        color:#806000 !important;
        background:linear-gradient(145deg,#FFF1BD,#F8E8B0) !important;
        text-shadow:none !important;
      }
      .fl-match-live { color:#B42318 !important; background:#FEECEB !important; border-color:#F3B7B2 !important; }
      .fl-match-live::before { background:#DC3D35 !important; box-shadow:none !important; }
      [class*="st-key-appearance_switch"] { position:fixed !important; top:116px !important; right:12px !important; z-index:2147483002 !important; display:flex !important; justify-content:flex-end !important; width:auto !important; margin:0 !important; }
      [class*="st-key-appearance_switch"] [role="radiogroup"] {
        display:inline-flex !important; align-items:center !important; gap:3px !important; padding:3px !important;
        border:1px solid #D6B84C !important; border-radius:999px !important; background:#FFFFFF !important;
        box-shadow:0 2px 8px rgba(31,41,55,.10) !important;
      }
      [class*="st-key-appearance_switch"] [role="radio"] { padding:4px 7px !important; min-width:30px !important; justify-content:center !important; color:#596273 !important; border-radius:999px !important; font-size:1rem !important; }
      [class*="st-key-appearance_switch"] [role="radio"][aria-checked="true"] { background:#F6E6A8 !important; color:#493800 !important; }
      [class*="st-key-appearance_switch"] [data-testid="stMarkdownContainer"] p { color:#596273 !important; }
      @media(max-width:640px) {
        [class*="st-key-appearance_switch"] { top:49px !important; right:12px !important; }
        [class*="st-key-appearance_switch"] [role="radiogroup"] { gap:1px !important; padding:2px !important; }
        [class*="st-key-appearance_switch"] { transform:scale(.78) !important; transform-origin:top right !important; }
        [class*="st-key-appearance_switch"] [role="radio"] { padding:2px 4px !important; min-width:22px !important; font-size:.76rem !important; }
      }
    
      /* Componentes de Goles y Señales: adaptar lectura, historial y promedio H2H al tema claro. */
      .goal-live-summary {
        background:linear-gradient(135deg,#FFFFFF 0%,#F5F7FA 100%) !important;
        border:1px solid #D6B84C !important;
        border-left:4px solid #B58A00 !important;
        box-shadow:0 5px 16px rgba(31,41,55,.07) !important;
      }
      .goal-live-summary-title {
        color:#947000 !important;
        -webkit-text-fill-color:#947000 !important;
      }
      .goal-live-summary p {
        color:#303744 !important;
        -webkit-text-fill-color:#303744 !important;
      }

      .history-table {
        background:#FFFFFF !important;
        border:1px solid #D6B84C !important;
        box-shadow:0 5px 16px rgba(31,41,55,.06) !important;
      }
      .history-table th {
        background:#F4F0E2 !important;
        color:#785B00 !important;
        border-bottom:1px solid #D8C47E !important;
      }
      .history-table td {
        background:#FFFFFF !important;
        color:#303744 !important;
        border-top:1px solid #E7EAF0 !important;
      }
      .history-table tr:nth-child(even) td {
        background:#F6F7F9 !important;
      }

      .goal-history-wrap {
        background:#FFFFFF !important;
        border-color:#D6B84C !important;
        box-shadow:0 5px 16px rgba(31,41,55,.06) !important;
      }
      .goal-history-heading {
        background:linear-gradient(100deg,#FFF7DC,#FFFFFF) !important;
        color:#806000 !important;
        border-bottom:1px solid #E2D39E !important;
      }
      .goal-history-heading span { color:#68717F !important; }
      .goal-history-table th {
        background:#F4F0E2 !important;
        color:#785B00 !important;
        border-bottom:1px solid #D8C47E !important;
      }
      .goal-history-table td {
        background:#FFFFFF !important;
        color:#303744 !important;
        border-top:1px solid #E7EAF0 !important;
      }
      .goal-history-table tr:nth-child(even) td { background:#F6F7F9 !important; }

      .goal-average-badge {
        background:linear-gradient(135deg,#FFFFFF 0%,#F5F7FA 100%) !important;
        border:1px solid #D6B84C !important;
        border-radius:10px !important;
        box-shadow:0 4px 12px rgba(31,41,55,.07) !important;
      }
      .goal-average-badge > span:first-child {
        color:#806000 !important;
        -webkit-text-fill-color:#806000 !important;
      }
      .goal-average-badge > span:last-child {
        background:#F6E6A8 !important;
        color:#493800 !important;
        -webkit-text-fill-color:#493800 !important;
        border:1px solid #D6B84C !important;
      }


      /* Reloj del partido: insignia clara, legible y con contraste dorado. */
      .fixture-clock {
        color:#806000 !important;
        -webkit-text-fill-color:#806000 !important;
        background:#FFF7DC !important;
        border:1px solid #D6B84C !important;
        box-shadow:0 2px 7px rgba(181,138,0,.10) !important;
      }

      /* Historial de últimos partidos y tarjetas de reacción en tema claro. */
      .goal-form-card,
      .goal-form-back,
      .goal-comeback-card {
        background:linear-gradient(145deg,#FFFFFF 0%,#F5F7FA 100%) !important;
        border:1px solid #D6B84C !important;
        box-shadow:0 5px 16px rgba(31,41,55,.07) !important;
        color:#303744 !important;
      }
      /* Marcador histórico: adaptar únicamente el encabezado al tema claro. */
      .goal-stats-scoreboard {
        background:#EEF1F7 !important;
        border-bottom:1px solid #D6B84C !important;
      }
      .goal-stats-live-team { color:#263142 !important; }
      .goal-stats-scorer { color:#4B5568 !important; }
      .goal-stats-no-scorer { color:#647084 !important; }
      .goal-stats-live-score {
        background:#FFFFFF !important;
        color:#B58A00 !important;
        border-color:#C49A24 !important;
        box-shadow:0 2px 8px rgba(31,41,55,.07) !important;
      }
      .goal-form-back-title {
        color:#806000 !important;
        -webkit-text-fill-color:#806000 !important;
        border-bottom:1px solid #E7D9A8 !important;
        padding-bottom:8px !important;
      }
      .goal-form-match {
        color:#303744 !important;
        border-top:1px solid #E7EAF0 !important;
      }
      [class*="st-key-goal_form_back_"] {
        background:linear-gradient(145deg,#FFFFFF 0%,#F5F7FA 100%) !important;
        border:1px solid #D6B84C !important;
        box-shadow:0 5px 16px rgba(31,41,55,.07) !important;
        color:#303744 !important;
      }
      [class*="st-key-goal_form_back_"] [data-testid="stMarkdownContainer"] p,
      [class*="st-key-goal_form_back_"] [data-testid="stCaptionContainer"] {
        color:#586170 !important;
        -webkit-text-fill-color:#586170 !important;
      }
      [class*="st-key-goal_form_back_"] .goal-form-match {
        color:#303744 !important;
        border-top:1px solid #E7EAF0 !important;
      }
      [class*="st-key-goal_form_back_"] .goal-form-match-meta {
        color:#947000 !important;
        -webkit-text-fill-color:#947000 !important;
      }
      [class*="st-key-goal_form_back_"] .goal-form-match-teams,
      [class*="st-key-goal_form_back_"] .goal-form-match-score {
        color:#263142 !important;
        -webkit-text-fill-color:#263142 !important;
      }
      [class*="st-key-goal_form_back_"] .goal-event-timeline {
        background:linear-gradient(145deg,#FFFFFF,#F5F7FA) !important;
        border:1px solid #D6B84C !important;
      }
      [class*="st-key-goal_form_back_"] .goal-event-row {
        border-bottom-color:#E7EAF0 !important;
      }
      [class*="st-key-goal_form_back_"] .goal-event-info strong {
        color:#263142 !important;
        -webkit-text-fill-color:#263142 !important;
      }
      [class*="st-key-goal_form_back_"] .goal-event-info span,
      [class*="st-key-goal_form_back_"] .goal-event-info small {
        color:#586170 !important;
        -webkit-text-fill-color:#586170 !important;
      }
      [class*="st-key-goal_form_back_"] .goal-event-minute,
      [class*="st-key-goal_form_back_"] .goal-event-score {
        color:#806000 !important;
        -webkit-text-fill-color:#806000 !important;
      }
      .goal-form-match-meta {
        color:#947000 !important;
        -webkit-text-fill-color:#947000 !important;
      }
      .goal-form-match-teams,
      .goal-form-match-score {
        color:#263142 !important;
        -webkit-text-fill-color:#263142 !important;
      }
      [class*="st-key-goal_form_front_"]{border-bottom-color:rgba(181,138,0,.22)!important}
      .goal-deep-heading { color:#A87900 !important; -webkit-text-fill-color:#A87900 !important; }
      .goal-form-team-lines > div { color:#263142 !important; -webkit-text-fill-color:#263142 !important; }
      .goal-form-score-lines > div { color:#263247 !important; -webkit-text-fill-color:#263247 !important; font-weight:950 !important; }
      .goal-form-team {
        color:#263142 !important;
        -webkit-text-fill-color:#263142 !important;
      }
      .goal-form-line { color:#586170 !important; -webkit-text-fill-color:#586170 !important; }
      .goal-form-record { color:#806000 !important; -webkit-text-fill-color:#806000 !important; }
      .goal-comeback-card b {
        color:#806000 !important;
        -webkit-text-fill-color:#806000 !important;
      }
      .goal-comeback-card span {
        color:#303744 !important;
        -webkit-text-fill-color:#303744 !important;
      }
      .goal-comeback-card small {
        color:#68717F !important;
        -webkit-text-fill-color:#68717F !important;
      }


      /* Indicadores de promedio H2H y último gol en modo claro. */
      .goal-h2h-average-badge {
        display:flex !important;
        align-items:center !important;
        flex-wrap:wrap !important;
        gap:8px !important;
        margin:8px 0 16px !important;
        padding:9px 12px !important;
        width:fit-content !important;
        max-width:100% !important;
        clear:both !important;
        position:relative !important;
        border:1px solid #D6B84C !important;
        border-radius:10px !important;
        background:linear-gradient(135deg,#FFFFFF 0%,#F5F7FA 100%) !important;
        box-shadow:0 4px 12px rgba(31,41,55,.07) !important;
        color:#806000 !important;
      }
      .goal-h2h-average-badge > span:first-child {
        color:#806000 !important;
        -webkit-text-fill-color:#806000 !important;
        font-weight:850 !important;
      }
      .goal-h2h-average-badge > span:last-child {
        display:inline-flex !important;
        align-items:center !important;
        justify-content:center !important;
        padding:5px 10px !important;
        border:1px solid #D6B84C !important;
        border-radius:8px !important;
        background:#F6E6A8 !important;
        color:#493800 !important;
        -webkit-text-fill-color:#493800 !important;
        font-weight:900 !important;
      }
      .goal-last-goal {
        background:linear-gradient(135deg,#FFFFFF 0%,#FFF9E8 100%) !important;
        border:2px solid #D6B84C !important;
        border-left:2px solid #D6B84C !important;
        box-shadow:0 0 0 1px rgba(214,184,76,.16),0 4px 12px rgba(31,41,55,.07) !important;
        color:#303744 !important;
      }
      .goal-last-goal b,
      .goal-last-goal strong {
        color:#806000 !important;
        -webkit-text-fill-color:#806000 !important;
      }
      .goal-last-goal span {
        background:#F6E6A8 !important;
        border:1px solid #D6B84C !important;
        color:#493800 !important;
        -webkit-text-fill-color:#493800 !important;
        box-shadow:none !important;
      }
      .goal-last-goal { animation:none !important; }
      .goal-last-goal span {
        animation:goal-minute-alarm 1.15s ease-in-out infinite !important;
        transform-origin:center !important;
        box-shadow:0 0 0 0 rgba(181,138,0,.38) !important;
      }


      /* Tip headings stay visible in light mode; one clear title per card section. */
      .tip-section-heading {
        color:#20242C !important;
        -webkit-text-fill-color:#20242C !important;
      }
      .tip-section-heading > span:not(.tip-heading-icon):not(.tip-heading-status) {
        color:#20242C !important;
        -webkit-text-fill-color:#20242C !important;
      }
      .tip-heading-icon {
        color:#A77B00 !important;
        -webkit-text-fill-color:#A77B00 !important;
        text-shadow:none !important;
      }
      .tip-heading-status {
        color:#806000 !important;
        -webkit-text-fill-color:#806000 !important;
        background:#FFF7DC !important;
        border-color:#D6B84C !important;
      }
      .risk-heading .tip-heading-icon { color:#A77B00 !important; }

      /* Cabecera azul suave para la tabla de promedio de goles en modo claro. */
      .goal-history-table th {
        background:linear-gradient(135deg,#E5EEF8 0%,#DCE8F5 100%) !important;
        color:#24476B !important;
        border-bottom:1px solid #B8CDE3 !important;
      }

      html body .stApp .goal-match-stats-table{background:linear-gradient(155deg,#FFFFFF 0%,#F4F6FA 100%)!important;border:1px solid #D8DEE8!important;border-top:2px solid #B58A00!important;box-shadow:0 5px 15px rgba(31,45,61,.07)!important}
      html body .stApp .goal-match-stats-table thead th{background:linear-gradient(180deg,#E9EEF5,#DFE6EF)!important;color:#765900!important;border-bottom-color:#CDD5E0!important}
      html body .stApp .goal-match-stats-table tbody th,html body .stApp .goal-match-stats-table tbody td{border-bottom-color:#E4E8EF!important}
      html body .stApp .goal-match-stats-table tbody tr:nth-child(even){background:#F0F3F8!important}
      html body .stApp .goal-match-stats-table tbody th{color:#536071!important}
      html body .stApp .goal-match-stats-table tbody td{color:#202B3A!important}
      html body .stApp .goal-match-goals{background:#F8F5E9!important;border-color:#E8DDB5!important;color:#394354!important}
      html body .stApp .goal-match-goals b{color:#806000!important}
      .goals-section-title {
        color:#263449 !important;
        -webkit-text-fill-color:#263449 !important;
        border:0 !important;
        border-bottom:0 !important;
        box-shadow:none !important;
        text-shadow:none !important;
        font-weight:800 !important;
      }
      /* LIVE TRACKER: adaptar exclusivamente su tarjeta al tema claro. */
      html body .stApp .fl-tracker-wrap {
        background:linear-gradient(145deg,#FFFFFF 0%,#F3F6FA 100%) !important;
        border:1px solid #D8C27A !important;
        color:#303744 !important;
        box-shadow:0 8px 24px rgba(31,41,55,.09),inset 0 1px 0 rgba(255,255,255,.95) !important;
      }
      html body .stApp .fl-tracker-kicker { color:#987300 !important; }
      html body .stApp .fl-tracker-title,
      html body .stApp .fl-tracker-score-mid b,
      html body .stApp .fl-tracker-possession b,
      html body .stApp .fl-tracker-metrics b { color:#987300 !important; }
      html body .stApp .fl-tracker-subtitle,
      html body .stApp .fl-tracker-team small,
      html body .stApp .fl-tracker-score-mid small,
      html body .stApp .fl-tracker-disclaimer { color:#68717F !important; }
      html body .stApp .fl-tracker-team,
      html body .stApp .fl-tracker-possession>div:not(.fl-tracker-possession-track) { color:#394354 !important; }
      html body .stApp .fl-tracker-scorer { color:#586170 !important; }
      html body .stApp .fl-tracker-scorer b { color:#987300 !important; }
      html body .stApp .fl-tracker-score { border-color:#DDE2E9 !important; }
      html body .stApp .fl-tracker-live {
        color:#B42332 !important; background:#FFF0F1 !important; border-color:#E8B8BE !important;
      }
      html body .stApp .fl-tracker-pitch-card {
        background:linear-gradient(145deg,#FFFFFF 0%,#F2F7F3 100%) !important;
        border-color:#D5DFD8 !important;
      }
      html body .stApp .fl-tracker-pitch-label,
      html body .stApp .fl-tracker-pitch-legend { color:#806000 !important; }
      html body .stApp .fl-tracker-metrics>div {
        background:linear-gradient(145deg,#FFFFFF 0%,#F5F7FA 100%) !important;
        border-color:#DDE2E9 !important;
      }
      html body .stApp .fl-tracker-metrics small { color:#68717F !important; }
      html body .stApp .fl-tracker-metrics span { color:#586170 !important; }
      html body .stApp .fl-tracker-status {
        background:#FFF7DC !important; color:#705400 !important; border:1px solid #E5D18A !important;
      }
      html body .stApp .fl-tracker-status-dot { box-shadow:0 0 8px #D6A91A !important; }
      /* Proyección de tarjetas: paleta clara ligada al selector de apariencia de Football Lab. */
      html body .stApp .fl-yellow-analysis { background:linear-gradient(145deg,#FFFFFF,#F3F6FA) !important; color:#303744 !important; border-color:#D6B64C !important; }
      html body .stApp .fl-yellow-grid article { background:#FFFFFF !important; border-color:#DDE2E9 !important; }
      html body .stApp .fl-yellow-grid small, html body .stApp .fl-yellow-grid span,
      html body .stApp .fl-yellow-analysis p { color:#68717F !important; }
      html body .stApp .fl-yellow-grid b, html body .stApp .fl-yellow-estimate strong,
      html body .stApp .fl-yellow-analysis header, html body .stApp .fl-yellow-analysis header strong { color:#293448 !important; }
      html body .stApp .fl-yellow-estimate { background:linear-gradient(135deg,#FFF3C4,#FFF9E8) !important; border:2px solid #D4A91F !important; box-shadow:0 0 0 1px rgba(212,169,31,.16),0 0 14px rgba(212,169,31,.14) !important; }
      html body .stApp .fl-yellow-estimate small { color:#806000 !important; }
      html body .stApp .fl-yellow-estimate b { color:#303744 !important; }
      /* Proyección de tiros: paleta clara ligada al selector de apariencia de Football Lab. */
      html body .stApp .fl-shots-analysis { background:linear-gradient(145deg,#FFFFFF,#F3F6FA) !important; color:#303744 !important; border-color:#D6B64C !important; }
      html body .stApp .fl-shots-grid article { background:#FFFFFF !important; border-color:#DDE2E9 !important; }
      html body .stApp .fl-shots-grid small, html body .stApp .fl-shots-grid span,
      html body .stApp .fl-shots-estimates span, html body .stApp .fl-shots-analysis p,
      html body .stApp .fl-shots-note { color:#68717F !important; }
      html body .stApp .fl-shots-grid b, html body .stApp .fl-shots-grid .fl-shots-secondary,
      html body .stApp .fl-shots-analysis header,
      html body .stApp .fl-shots-analysis header strong {
        color:#293448 !important; font-family:inherit !important;
        font-size:clamp(1.15rem,2.1vw,1.45rem) !important;
        font-weight:800 !important; letter-spacing:.005em !important;
        line-height:1.25 !important;
      }
      html body .stApp .fl-shots-estimates article { background:linear-gradient(135deg,#FFF3C4,#FFF9E8) !important; border-color:#D4A91F !important; box-shadow:0 0 12px rgba(212,169,31,.12) !important; }
      html body .stApp .fl-shots-estimates small { color:#806000 !important; }
      html body .stApp .fl-shots-estimates strong { color:#987300 !important; }
</style>
    """, unsafe_allow_html=True)
if st.session_state.get("appearance_mode") not in {"☀️", "☀️ Claro"}:
    st.markdown("""
    <style>
      /* La ficha de forma reciente queda abierta, sin marco, igual que en modo claro. */
      .goal-form-card {
        border:0 !important;
        border-radius:0 !important;
        background:transparent !important;
        box-shadow:none !important;
      }
      /* Selector compacto para el tema oscuro original. */
      [class*="st-key-appearance_switch"] { position:fixed !important; top:116px !important; right:12px !important; z-index:2147483002 !important; display:flex !important; justify-content:flex-end !important; width:auto !important; margin:0 !important; }
      [class*="st-key-appearance_switch"] [role="radiogroup"] {
        display:inline-flex !important; align-items:center !important; gap:3px !important; padding:3px !important;
        border:1px solid #66551F !important; border-radius:999px !important; background:#15191F !important;
        box-shadow:0 2px 8px rgba(0,0,0,.22) !important;
      }
      [class*="st-key-appearance_switch"] [role="radio"] { padding:4px 7px !important; min-width:30px !important; justify-content:center !important; color:#B9BEC8 !important; border-radius:999px !important; font-size:1rem !important; }
      [class*="st-key-appearance_switch"] [role="radio"][aria-checked="true"] { background:#3B3216 !important; color:#FFE477 !important; }
      [class*="st-key-appearance_switch"] [data-testid="stMarkdownContainer"] p { color:#B9BEC8 !important; }
      @media(max-width:640px) {
        [class*="st-key-appearance_switch"] { top:49px !important; right:12px !important; }
        [class*="st-key-appearance_switch"] [role="radiogroup"] { gap:1px !important; padding:2px !important; }
        [class*="st-key-appearance_switch"] { transform:scale(.78) !important; transform-origin:top right !important; }
        [class*="st-key-appearance_switch"] [role="radio"] { padding:2px 4px !important; min-width:22px !important; font-size:.76rem !important; }
      }
      /* Indicador promedio H2H: tarjeta compacta también en modo oscuro. */
      .goal-h2h-average-badge {
        display:flex !important;
        align-items:center !important;
        flex-wrap:wrap !important;
        gap:8px !important;
        margin:8px 0 16px !important;
        padding:9px 12px !important;
        width:fit-content !important;
        max-width:100% !important;
        clear:both !important;
        position:relative !important;
        border:1px solid #66551F !important;
        border-radius:10px !important;
        background:linear-gradient(135deg,#171A20 0%,#101216 100%) !important;
        box-shadow:0 4px 14px rgba(0,0,0,.22) !important;
        color:#FACC15 !important;
      }
      .goal-h2h-average-badge > span:first-child {
        color:#FACC15 !important;
        -webkit-text-fill-color:#FACC15 !important;
        font-weight:850 !important;
      }
      .goal-h2h-average-badge > span:last-child {
        display:inline-flex !important;
        align-items:center !important;
        justify-content:center !important;
        padding:5px 10px !important;
        border:1px solid #E6BD24 !important;
        border-radius:8px !important;
        background:#FACC15 !important;
        color:#171717 !important;
        -webkit-text-fill-color:#171717 !important;
        font-weight:900 !important;
      }
    </style>
    """, unsafe_allow_html=True)


# La hora se calcula en el navegador para respetar la zona horaria local de cada dispositivo.
st.components.v1.html("""
<script>
(function () {
  const months = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  function localStamp() {
    const now = new Date();
    const pad = n => String(n).padStart(2, "0");
    return pad(now.getDate()) + " " + months[now.getMonth()] + " " + now.getFullYear()
      + " · " + pad(now.getHours()) + ":" + pad(now.getMinutes()) + ":" + pad(now.getSeconds());
  }
  function applyLocalTime() {
    try {
      const target = window.parent.document.getElementById("update-toast-time");
      if (target) target.textContent = localStamp();
    } catch (e) {}
  }

  // Reloj visual del partido: cuenta segundos localmente entre actualizaciones de la API.
  // No realiza peticiones adicionales y se resincroniza cuando Streamlit vuelve a renderizar el marcador.
  function tickMatchClocks() {
    try {
      const doc = window.parent.document;
      doc.querySelectorAll(".fl-match-minute[data-base-minute]").forEach(el => {
        const baseMinute = Number(el.dataset.baseMinute);
        if (!Number.isFinite(baseMinute)) return;
        if (!el.dataset.clockStartedAt) el.dataset.clockStartedAt = String(Date.now());
        const elapsedSeconds = Math.max(0, Math.floor((Date.now() - Number(el.dataset.clockStartedAt)) / 1000));
        const minute = baseMinute + Math.floor(elapsedSeconds / 60);
        const second = elapsedSeconds % 60;
        const pad = n => String(n).padStart(2, "0");
        el.innerHTML = '<span class="fl-match-minute-main">' + minute + '</span><span class="fl-match-clock-separator">:</span><span class="fl-match-seconds">' + pad(second) + '</span>';
        el.setAttribute("aria-label", minute + " minutos " + second + " segundos");
      });
    } catch (e) {}
  }
  applyLocalTime();
  tickMatchClocks();
  setInterval(() => { applyLocalTime(); tickMatchClocks(); }, 1000);
  setTimeout(() => { applyLocalTime(); tickMatchClocks(); }, 250);
})();
</script>
""", height=0, width=0, scrolling=False)
# Cabecera limpia; los detalles del modelo aparecen en Rendimiento del modelo.

MODEL_DATA = load_league_baselines()

with st.sidebar:
    _sidebar_tool_page = st.session_state.get("main_fixture_tool") or {}
    _sidebar_tool_id = str(_sidebar_tool_page.get("fixture_id") or "")
    _sidebar_tool_market = str(_sidebar_tool_page.get("market") or "")
    _sidebar_tool_active = bool(_sidebar_tool_id and _sidebar_tool_page.get("tool"))
    _sidebar_dedicated_view = bool(_sidebar_tool_active)
    _sidebar_section_title = ({"stats": "Estadísticas", "standings": "Clasificación", "h2h": "H2H", "tracker": "Live Tracker"}.get(str(_sidebar_tool_page.get("tool") or ""), {"goals": "Goles y señales", "corners": "Córners y señales"}.get(_sidebar_tool_market, "Configuración")))
    _sidebar_section_icon = "🏆" if _sidebar_tool_page.get("tool") == "standings" else "📊" if _sidebar_tool_page.get("tool") == "stats" else "🛡" if _sidebar_tool_page.get("tool") == "h2h" else "⚽" if _sidebar_tool_page.get("tool") == "tracker" else "⚽" if _sidebar_tool_market == "goals" else "🚩" if _sidebar_tool_market == "corners" else "⚙"
    st.markdown(
        f'<div style="margin:0 0 18px 0;padding:4px 0 12px 0;border-bottom:1px solid rgba(250,204,21,.32);">'+
        f'<div style="font-size:.68rem;font-weight:850;letter-spacing:.19em;text-transform:uppercase;color:#B9A35A;margin-bottom:7px;">FOOTBALL LAB <span style="color:#FACC15;">/ ANÁLISIS</span></div>'+
        f'<div style="font-size:clamp(1.25rem,2vw,1.55rem);font-weight:900;letter-spacing:.035em;line-height:1.15;color:#FFE36A;text-shadow:0 0 18px rgba(250,204,21,.12);text-transform:uppercase;">{_sidebar_section_icon} {_sidebar_section_title}</div>'+
        f'<div style="width:46px;height:3px;border-radius:99px;background:linear-gradient(90deg,#FFE566,#A87909);margin-top:11px;box-shadow:0 0 10px rgba(250,204,21,.22);"></div></div>',
        unsafe_allow_html=True,
    )
    # El buscador se trasladó a la cabecera principal, debajo de la marca.
    if _sidebar_tool_active:
        _sidebar_selected_fixture = st.session_state.get("selected_live_fixture") or {}
        _sidebar_home = (_sidebar_selected_fixture.get("teams") or {}).get("home") or {}
        _sidebar_away = (_sidebar_selected_fixture.get("teams") or {}).get("away") or {}
        _sidebar_match_label = f'{_sidebar_home.get("name") or "Local"} vs {_sidebar_away.get("name") or "Visitante"}'
        st.caption(_sidebar_match_label)
    st.divider()
    st.markdown('<div style="font-size:.78rem;font-weight:900;letter-spacing:.16em;color:#FFE36A;margin-bottom:12px;text-transform:uppercase;">HERRAMIENTAS DEL PARTIDO</div>', unsafe_allow_html=True)
    _selected_fixture_for_menu = st.session_state.get("selected_live_fixture") or {}
    _selected_fixture_for_menu_id = str((_selected_fixture_for_menu.get("fixture") or {}).get("id") or "")
    # En las vistas dedicadas, recuperar el partido seleccionado desde el ID de navegación
    # si el objeto de selección no sobrevivió al rerun de Streamlit.
    if not _selected_fixture_for_menu_id and _sidebar_tool_id:
        for _candidate_fixture in st.session_state.get("live_fixtures", []):
            _candidate_id = str((_candidate_fixture.get("fixture") or {}).get("id") or "")
            if _candidate_id == _sidebar_tool_id:
                _selected_fixture_for_menu = _candidate_fixture
                _selected_fixture_for_menu_id = _candidate_id
                st.session_state["selected_live_fixture"] = _candidate_fixture
                st.session_state["selected_live_fixture_id"] = _candidate_id
                break
    _selected_home_for_menu = (_selected_fixture_for_menu.get("teams") or {}).get("home") or {}
    _selected_away_for_menu = (_selected_fixture_for_menu.get("teams") or {}).get("away") or {}
    if _selected_fixture_for_menu_id:
        if not _sidebar_tool_active:
            st.markdown(f'<div style="font-size:.84rem;font-weight:750;line-height:1.35;color:#E5E7EB;margin:0 0 12px 0;">{html.escape(str(_selected_home_for_menu.get("name") or "Local"))}<span style="color:#C9A93A;"> vs </span>{html.escape(str(_selected_away_for_menu.get("name") or "Visitante"))}</div>', unsafe_allow_html=True)
        _menu_tool_state = st.session_state.get("main_fixture_tool") or {}
        _menu_active_tool = _menu_tool_state.get("tool") if str(_menu_tool_state.get("fixture_id")) == _selected_fixture_for_menu_id else None
        _menu_active_market = _menu_tool_state.get("market") if str(_menu_tool_state.get("fixture_id")) == _selected_fixture_for_menu_id else None
        _menu_stats = st.button("ESTADÍSTICAS", icon=":material/query_stats:", help="Estadísticas en vivo", key=f"main_stats_{_selected_fixture_for_menu_id}", type="primary" if _menu_active_tool in {"stats", "standings"} else "secondary", use_container_width=True)
        _menu_goals = st.button("GOLES Y SEÑALES", icon=":material/sports_soccer:", help="Goles y señales", key=f"main_market_{_selected_fixture_for_menu_id}_goals", type="primary" if _menu_active_market == "goals" else "secondary", use_container_width=True)
        _menu_corners = st.button("CÓRNERS", icon=":material/flag:", help="Córners y señales", key=f"main_market_{_selected_fixture_for_menu_id}_corners", type="primary" if _menu_active_market == "corners" else "secondary", use_container_width=True)
        _menu_h2h = st.button("H2H", icon=":material/shield:", help="Historial de enfrentamientos (H2H)", key=f"main_h2h_{_selected_fixture_for_menu_id}", type="primary" if _menu_active_tool == "h2h" else "secondary", use_container_width=True)
        _menu_tracker = st.button("LIVE TRACKER", icon=":material/sports_soccer:", help="Mapa animado de dominio territorial estimado", key=f"main_tracker_{_selected_fixture_for_menu_id}", type="primary" if _menu_active_tool == "tracker" else "secondary", use_container_width=True)
        if _menu_stats:
            st.session_state["main_fixture_tool"] = {"fixture_id": _selected_fixture_for_menu_id, "tool": "stats"}
            st.rerun()
        if _menu_goals:
            st.session_state["main_fixture_tool"] = {"fixture_id": _selected_fixture_for_menu_id, "tool": "market", "market": "goals"}
            st.rerun()
        if _menu_corners:
            st.session_state["main_fixture_tool"] = {"fixture_id": _selected_fixture_for_menu_id, "tool": "market", "market": "corners"}
            st.rerun()
        if _menu_h2h:
            st.session_state["main_fixture_tool"] = {"fixture_id": _selected_fixture_for_menu_id, "tool": "h2h"}
            st.rerun()
        if _menu_tracker:
            st.session_state["main_fixture_tool"] = {"fixture_id": _selected_fixture_for_menu_id, "tool": "tracker"}
            st.rerun()
        if _sidebar_tool_active:
            st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
            if _sidebar_tool_page.get("tool") == "standings":
                if st.button("← VOLVER A ESTADÍSTICAS", key="sidebar_standings_back", use_container_width=True, help="Regresar a las estadísticas del mismo partido"):
                    st.session_state["main_fixture_tool"] = {"fixture_id": _sidebar_tool_id, "tool": "stats"}
                    st.rerun()
            else:
                if st.button("← VOLVER A PARTIDOS EN VIVO", key="sidebar_analysis_back", use_container_width=True, help="Volver a la lista de partidos"):
                    # Conservar el partido y la liga seleccionados para regresar al mismo punto.
                    st.session_state["selected_live_fixture_id"] = _sidebar_tool_id
                    st.session_state["return_to_fixture_id"] = _sidebar_tool_id
                    st.session_state["main_fixture_tool"] = {}
                    st.session_state["live_now_expander"] = True
                    st.rerun()
    else:
        st.caption("Haz clic en la tarjeta de un partido para seleccionar el encuentro y habilitar estas herramientas.")

    with st.expander("DIAGNÓSTICO DE CONEXIÓN", expanded=False):
        st.caption("Diagnóstico de Supabase y Telegram. El botón de prueba de Telegram sí envía un mensaje técnico al canal.")
        if st.button("VERIFICAR SUPABASE", key="verify_supabase_connection", use_container_width=True):
            try:
                _supabase_url_check = str(st.secrets.get("SUPABASE_URL", "") or os.getenv("SUPABASE_URL", "")).strip()
                _supabase_key_check = str(st.secrets.get("SUPABASE_SECRET_KEY", "") or os.getenv("SUPABASE_SECRET_KEY", "")).strip()
            except Exception:
                _supabase_url_check = str(os.getenv("SUPABASE_URL", "")).strip()
                _supabase_key_check = str(os.getenv("SUPABASE_SECRET_KEY", "")).strip()
            _supabase_ok, _supabase_message = check_supabase_connection(_supabase_url_check, _supabase_key_check)
            if _supabase_ok:
                st.success(_supabase_message)
            else:
                st.error(_supabase_message)

        if st.button("PROBAR PROTECCIÓN CONTRA DUPLICADOS", key="test_supabase_dedup", use_container_width=True):
            try:
                _supabase_url_test = str(st.secrets.get("SUPABASE_URL", "") or os.getenv("SUPABASE_URL", "")).strip()
                _supabase_key_test = str(st.secrets.get("SUPABASE_SECRET_KEY", "") or os.getenv("SUPABASE_SECRET_KEY", "")).strip()
            except Exception:
                _supabase_url_test = str(os.getenv("SUPABASE_URL", "")).strip()
                _supabase_key_test = str(os.getenv("SUPABASE_SECRET_KEY", "")).strip()
            _test_ok, _test_message = test_supabase_duplicate_protection(_supabase_url_test, _supabase_key_test)
            if _test_ok:
                st.success(_test_message)
            else:
                st.error(_test_message)

        st.divider()
        st.caption("Esta prueba envía un mensaje técnico al canal. No crea señales ni registros en Supabase.")
        if st.button("ENVIAR MENSAJE DE PRUEBA A TELEGRAM", key="test_telegram_delivery", use_container_width=True):
            try:
                _telegram_test_token = str(st.secrets.get("TELEGRAM_BOT_TOKEN", "") or os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
                _telegram_test_chat = str(st.secrets.get("TELEGRAM_CHAT_ID", "") or os.getenv("TELEGRAM_CHAT_ID", "")).strip()
            except Exception:
                _telegram_test_token = str(os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
                _telegram_test_chat = str(os.getenv("TELEGRAM_CHAT_ID", "")).strip()
            _telegram_test_ok, _telegram_test_message = send_telegram_test_message(
                _telegram_test_token, _telegram_test_chat
            )
            if _telegram_test_ok:
                st.success(_telegram_test_message)
            else:
                st.error(_telegram_test_message)

        st.divider()
        st.markdown("**ENVÍO AUTOMÁTICO Y CONTROL DE SEÑALES**")
        st.caption("Las señales nuevas que superan los filtros se reservan en Supabase y se envían automáticamente a Telegram durante el escaneo. Esta cola queda como respaldo para revisar o reenviar casos pendientes.")
        _telegram_queue = st.session_state.get("telegram_pending_rows", [])
        if _telegram_queue:
            _telegram_options = list(range(len(_telegram_queue)))
            def _telegram_signal_label(_idx):
                _row = _telegram_queue[_idx]
                _match = f"{_row.get('home') or 'Local'} vs {_row.get('away') or 'Visitante'}"
                _market = str(_row.get("market") or "Mercado")
                _minute = _row.get("minute")
                _score = f"{_row.get('score_home', '?')}-{_row.get('score_away', '?')}"
                _odd = _row.get("verified_live_odd")
                _edge = _row.get("estimated_edge")
                return f"{_match} · {_market} · {_minute or '?'}' · {_score} · cuota {_odd:.2f} · edge {_edge:.1%}"
            _telegram_selected_idx = st.selectbox(
                "Selecciona una señal para revisar",
                options=_telegram_options,
                format_func=_telegram_signal_label,
                key="telegram_manual_signal_selection",
            )
            _telegram_selected_row = _telegram_queue[_telegram_selected_idx]
            _telegram_detail_cols = st.columns(2)
            with _telegram_detail_cols[0]:
                st.metric("Cuota verificada", f"{float(_telegram_selected_row.get('verified_live_odd', 0)):.2f}")
            with _telegram_detail_cols[1]:
                st.metric("Ventaja estimada", f"{float(_telegram_selected_row.get('estimated_edge', 0)):.1%}")
            st.caption(
                f"Casa: {_telegram_selected_row.get('verified_bookmaker')} · "
                f"Mercado de cuota: {_telegram_selected_row.get('verified_odds_market')}"
            )
            if st.button("ENVIAR ESTA SEÑAL A TELEGRAM", key="telegram_send_selected_signal", use_container_width=True, type="primary"):
                try:
                    _manual_token = str(st.secrets.get("TELEGRAM_BOT_TOKEN", "") or os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
                    _manual_chat = str(st.secrets.get("TELEGRAM_CHAT_ID", "") or os.getenv("TELEGRAM_CHAT_ID", "-1004668474905")).strip()
                    _manual_url = str(st.secrets.get("SUPABASE_URL", "") or os.getenv("SUPABASE_URL", "")).strip()
                    _manual_secret = str(st.secrets.get("SUPABASE_SECRET_KEY", "") or os.getenv("SUPABASE_SECRET_KEY", "")).strip()
                except Exception:
                    _manual_token = str(os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
                    _manual_chat = str(os.getenv("TELEGRAM_CHAT_ID", "-1004668474905")).strip()
                    _manual_url = str(os.getenv("SUPABASE_URL", "")).strip()
                    _manual_secret = str(os.getenv("SUPABASE_SECRET_KEY", "")).strip()
                if not all((_manual_token, _manual_chat, _manual_url, _manual_secret)):
                    st.error("Envío detenido: faltan credenciales de Telegram o Supabase.")
                else:
                    _reserved, _alert_key, _reserve_detail = reserve_telegram_alert(
                        _telegram_selected_row, _manual_url, _manual_secret
                    )
                    if not _reserved:
                        if _alert_key:
                            st.session_state.telegram_manual_result = ("warning", "Esta señal ya fue registrada o enviada. Supabase bloqueó el duplicado.")
                            st.session_state.telegram_pending_rows.pop(_telegram_selected_idx)
                        else:
                            st.session_state.telegram_manual_result = ("error", f"No se pudo reservar la señal en Supabase: {_reserve_detail}")
                    else:
                        _sent, _send_detail = send_telegram_signal(
                            _telegram_selected_row, _manual_token, _manual_chat
                        )
                        update_telegram_alert(
                            _alert_key, "sent" if _sent else "failed",
                            _manual_url, _manual_secret,
                            error="" if _sent else _send_detail,
                        )
                        st.session_state.telegram_pending_rows.pop(_telegram_selected_idx)
                        if _sent:
                            st.session_state.telegram_manual_result = ("success", "Señal enviada correctamente a Telegram.")
                        else:
                            st.session_state.telegram_manual_result = ("error", f"No se pudo enviar la señal: {_send_detail}")
                    if all((_manual_token, _manual_chat, _manual_url, _manual_secret)):
                        st.rerun()
        else:
            st.info("Todavía no hay señales elegibles pendientes. Primero ejecuta un escaneo en vivo; las señales que cumplan los filtros aparecerán aquí para aprobación.")

        _manual_result = st.session_state.pop("telegram_manual_result", None)
        if _manual_result:
            _manual_level, _manual_message = _manual_result
            if _manual_level == "success":
                st.success(_manual_message)
            elif _manual_level == "warning":
                st.warning(_manual_message)
            else:
                st.error(_manual_message)
        if st.session_state.get("telegram_publish_status"):
            st.caption(st.session_state.telegram_publish_status)



def get_api_key() -> str:
    try:
        secret = st.secrets.get("API_FOOTBALL_KEY", "")
    except Exception:
        secret = ""
    return str(secret or os.getenv("API_FOOTBALL_KEY", "")).strip()

def _api_cache_ttl(endpoint: str, params: dict[str, Any] | None = None) -> int:
    """TTL por endpoint: datos en vivo cortos, históricos más largos."""
    if endpoint == "fixtures" and (params or {}).get("live") == "all":
        return 25
    if endpoint == "odds/live":
        return 30
    if endpoint == "fixtures/statistics":
        fixture_id = str((params or {}).get("fixture") or "")
        live_ids = {
            str(((item.get("fixture") or {}).get("id") or ""))
            for item in st.session_state.get("live_fixtures", [])
        }
        return 45 if fixture_id in live_ids else 21600
    if endpoint == "fixtures/events":
        return 30
    if endpoint == "fixtures/lineups":
        return 1800
    if endpoint in {"fixtures/headtohead", "standings"}:
        return 21600
    return 600


def api_get(endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    key = get_api_key()
    if not key:
        raise RuntimeError(
            "Falta configurar API_FOOTBALL_KEY en Secrets. "
            "Consulta README.md para ver los pasos."
        )

    # Cache de respuestas por sesión: evita repetir llamadas iguales durante reruns,
    # cambios de pestaña y secciones que comparten las mismas estadísticas.
    normalized_params = params or {}
    cache_key = f"{endpoint}:{json.dumps(normalized_params, sort_keys=True, default=str)}"
    now_epoch = time.time()
    api_cache = st.session_state.setdefault("api_response_cache", {})
    cached = api_cache.get(cache_key)
    ttl = _api_cache_ttl(endpoint, normalized_params)
    if isinstance(cached, dict):
        cached_payload = cached.get("payload") or {}
        cached_response = cached_payload.get("response") or []
        if endpoint == "fixtures/statistics" and not cached_response:
            ttl = min(ttl, 300 if (normalized_params or {}).get("half") == "true" else 900)
        if endpoint == "fixtures/lineups" and not cached_response:
            ttl = min(ttl, 180)
        if now_epoch - float(cached.get("fetched_at", 0)) < ttl:
            return cached["payload"]

    # Si la API ha confirmado que se agotó la cuota diaria, no enviar más llamadas
    # hasta el siguiente reinicio UTC. Para un límite por minuto, esperar 60 segundos.
    blocked_until = float(st.session_state.get("api_request_block_until_epoch", 0) or 0)
    if now_epoch < blocked_until:
        reason = st.session_state.get("api_request_block_reason") or "La API está temporalmente limitada."
        raise RuntimeError(reason)

    st.session_state["api_request_count"] = st.session_state.get("api_request_count", 0) + 1
    response = requests.get(
        f"{API_BASE}/{endpoint}",
        headers={"x-apisports-key": key},
        params=normalized_params,
        timeout=TIMEOUT_SECONDS,
    )
    if response.status_code == 429:
        try:
            error_payload = response.json()
        except ValueError:
            error_payload = {}
        api_errors = error_payload.get("errors") or {}
        if isinstance(api_errors, dict):
            detail = "; ".join(f"{name}: {value}" for name, value in api_errors.items() if value)
        elif api_errors:
            detail = str(api_errors)
        else:
            detail = ""
        daily_limit = "daily request limit" in detail.lower() or "requests per day" in detail.lower()
        if daily_limit:
            utc_now = datetime.now(timezone.utc)
            next_reset = utc_now.replace(hour=0, minute=0, second=0, microsecond=0)
            if next_reset <= utc_now:
                from datetime import timedelta
                next_reset += timedelta(days=1)
            blocked_until = next_reset.timestamp()
            block_reason = (
                "API-Football confirmó que se agotó la cuota diaria. "
                "Se pausaron las nuevas consultas hasta el reinicio diario de la API."
            )
        else:
            blocked_until = now_epoch + 60
            block_reason = (
                "API-Football aplicó un límite temporal (HTTP 429). "
                "Se pausaron las nuevas consultas durante 60 segundos."
            )
        st.session_state["api_request_block_until_epoch"] = blocked_until
        st.session_state["api_request_block_reason"] = block_reason
        daily_remaining = response.headers.get("x-ratelimit-requests-remaining")
        minute_remaining = response.headers.get("X-RateLimit-Remaining")
        limit_info = []
        if daily_remaining is not None:
            limit_info.append(f"solicitudes diarias restantes: {daily_remaining}")
        if minute_remaining is not None:
            limit_info.append(f"solicitudes disponibles este minuto: {minute_remaining}")
        diagnostics = " · ".join(part for part in [detail, " | ".join(limit_info)] if part)
        suffix = f" Detalle de API-Football: {diagnostics}." if diagnostics else ""
        raise RuntimeError(f"{block_reason}{suffix}")

    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(f"API-Football reportó un error: {payload['errors']}")

    api_cache[cache_key] = {"fetched_at": now_epoch, "payload": payload}
    # Mantener el caché acotado para evitar que la sesión crezca indefinidamente.
    if len(api_cache) > 500:
        oldest_keys = sorted(api_cache, key=lambda item: api_cache[item].get("fetched_at", 0))
        for old_key in oldest_keys[:len(api_cache) - 400]:
            api_cache.pop(old_key, None)
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

def safe_stat_for_team(stats: list[dict[str, Any]], stat_name: str, team_id: int | str | None):
    """Return a statistic only from the API row whose team ID matches."""
    if team_id is None:
        return None
    for row in stats or []:
        row_team_id = (row.get("team") or {}).get("id")
        if row_team_id is not None and str(row_team_id) == str(team_id):
            for item in row.get("statistics") or []:
                if item.get("type") == stat_name:
                    return item.get("value")
            return None
    return None

def safe_corner_parts(stats: list[dict[str, Any]], team_index: int = 0):
    """Return official full-match and half corner counts across API response variants."""
    if team_index < 0 or team_index >= len(stats or []):
        return None, None, None
    row = (stats or [])[team_index] or {}
    raw = row.get("statistics") or {}
    if isinstance(raw, dict):
        full = raw.get("corner_kicks")
    else:
        full = safe_stat(stats, "Corner Kicks", team_index)
    first = (row.get("first_half") or {}).get("corner_kicks")
    second = (row.get("second_half") or {}).get("corner_kicks")
    # Some API/cache response variants nest the split under statistics.
    if isinstance(raw, dict):
        if first is None:
            first = (raw.get("first_half") or {}).get("corner_kicks")
        if second is None:
            second = (raw.get("second_half") or {}).get("corner_kicks")
    return full, first, second

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

def fixture_red_card_counts(fixture_id: int | str, home_team_id: int | str | None, away_team_id: int | str | None) -> tuple[int, int]:
    """Count official red-card events for each team in a live fixture."""
    try:
        payload = api_get("fixtures/events", {"fixture": fixture_id})
        home_red = away_red = 0
        for event in payload.get("response") or []:
            if str(event.get("type") or "").casefold() != "card":
                continue
            detail = str(event.get("detail") or "").casefold()
            if "red card" not in detail and "second yellow" not in detail:
                continue
            team_id = (event.get("team") or {}).get("id")
            if team_id is not None and home_team_id is not None and str(team_id) == str(home_team_id):
                home_red += 1
            elif team_id is not None and away_team_id is not None and str(team_id) == str(away_team_id):
                away_red += 1
        return home_red, away_red
    except Exception:
        return 0, 0


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
if "corner_snapshot" not in st.session_state:
    st.session_state.corner_snapshot = {}
if "corner_rotation_index" not in st.session_state:
    st.session_state.corner_rotation_index = 0
if "auto_scan_summary" not in st.session_state:
    st.session_state.auto_scan_summary = {}
if "last_auto_market_scan_epoch" not in st.session_state:
    st.session_state.last_auto_market_scan_epoch = 0
# Persist the audit trail on the host filesystem where supported. The path can be
# redirected with SIGNAL_HISTORY_PATH; some cloud hosts use ephemeral storage.
SIGNAL_HISTORY_PATH = Path(os.getenv("SIGNAL_HISTORY_PATH", "registro_senales_escanner.csv"))
PREDICTION_LEDGER_PATH = Path(os.getenv("PREDICTION_LEDGER_PATH", "registro_pronosticos_football_lab.sqlite3"))
if "signal_rows" not in st.session_state:
    try:
        if SIGNAL_HISTORY_PATH.exists():
            with SIGNAL_HISTORY_PATH.open("r", encoding="utf-8-sig", newline="") as history_file:
                st.session_state.signal_rows = list(csv.DictReader(history_file))
        else:
            st.session_state.signal_rows = []
    except (OSError, csv.Error, UnicodeDecodeError):
        st.session_state.signal_rows = []
if "signal_history_warning_shown" not in st.session_state:
    st.session_state.signal_history_warning_shown = False

with st.container(key="top_status_controls"):
    st.markdown("""<style>
    [class*="st-key-top_status_controls"] {
      position:relative !important; z-index:8 !important;
      display:block !important; width:100% !important;
      margin:12px 0 18px !important; padding:10px 9px 8px !important;
      border:1px solid rgba(250,204,21,.58) !important;
      border-radius:15px !important;
      background:linear-gradient(135deg,rgba(35,31,19,.98),rgba(16,18,23,.98)) !important;
      box-shadow:0 5px 18px rgba(0,0,0,.28),inset 0 1px 0 rgba(255,255,255,.04) !important;
    }
    [class*="st-key-top_status_controls"] [data-testid="stHorizontalBlock"] {
      display:grid !important; grid-template-columns:repeat(3,minmax(0,1fr)) !important;
      gap:8px !important; align-items:center !important;
    }
    [class*="st-key-top_status_controls"] [data-testid="column"] {
      min-width:0 !important; width:auto !important; flex:none !important;
    }
    [class*="st-key-auto_refresh_control_card"],
    [class*="st-key-sound_control_card"] {
      min-height:42px !important; display:flex !important; align-items:center !important;
      justify-content:center !important; padding:5px 4px !important;
      border:1px solid rgba(212,167,44,.48) !important; border-radius:10px !important;
      background:rgba(250,204,21,.055) !important;
    }
    [class*="st-key-top_status_controls"] [data-testid="stMarkdownContainer"] div {
      font-size:12px !important; font-weight:800 !important; letter-spacing:.02em !important;
    }
    [class*="st-key-top_status_controls"] [role="switch"] {
      transform:scale(1.08) !important; transform-origin:center !important;
    }
    [class*="st-key-top_status_controls"] iframe { height:38px !important; }
    @media(max-width:640px) {
      [class*="st-key-top_status_controls"] {
        /* Compensar la barra superior fija de Streamlit en Safari móvil. */
        /* El menú fijo y la tarjeta de marca ocupan la parte superior en Safari iOS.
           Reservar espacio real en el flujo para que los interruptores queden debajo. */
        margin:250px 0 26px !important;
        padding:10px 8px 9px !important;
        position:relative !important;
        z-index:2147483005 !important;
        isolation:isolate !important;
      }
      [class*="st-key-top_status_controls"] [data-testid="stHorizontalBlock"] { gap:5px !important; }
      [class*="st-key-auto_refresh_control_card"],
      [class*="st-key-sound_control_card"] { min-height:44px !important; padding:4px 2px !important; }
      [class*="st-key-top_status_controls"] [data-testid="stMarkdownContainer"] div {
        font-size:10px !important; letter-spacing:0 !important;
      }
      [class*="st-key-top_status_controls"] [role="switch"] { transform:scale(1.12) !important; }
    }
    </style>""", unsafe_allow_html=True)
    status_cols = st.columns([1, 1, 1], gap="small")
    with status_cols[0]:
        with st.container(key="auto_refresh_control_card"):
            auto_cols = st.columns([0.34, 0.66], gap="small", vertical_alignment="center")
            with auto_cols[0]:
                st.session_state.auto_refresh_enabled = st.toggle(
                    " ",
                    value=st.session_state.auto_refresh_enabled,
                    key="auto_refresh_enabled_toggle",
                    help="Actualiza los marcadores cada 60 segundos mientras esta página esté abierta."
                )
            with auto_cols[1]:
                st.markdown(
                    '<div style="height:22px;display:flex;align-items:center;justify-content:flex-start;color:#D8C27A;-webkit-text-fill-color:#D8C27A;font-family:system-ui,-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;font-size:12px;font-weight:800;line-height:1.1;letter-spacing:.01em;white-space:nowrap">⟳ Auto 60s</div>',
                    unsafe_allow_html=True,
                )
    with status_cols[1]:
        with st.container(key="sound_control_card"):
            sound_cols = st.columns([0.34, 0.66], gap="small", vertical_alignment="center")
            with sound_cols[0]:
                sound_enabled = st.toggle(
                    " ",
                    value=not st.session_state.sound_muted,
                    key="sound_enabled_toggle",
                    help="Activa o desactiva las alertas sonoras del escáner."
                )
                st.session_state.sound_muted = not sound_enabled
            with sound_cols[1]:
                st.markdown(
                    '<div style="height:22px;display:flex;align-items:center;justify-content:flex-start;color:#D8C27A;-webkit-text-fill-color:#D8C27A;font-family:system-ui,-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;font-size:12px;font-weight:800;line-height:1.1;letter-spacing:.01em;white-space:nowrap">♫ Sonido</div>',
                    unsafe_allow_html=True,
                )
    with status_cols[2]:
        st.components.v1.html("""
<style>html,body{margin:0!important;padding:0!important;width:100%!important;background:transparent!important;overflow:hidden!important;}</style>
<div style="box-sizing:border-box;display:flex;align-items:center;justify-content:center;width:100%;height:36px;min-height:36px;max-height:36px;margin:0;padding:2px 0 0;overflow:visible">
  <button id="scanner-test-sound" type="button" role="switch" aria-checked="false" title="Activar/desactivar y probar alertas sonoras" style="box-sizing:border-box;position:relative;top:0;display:flex;flex:1 1 auto;align-items:center;justify-content:center;gap:3px;width:100%;max-width:100%;height:30px;min-height:30px;max-height:30px;margin:0;padding:0;border-radius:0;border:0;background:transparent;color:#D8C27A;font:800 12px/1.1 system-ui;white-space:nowrap;cursor:pointer;align-self:center;vertical-align:middle"><span id="scanner-alert-switch" style="display:inline-block;position:relative;width:34px;height:18px;min-width:34px;max-width:34px;border-radius:10px;background:#D94A4A;flex:0 0 30px"><span id="scanner-alert-knob" style="position:absolute;left:2px;top:2px;width:14px;height:14px;max-width:14px;max-height:14px;border-radius:50%;background:#FFF;transition:left .15s"></span></span><span>Alertas</span></button>
</div>
<script>
(() => {
 const b=document.getElementById('scanner-test-sound');
 if(!b || b.dataset.bound) return;
 b.dataset.bound='1';
 let alertOn = localStorage.getItem('football-lab-alerts-enabled') === 'true';
  const track=document.getElementById('scanner-alert-switch'), knob=document.getElementById('scanner-alert-knob');
  const paint=()=>{b.setAttribute('aria-checked',String(alertOn)); track.style.background=alertOn?'#22A06B':'#D94A4A'; knob.style.left=alertOn?'18px':'2px';};
  paint();
  b.addEventListener('click', () => {
    alertOn=!alertOn;
    localStorage.setItem('football-lab-alerts-enabled',String(alertOn));
    paint();
    if(!alertOn){b.title='Alertas desactivadas';return;}
   try {
     localStorage.setItem('football-lab-audio-activated', 'true');
     const C=window.AudioContext||window.webkitAudioContext;
     if(!C) { b.title='Alertas activadas'; return; }
     const c=new C();
     const playAirportChime = () => {
       const notes=[659.25,783.99,987.77,783.99];
       const starts=[0,0.22,0.46,0.82];
       notes.forEach((freq,i)=>{
         const osc=c.createOscillator(), gain=c.createGain(), t=c.currentTime+starts[i];
         osc.type='sine'; osc.frequency.setValueAtTime(freq,t);
         gain.gain.setValueAtTime(0.0001,t);
         gain.gain.exponentialRampToValueAtTime(0.095,t+0.035);
         gain.gain.exponentialRampToValueAtTime(0.0001,t+0.30);
         osc.connect(gain); gain.connect(c.destination);
         osc.start(t); osc.stop(t+0.32);
       });
       setTimeout(()=>{try{c.close();}catch(e){}},1250);
     };
     Promise.resolve(c.resume()).then(playAirportChime);
     b.title='Alertas activadas';
   } catch(e) { b.title='Alertas activadas (audio no disponible)'; }
 });
})();
</script>
""", height=38, scrolling=False)

def update_scan_progress(value, title, detail, done=False):
    """Actualizar porcentaje real y estado visual de la barra de Football Lab."""
    value = max(0, min(100, int(value)))
    scan_progress.progress(value)
    scan_progress_label.markdown(
        f'<div class="fl-scan-progress-head"><span class="fl-scan-progress-title">{title}</span><span class="fl-scan-progress-percent">{value}%</span></div>',
        unsafe_allow_html=True,
    )
    status_class = "fl-scan-progress-caption is-done" if done else "fl-scan-progress-caption"
    dot = "✓" if done else '<span class="fl-live-dot"></span>'
    scan_progress_caption.markdown(
        f'<div class="{status_class}">{dot}<span>{detail}</span></div>',
        unsafe_allow_html=True,
    )

with st.container(key="scan_actions_row"):
    st.markdown("""<style>[class*="st-key-scan_actions_row"] { display:block !important; width:100% !important; max-width:100% !important; min-width:0 !important; box-sizing:border-box !important; } [class*="st-key-scan_actions_row"] > div, [class*="st-key-scan_actions_row"] [data-testid="stVerticalBlock"], [class*="st-key-scan_actions_row"] [data-testid="stElementContainer"] { width:100% !important; max-width:100% !important; min-width:0 !important; box-sizing:border-box !important; } [class*="st-key-scan_actions_row"] [data-testid="stHorizontalBlock"] { display:grid !important; grid-template-columns:minmax(0,1fr) !important; width:100% !important; max-width:100% !important; } [class*="st-key-scan_actions_row"] [data-testid="column"] { width:100% !important; min-width:0 !important; } [class*="st-key-scan_actions_row"] [class*="st-key-scan_cta_card"] { display:block !important; width:100% !important; max-width:560px !important; min-width:0 !important; margin:0 auto !important; box-sizing:border-box !important; } [class*="st-key-scan_actions_row"]:has([class*="st-key-scan_cta_card"]), [class*="st-key-scan_actions_row"]:has([class*="st-key-scan_cta_card"]) > div, [class*="st-key-scan_actions_row"]:has([class*="st-key-scan_cta_card"]) [data-testid="stVerticalBlock"], [class*="st-key-scan_actions_row"]:has([class*="st-key-scan_cta_card"]) [data-testid="stElementContainer"], [class*="st-key-scan_actions_row"]:has([class*="st-key-scan_cta_card"]) [data-testid="stHorizontalBlock"], [class*="st-key-scan_actions_row"]:has([class*="st-key-scan_cta_card"]) [data-testid="column"] { width:100% !important; max-width:100% !important; min-width:0 !important; flex:1 1 100% !important; box-sizing:border-box !important; } [class*="st-key-scan_actions_row"] [class*="st-key-scan_cta_card"] { justify-self:stretch !important; margin-left:0 !important; margin-right:0 !important; } [class*="st-key-scan_cta_card"] > div, [class*="st-key-scan_cta_card"] [data-testid="stVerticalBlock"], [class*="st-key-scan_cta_card"] [data-testid="stElementContainer"], [class*="st-key-scan_cta_card"] [data-testid="stButton"], [class*="st-key-scan_cta_card"] [data-testid="stButton"] > div, [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button { display:block !important; width:100% !important; max-width:100% !important; min-width:0 !important; box-sizing:border-box !important; } @media(max-width:640px) { [class*="st-key-scan_actions_row"] { padding-top:46px !important; } [class*="st-key-scan_actions_row"] [data-testid="stHorizontalBlock"] { margin-top:18px !important; } [class*="st-key-scan_actions_row"] [class*="st-key-scan_cta_card"] { display:block !important; flex:0 0 280px !important; width:280px !important; max-width:280px !important; min-width:0 !important; margin:32px auto 0 !important; justify-self:center !important; } [class*="st-key-scan_cta_card"] [data-testid="stButton"] { width:280px !important; max-width:280px !important; margin:0 auto !important; } [class*="st-key-scan_cta_card"] [data-testid="stButton"] > div { width:100% !important; max-width:100% !important; } [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button { display:block !important; width:100% !important; max-width:280px !important; min-width:0 !important; min-height:145px !important; height:145px !important; padding:12px 10px 12px 46% !important; box-sizing:border-box !important; } [class*="st-key-scan_cta_card"] [data-testid="stButton"] button::before { left:4% !important; width:38% !important; } [class*="st-key-scan_cta_card"] [data-testid="stButton"] button::after { left:23% !important; }
/* Ajuste final del CTA principal: radar y balón centrados, botón completo en escritorio y móvil. */
[class*="st-key-scan_actions_row"] [class*="st-key-scan_cta_card"] {
  display:block !important; width:100% !important; max-width:720px !important;
  min-width:0 !important; margin:0 auto !important; justify-self:center !important;
}
[class*="st-key-scan_cta_card"] [data-testid="stButton"],
[class*="st-key-scan_cta_card"] [data-testid="stButton"] > div {
  width:100% !important; max-width:100% !important; margin:0 auto !important;
}
[class*="st-key-scan_cta_card"] [data-testid="stButton"] > button {
  position:relative !important; display:block !important; flex-direction:column !important;
  align-items:center !important; justify-content:flex-start !important;
  width:100% !important; max-width:100% !important; min-width:0 !important;
  height:270px !important; min-height:270px !important; max-height:none !important;
  box-sizing:border-box !important; padding:0 18px !important;
  overflow:hidden !important; text-align:center !important;
}
/* Radar y balón comparten el centro geométrico del CTA. */
[class*="st-key-scan_cta_card"] [data-testid="stButton"] > button::before {
  left:50% !important; top:55% !important; width:132px !important; height:132px !important; max-width:42% !important;
  transform:translate(-50%,-50%) !important; transform-origin:center !important;
  animation:scanner-radar-spin 3s linear infinite !important;
}
[class*="st-key-scan_cta_card"] [data-testid="stButton"] > button::after {
  left:50% !important; top:59% !important; width:54px !important; height:54px !important;
  transform:translate(-50%,-50%) !important; transform-origin:center !important;
  animation:scanner-ball-orbit 2s ease-in-out infinite !important;
}
/* Orden visual: títulos arriba, radar al centro y lema abajo. */
[class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p {
  position:absolute !important; left:10px !important; width:calc(100% - 20px) !important;
  z-index:4 !important; text-align:center !important; margin:0 !important;
}
[class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p:first-of-type {
  top:10px !important; bottom:auto !important;
}
[class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p:nth-of-type(2) {
  top:54px !important; bottom:auto !important;
}
[class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p:nth-of-type(3) {
  top:auto !important; bottom:10px !important;
}
@media(max-width:640px) {
  [class*="st-key-scan_actions_row"] { padding-top:30px !important; }
  /* CTA móvil más compacto y separado del menú superior. */
  [class*="st-key-scan_actions_row"] [class*="st-key-scan_cta_card"] {
    display:block !important; width: min(270px, calc(100vw - 64px)) !important;
    max-width:270px !important; min-width:0 !important;
    flex:0 1 270px !important; margin:112px auto 0 !important;
    justify-self:center !important; position:relative !important;
  }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"],
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > div {
    width:100% !important; max-width:270px !important; margin:0 auto !important;
  }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button {
    display:block !important; width:100% !important; max-width:270px !important;
    height:230px !important; min-height:230px !important;
    padding:0 8px !important; margin:0 auto !important;
    position:relative !important; overflow:hidden !important;
  }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button::before {
    top:55% !important; width:112px !important; height:112px !important;
  }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button::after {
    top:55% !important; width:48px !important; height:48px !important;
  }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p:first-of-type {
    top:10px !important; bottom:auto !important; left:8px !important;
    width:calc(100% - 16px) !important; margin:0 !important;
    text-align:center !important; z-index:4 !important;
  }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p:nth-of-type(2) {
    top:48px !important; left:8px !important; bottom:auto !important;
    width:calc(100% - 16px) !important; margin:0 !important;
    text-align:center !important; z-index:4 !important;
  }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p:nth-of-type(3) {
    top:auto !important; bottom:10px !important; left:8px !important;
    width:calc(100% - 16px) !important; margin:0 !important;
    text-align:center !important; z-index:4 !important;
  }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button::before {
    width:108px !important; height:108px !important; max-width:42% !important;
    left:50% !important; top:55% !important; transform-origin:50% 50% !important;
    background-image:
      radial-gradient(circle at center,rgba(255,220,75,.98) 0 5%,#8B6500 6% 12%,transparent 13%),
      repeating-radial-gradient(circle at center,transparent 0 10px,rgba(255,211,55,.78) 11px 13px,transparent 14px 20px),
      conic-gradient(from 0deg,transparent 0 8%,rgba(255,214,65,.98) 13%,rgba(255,238,145,.12) 20%,transparent 28% 43%,rgba(255,198,35,.8) 50%,transparent 62% 100%) !important;
    animation:fl-mobile-radar-revolve 2.4s linear infinite !important;
    box-shadow:0 0 25px rgba(250,204,21,.68),inset 0 0 22px rgba(250,204,21,.4) !important;
  }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button::after {
    width:46px !important; height:46px !important; top:55% !important; left:50% !important;
    font-size:2.35rem !important; line-height:1 !important;
    animation:fl-mobile-golden-ball 1.8s linear infinite !important;
    filter:sepia(1) saturate(5.5) hue-rotate(355deg) brightness(1.12) drop-shadow(0 0 12px rgba(255,202,35,.98)) !important;
    text-shadow:0 0 12px rgba(255,213,65,.95) !important;
  }
  @keyframes fl-mobile-radar-revolve {
    0% { transform:translate(-50%,-50%) rotate(0deg); }
    100% { transform:translate(-50%,-50%) rotate(360deg); }
  }
  @keyframes fl-mobile-golden-ball {
    0% { transform:translate(-50%,-50%) rotate(0deg) scale(1); }
    50% { transform:translate(-50%,-50%) rotate(180deg) scale(1.09); }
    100% { transform:translate(-50%,-50%) rotate(360deg) scale(1); }
  }

  /* Composición final del botón: textos en zonas independientes y radar centrado. */
  /* Fondo y marco antiguos retirados: el CTA debe ser completamente transparente. */
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button {
    height:270px !important; min-height:270px !important;
    padding:0 18px !important; position:relative !important;
    overflow:hidden !important; text-align:center !important;
    background:transparent !important; background-color:transparent !important;
    background-image:none !important;
    border:0 !important; border-radius:0 !important;
    box-shadow:none !important;
  }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button [data-testid="stMarkdownContainer"] {
    position:static !important;
  }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p {
    position:absolute !important; left:12px !important;
    width:calc(100% - 24px) !important; margin:0 !important;
    padding:0 !important; text-align:center !important;
    line-height:1.2 !important; z-index:5 !important;
  }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p:first-of-type {
    top:16px !important; bottom:auto !important;
    color:#ffd84d !important; font-size:clamp(20px,3vw,34px) !important;
    font-weight:900 !important; letter-spacing:.04em !important;
  }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p:nth-of-type(2) {
    top:62px !important; bottom:auto !important;
    color:#f4d477 !important; font-size:clamp(16px,2.2vw,25px) !important;
    font-weight:750 !important;
  }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p:nth-of-type(3) {
    top:auto !important; bottom:15px !important;
    color:#fff !important; font-size:clamp(13px,1.7vw,20px) !important;
    font-weight:650 !important;
  }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button::before {
    content:"" !important; position:absolute !important;
    left:50% !important; top:57% !important;
    width:174px !important; height:174px !important; max-width:48% !important;
    transform:translate(-50%,-50%) !important; transform-origin:center !important;
    border:5px solid rgba(255,211,42,.98) !important; border-radius:50% !important;
    background:
      radial-gradient(circle at center,rgba(255,220,75,.12) 0 30%,transparent 31%),
      repeating-radial-gradient(circle at center,transparent 0 25px,rgba(255,211,55,.72) 26px 29px,transparent 30px 43px),
      conic-gradient(from 0deg,transparent 0 8%,rgba(255,214,65,.98) 13%,rgba(255,238,145,.12) 20%,transparent 28% 43%,rgba(255,198,35,.8) 50%,transparent 62% 100%) !important;
    box-shadow:0 0 24px rgba(255,204,35,.7),inset 0 0 24px rgba(255,204,35,.22) !important;
    animation:scanner-radar-spin 3s linear infinite !important;
    z-index:2 !important; pointer-events:none !important;
  }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button::after {
    content:"⚽" !important; position:absolute !important;
    left:50% !important; top:57% !important;
    width:66px !important; height:66px !important;
    display:flex !important; align-items:center !important; justify-content:center !important;
    font-size:58px !important; line-height:1 !important;
    transform:translate(-50%,-50%) !important; transform-origin:center !important;
    filter:sepia(1) saturate(6) hue-rotate(355deg) brightness(1.12) drop-shadow(0 0 14px rgba(255,202,35,.98)) !important;
    text-shadow:0 0 16px rgba(255,213,65,.98) !important;
    animation:football-lab-ball-spin 1.8s linear infinite !important;
    z-index:3 !important; pointer-events:none !important;
  }
  @keyframes football-lab-ball-spin {
    0% { transform:translate(-50%,-50%) rotate(0deg) scale(1); }
    50% { transform:translate(-50%,-50%) rotate(180deg) scale(1.08); }
    100% { transform:translate(-50%,-50%) rotate(360deg) scale(1); }
  }
  @media(max-width:640px) {
    [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button {
      height:250px !important; min-height:250px !important;
      border-radius:28px !important; padding:0 8px !important;
    }
    [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p:first-of-type {
      top:14px !important; left:8px !important;
      width:calc(100% - 16px) !important; font-size:21px !important;
    }
    [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p:nth-of-type(2) {
      top:49px !important; left:8px !important;
      width:calc(100% - 16px) !important; font-size:16px !important;
    }
    [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p:nth-of-type(3) {
      bottom:13px !important; left:8px !important;
      width:calc(100% - 16px) !important; font-size:13px !important;
    }
    [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button::before {
      top:57% !important; width:136px !important; height:136px !important;
      max-width:55% !important; border-width:4px !important;
      animation:fl-mobile-radar-revolve 2.4s linear infinite !important;
    }
    [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button::after {
      top:57% !important; width:54px !important; height:54px !important;
      font-size:48px !important;
      animation:fl-mobile-golden-ball 1.8s linear infinite !important;
    }
  }
}""", unsafe_allow_html=True)
    # Override único del CTA: elimina los estilos heredados que desplazaban el radar y mezclaban los textos.
    st.markdown("""<style>
    /* Mayor especificidad que los estilos de tema claro de Streamlit. */
    html body .stApp [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button[kind="secondary"],
    html body .stApp [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button[kind="secondary"]:hover,
    html body .stApp [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button[kind="secondary"]:active,
    html body .stApp [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button[kind="secondary"]:focus,
    html body .stApp [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button[kind="secondary"]:focus-visible {
      background:transparent !important;
      background-color:transparent !important;
      background-image:none !important;
      border:0 !important;
      border-color:transparent !important;
      box-shadow:none !important;
      outline:0 !important;
      -webkit-tap-highlight-color:transparent !important;
    }
    [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button {
      --fl-cta-speed:4s;
      position:relative !important; display:block !important; width:100% !important;
      max-width:720px !important; height:184px !important; min-height:184px !important;
      margin:0 auto !important; padding:0 14px !important; box-sizing:border-box !important;
      overflow:visible !important; border:0 !important; border-radius:0 !important;
      background:transparent !important;
      color:#FFE17A !important; box-shadow:none !important;
      text-align:center !important;
    }
    /* Jerarquía del texto a la derecha: título dorado, descripción blanca y mercados discretos. */
    [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p {
      position:absolute !important; left:54% !important; width:43% !important;
      margin:0 !important; padding:0 !important; transform:none !important;
      text-align:left !important; z-index:5 !important;
    }
    [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p:first-of-type {
      top:31px !important; color:#FFD84D !important; font-size:clamp(17px,2.6vw,23px) !important;
      line-height:1.2 !important; font-weight:950 !important; letter-spacing:.045em !important;
    }
    [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p:nth-of-type(2) {
      top:72px !important; color:#FFFFFF !important; -webkit-text-fill-color:#FFFFFF !important;
      font-size:clamp(13px,1.8vw,16px) !important; line-height:1.3 !important; font-weight:600 !important;
    }
    [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p:nth-of-type(3) {
      top:108px !important; color:#D5D7DC !important; -webkit-text-fill-color:#D5D7DC !important;
      font-size:clamp(10px,1.35vw,12px) !important; line-height:1.3 !important; font-weight:450 !important;
      letter-spacing:.01em !important;
    }
    [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button::before {
      content:"" !important; position:absolute !important; left:13% !important; top:50% !important;
      width:150px !important; height:150px !important; max-width:58% !important;
      box-sizing:border-box !important; border:4px solid #F5C928 !important; border-radius:50% !important;
      background:
        radial-gradient(circle,transparent 0 34%,rgba(255,214,60,.12) 35% 37%,transparent 38%),
        repeating-radial-gradient(circle,transparent 0 16px,rgba(255,218,75,.78) 17px 19px,transparent 20px 29px),
        radial-gradient(circle,transparent 0 31%,rgba(255,218,75,.72) 32% 34%,transparent 35% 48%,rgba(255,218,75,.62) 49% 51%,transparent 52% 66%,rgba(255,218,75,.55) 67% 69%,transparent 70%),
        conic-gradient(from var(--fl-cta-angle),transparent 0 8%,rgba(255,213,52,.98) 13%,rgba(255,232,130,.12) 22%,transparent 30% 48%,rgba(255,193,28,.78) 55%,transparent 68% 100%) !important;
      box-shadow:0 0 25px rgba(255,199,35,.48),inset 0 0 20px rgba(255,208,45,.20) !important;
      transform:translate(-50%,-50%) !important; transform-origin:center !important;
      animation:fl-cta-light-sweep var(--fl-cta-speed) linear infinite !important; z-index:2 !important; pointer-events:none !important;
    }
    [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button::after {
      content:"⚽" !important; position:absolute !important; left:13% !important; top:50% !important;
      width:48px !important; height:48px !important; display:flex !important;
      align-items:center !important; justify-content:center !important; font-size:42px !important;
      transform:none !important; translate:-50% -50% !important; rotate:0deg; transform-origin:center !important;
      filter:sepia(1) saturate(6) hue-rotate(355deg) brightness(1.12) drop-shadow(0 0 13px rgba(255,195,20,.95)) !important;
      animation:fl-cta-ball var(--fl-cta-speed) linear infinite !important; z-index:3 !important; pointer-events:none !important;
    }
    /* El aro y los círculos quedan inmóviles; solo cambia el ángulo del haz dorado. */
    @property --fl-cta-angle {
      syntax: "<angle>";
      inherits: false;
      initial-value: 0deg;
    }
    @keyframes fl-cta-light-sweep {
      from { --fl-cta-angle:0deg; }
      to { --fl-cta-angle:360deg; }
    }
    /* El balón gira sobre su propio eje en el centro fijo del espiral; no describe una órbita. */
    @keyframes fl-cta-ball {
      from { rotate:0deg; }
      to   { rotate:360deg; }
    }
    @media(max-width:640px) {
      [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button {
        width:100% !important; max-width:720px !important; height:184px !important;
        min-height:184px !important; border:0 !important; border-radius:0 !important; background:transparent !important; box-shadow:none !important;
      }
      [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p {
        left:53% !important; width:44% !important; transform:none !important;
      }
      [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p:first-of-type {
        left:54% !important; width:45% !important;
        top:36px !important; font-size:clamp(15px,4vw,18px) !important;
        white-space:nowrap !important;
      }
      [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p:nth-of-type(2) {
        left:54% !important; width:45% !important;
        top:76px !important; font-size:clamp(11px,3.1vw,13px) !important;
        white-space:nowrap !important;
      }
      [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button p:nth-of-type(3) {
        left:58% !important; width:42% !important;
        top:64px !important; bottom:auto !important;
        font-size:clamp(9px,2.5vw,10px) !important;
        white-space:nowrap !important;
      }
      [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button::before {
        left:13% !important; top:50% !important; width:140px !important; height:140px !important; max-width:58% !important;
      }
      [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button::after {
        left:13% !important; top:50% !important;
        width:44px !important; height:44px !important; font-size:39px !important;
        transform:none !important; translate:-50% -50% !important;
      }
    }
    /* Fondo realmente transparente: el CTA debe integrarse con el fondo del tema, oscuro o claro. */
    [class*="st-key-scan_cta_card"],
    [class*="st-key-scan_cta_card"] > div,
    [class*="st-key-scan_cta_card"] [data-testid="stVerticalBlock"],
    [class*="st-key-scan_cta_card"] [data-testid="stElementContainer"],
    [class*="st-key-scan_cta_card"] [data-testid="stButton"],
    [class*="st-key-scan_cta_card"] [data-testid="stButton"] > div,
    [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button {
      background:transparent !important;
      background-color:transparent !important;
      box-shadow:none !important;
      outline:0 !important;
    }
    [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button {
      border:0 !important;
    }
    @media(prefers-reduced-motion:reduce) {
      [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button { --fl-cta-speed:8s; }
    }
    </style>""", unsafe_allow_html=True)
    with st.container(key="scan_cta_card"):
        manual_scan = st.button(
            "**ESCANEAR EN VIVO**\n\nActualizar y analizar partidos\n\nEstadísticas · Goles · Córners",
            type="secondary",
            key="scan_all_live",
        )
# Navegación entre partidos en vivo y programación previa.
with st.container(key="fixture_mode_switch"):
    _mode_cols = st.columns(2, gap="small")
    with _mode_cols[0]:
        _live_mode_clicked = st.button("EN VIVO", key="fixture_mode_live", use_container_width=True, type="primary" if st.session_state.get("fixture_mode", "live") == "live" else "secondary")
    with _mode_cols[1]:
        _upcoming_mode_clicked = st.button("PRÓXIMOS PARTIDOS", key="fixture_mode_upcoming", use_container_width=True, type="primary" if st.session_state.get("fixture_mode", "live") == "upcoming" else "secondary")
    if _live_mode_clicked:
        st.session_state["fixture_mode"] = "live"
        st.session_state.pop("live_search_query", None)
        st.rerun()
    if _upcoming_mode_clicked:
        st.session_state["fixture_mode"] = "upcoming"
        st.session_state.pop("live_search_query", None)
        st.rerun()

# Cargar partidos programados de hoy/mañana en hora local colombiana.
if "upcoming_fixtures_by_date" not in st.session_state:
    st.session_state["upcoming_fixtures_by_date"] = {}
if "upcoming_fixtures_cache_epoch" not in st.session_state:
    st.session_state["upcoming_fixtures_cache_epoch"] = {}
_colombia_tz = timezone(timedelta(hours=-5))
_colombia_now = datetime.now(timezone.utc).astimezone(_colombia_tz)
_upcoming_dates = {
    "HOY": _colombia_now.strftime("%Y-%m-%d"),
    "MAÑANA": (_colombia_now + timedelta(days=1)).strftime("%Y-%m-%d"),
}
if st.session_state.get("fixture_mode", "live") == "upcoming":
    _upcoming_date_cols = st.columns(2, gap="small")
    with _upcoming_date_cols[0]:
        _today_clicked = st.button("HOY", key="upcoming_day_today", use_container_width=True, type="primary" if st.session_state.get("upcoming_day", "HOY") == "HOY" else "secondary")
    with _upcoming_date_cols[1]:
        _tomorrow_clicked = st.button("MAÑANA", key="upcoming_day_tomorrow", use_container_width=True, type="primary" if st.session_state.get("upcoming_day", "HOY") == "MAÑANA" else "secondary")
    if _today_clicked:
        st.session_state["upcoming_day"] = "HOY"
        st.rerun()
    if _tomorrow_clicked:
        st.session_state["upcoming_day"] = "MAÑANA"
        st.rerun()
    _upcoming_day = st.session_state.get("upcoming_day", "HOY")
    _upcoming_date = _upcoming_dates[_upcoming_day]
    _upcoming_cache_epoch = float(st.session_state["upcoming_fixtures_cache_epoch"].get(_upcoming_date, 0) or 0)
    if time.time() - _upcoming_cache_epoch > 600:
        try:
            _upcoming_payload = api_get("fixtures", {"date": _upcoming_date, "timezone": "America/Bogota"})
            _upcoming_rows = _upcoming_payload.get("response") or []
            st.session_state["upcoming_fixtures_by_date"][_upcoming_date] = _upcoming_rows
            st.session_state["upcoming_fixtures_cache_epoch"][_upcoming_date] = time.time()
            st.session_state["upcoming_fixtures_error"] = ""
        except Exception as _upcoming_exc:
            st.session_state["upcoming_fixtures_error"] = str(_upcoming_exc)
    _scheduled_rows = st.session_state["upcoming_fixtures_by_date"].get(_upcoming_date, [])
    _scheduled_rows = [
        _row for _row in _scheduled_rows
        if str(((_row.get("fixture") or {}).get("status") or {}).get("short") or "").upper() in {"NS", "TBD"}
    ]
    if _upcoming_day == "HOY":
        _scheduled_rows = [
            _row for _row in _scheduled_rows
            if str((_row.get("fixture") or {}).get("date") or "") >= _colombia_now.isoformat()
        ]
    _scheduled_rows.sort(key=lambda _row: str((_row.get("fixture") or {}).get("date") or ""))
    st.session_state["upcoming_fixtures"] = _scheduled_rows
else:
    st.session_state["upcoming_fixtures"] = []

# El balón ejecuta ahora la actualización general y el análisis completo en una sola secuencia.
# Se conserva el flujo existente de actualización; el botón secundario deja de ser necesario.
refresh = manual_scan

with st.container(key="scan-progress"):
    scan_progress_label = st.empty()
    scan_progress = st.empty()
    scan_progress_caption = st.empty()

if refresh:
    update_scan_progress(0, "Iniciando escáner", "Preparando conexión con partidos en vivo")

if manual_scan:
    # Mantener el balón girando mientras se ejecuta este escaneo, no solo mientras se pulsa.
    st.markdown("""
    <style>
      /* Misma velocidad para haz y balón; se conserva la animación aprobada. */
      [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button {
        --fl-cta-speed:1.05s !important;
        background:transparent !important;
        background-color:transparent !important;
        background-image:none !important;
        border:0 !important;
        box-shadow:none !important;
        outline:0 !important;
        appearance:none !important;
        -webkit-appearance:none !important;
        -webkit-tap-highlight-color:transparent !important;
      }
      /* Neutralizar cualquier superficie HTML interna que herede el fondo del botón.
         No se seleccionan ::before ni ::after: radar y balón conservan sus efectos. */
      html body .stApp [class*="st-key-scan_cta_card"],
      html body .stApp [class*="st-key-scan_cta_card"] *,
      html body .stApp [class*="st-key-scan_cta_card"] button:hover,
      html body .stApp [class*="st-key-scan_cta_card"] button:active,
      html body .stApp [class*="st-key-scan_cta_card"] button:focus,
      html body .stApp [class*="st-key-scan_cta_card"] button:focus-visible {
        background:transparent !important;
        background-color:transparent !important;
        background-image:none !important;
        box-shadow:none !important;
        border-color:transparent !important;
        outline:0 !important;
      }
      [class*="st-key-scan_cta_card"] button:active { transform:none !important; }
      [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button::before {
        box-shadow:0 0 26px rgba(250,204,21,.72),inset 0 0 22px rgba(250,204,21,.38) !important;
      }
      @keyframes scanner-ball-orbit {
        0% { transform:translate(-50%,-50%) rotate(0deg) scale(1); }
        50% { transform:translate(-50%,-50%) rotate(180deg) scale(1.08); }
        100% { transform:translate(-50%,-50%) rotate(360deg) scale(1); }
      }
    </style>
    """, unsafe_allow_html=True)
    st.markdown('<div class="scan-running-status"><span class="scan-code-icon">⟳</span><div><strong>ESCANEANDO…</strong><div class="scan-running-subtitle">Analizando partidos y mercados</div></div><span class="scan-sweep"></span></div>', unsafe_allow_html=True)

internal_scan_requested = False

@st.fragment(run_every="60s")
def _native_live_refresh_timer():
    if not st.session_state.get("auto_refresh_enabled", False):
        return
    _now = time.monotonic()
    _last = st.session_state.get("last_native_auto_refresh")
    if _last is None:
        st.session_state.last_native_auto_refresh = _now
    elif _now - _last >= 55:
        st.session_state.last_native_auto_refresh = _now
        st.rerun()

_native_live_refresh_timer()
should_refresh = refresh

if should_refresh:
    try:
        if refresh:
            update_scan_progress(12, "Conectando con partidos", "Consultando encuentros en vivo")
        data = api_get("fixtures", {"live": "all"})
        new_fixtures = data.get("response", [])
        if refresh:
            update_scan_progress(28, "Partidos detectados", f"{len(new_fixtures)} encuentros recibidos de la API")
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
                        "type": "goal",
                        "title": "⚽ ¡GOOOOL!",
                        "message": f"{home.get('name', 'Local')} {score[0]} - {score[1]} {away.get('name', 'Visitante')}"
                    })
        st.session_state.score_snapshot = current_snapshot
        st.session_state.live_fixtures = new_fixtures
        st.session_state.last_refresh = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.session_state.last_auto_refresh_error = ""

        # Consultar cuotas en bloque, de forma independiente al escaneo estadístico.
        # Una sola llamada cubre todos los fixtures disponibles; intervalo de 120 s
        # para vigilar cambios sin generar una llamada por partido.
        if refresh:
            update_scan_progress(40, "Evaluando mercados", "Actualizando cuotas disponibles")
        odds_now_epoch = int(datetime.now().timestamp())
        if odds_now_epoch - int(st.session_state.get("live_odds_last_fetch_epoch", 0)) >= 120:
            try:
                live_odds_payload = api_get("odds/live")
                st.session_state.live_odds_by_fixture = extract_live_odds(live_odds_payload)
                st.session_state.live_odds_error = ""
                st.session_state.live_odds_last_fetch = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                st.session_state.live_odds_last_fetch_epoch = odds_now_epoch
            except Exception as odds_exc:
                st.session_state.live_odds_error = str(odds_exc)
                st.session_state.setdefault("live_odds_by_fixture", {})
                # Evitar repetir la consulta fallida en cada rerun del mismo minuto.
                st.session_state.live_odds_last_fetch_epoch = odds_now_epoch

        # Consultar hasta 5 partidos por minuto para proteger la cuota de API.
        # El partido abierto por el usuario siempre ocupa el primer lugar del ciclo;
        # los demás continúan rotando para mantener cobertura del resto de encuentros.
        live_for_corners = [
            match for match in new_fixtures
            if (match.get("fixture") or {}).get("id") is not None
            and (((match.get("fixture") or {}).get("status") or {}).get("short") not in {"HT", "FT", "AET", "PEN", "NS"})
        ]
        corner_events = []
        if live_for_corners:
            batch_size = min(5, len(live_for_corners))
            selected_detail = st.session_state.get("selected_match_detail") or {}
            selected_fixture_id = str(selected_detail.get("fixture_id") or "")
            selected_match = next(
                (item for item in live_for_corners
                 if str(((item.get("fixture") or {}).get("id") or "")) == selected_fixture_id),
                None,
            )
            remaining_matches = [
                item for item in live_for_corners
                if item is not selected_match
            ]
            if remaining_matches:
                offset = st.session_state.corner_rotation_index % len(remaining_matches)
                rotated_remaining = remaining_matches[offset:] + remaining_matches[:offset]
            else:
                offset = 0
                rotated_remaining = []
            prioritized_batch = ([selected_match] if selected_match is not None else []) + rotated_remaining[:max(0, batch_size - (1 if selected_match is not None else 0))]
            for corner_idx, match in enumerate(prioritized_batch):
                if refresh:
                    update_scan_progress(45 + int(45 * ((corner_idx + 1) / max(1, batch_size))), "Analizando estadísticas", f"Revisando actividad y córners · partido {corner_idx + 1} de {batch_size}")
                fixture_data = match.get("fixture") or {}
                fixture_id = str(fixture_data.get("id"))
                try:
                    stat_payload = api_get("fixtures/statistics", {"fixture": fixture_id})
                    stat_rows = stat_payload.get("response") or []
                    # Capturar el snapshot con estadísticas ya consultadas: cero llamadas API adicionales.
                    # La captura es auxiliar y nunca debe interrumpir el escáner principal.
                    try:
                        capture_result = capture_live_corner_snapshot(
                            LIVE_CORNER_CAPTURE_DB, match, stat_rows
                        )
                        if capture_result.get("stored"):
                            st.session_state["live_corner_capture_last"] = {
                                "fixture_id": fixture_id,
                                "minute": capture_result.get("minute"),
                            }
                            st.session_state["live_corner_capture_count"] = (
                                st.session_state.get("live_corner_capture_count", 0) + 1
                            )
                    except Exception as capture_exc:
                        st.session_state["live_corner_capture_error"] = str(capture_exc)
                    # Reutilizar datos recientes en el panel del partido seleccionado.
                    st.session_state.stats_cache[fixture_id] = stat_rows
                    match_teams = match.get("teams") or {}
                    home_c = safe_stat_for_team(stat_rows, "Corner Kicks", (match_teams.get("home") or {}).get("id"))
                    away_c = safe_stat_for_team(stat_rows, "Corner Kicks", (match_teams.get("away") or {}).get("id"))
                    if home_c is None or away_c is None:
                        continue
                    now_total = home_c + away_c
                    previous_total = st.session_state.corner_snapshot.get(fixture_id)
                    st.session_state.corner_snapshot[fixture_id] = now_total
                    if previous_total is not None and now_total > previous_total:
                        teams = match.get("teams") or {}
                        corner_events.append({
                            "id": f"corner:{fixture_id}:{now_total}",
                            "type": "corner",
                            "title": "🚩 ¡NUEVO CÓRNER!",
                            "message": f"{(teams.get('home') or {}).get('name', 'Local')} vs {(teams.get('away') or {}).get('name', 'Visitante')} · total {now_total}"
                        })
                except Exception as stats_exc:
                    if "HTTP 429" in str(stats_exc):
                        st.session_state.last_auto_refresh_error = "Se alcanzó el límite de la API; se pausaron las consultas de córners en este ciclo."
                        break
            if remaining_matches:
                scanned_others = max(0, len(prioritized_batch) - (1 if selected_match is not None else 0))
                st.session_state.corner_rotation_index = (offset + scanned_others) % len(remaining_matches)

        all_events = new_events + corner_events
        seen_ids = {event.get("id") for event in st.session_state.notification_events}
        for event in all_events:
            if event["id"] not in seen_ids:
                st.session_state.notification_events.append(event)
                st.toast(f"{event['title']} · {event['message']}", icon="⚽")
        st.session_state.notification_events = st.session_state.notification_events[-5:]
        st.session_state.auto_scan_summary = {
            "live_matches": len(new_fixtures),
            "corner_stats_checked": min(5, len(live_for_corners)),
            "last_auto_scan": st.session_state.last_refresh,
        }
        if refresh:
            update_scan_progress(100, "Escaneo completado", f"Actualización finalizada · {len(new_fixtures)} partidos en vivo detectados", done=True)
    except Exception as exc:
        st.session_state.last_auto_refresh_error = str(exc)
        if refresh:
            update_scan_progress(100, "Escaneo interrumpido", "No se pudo completar la actualización; revisa el aviso de error", done=True)

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
    let browserAudioActivated = false;
    try {{ browserAudioActivated = localStorage.getItem('football-lab-audio-activated') === 'true'; }} catch (e) {{}}
    const muted = {muted_js} || !browserAudioActivated;
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
      if ("Notification" in window && Notification.permission === "default") {{
        try {{ Notification.requestPermission(); }} catch (e) {{}}
      }}
      if ("Notification" in window && Notification.permission === "granted") {{
        fresh.forEach(e => {{ try {{ new Notification(e.title, {{ body: e.message, tag: e.id }}); }} catch (err) {{}} }});
      }}
      if (!muted) {{
        try {{
          const AudioCtx = window.AudioContext || window.webkitAudioContext;
          const playCornerRadar = () => {{
            if (!AudioCtx) return;
            const ctx = new AudioCtx();
            const notes = [740, 988, 988];
            const starts = [0, 0.19, 0.43];
            const levels = [0.075, 0.085, 0.026];
            notes.forEach((freq, i) => {{
              const osc = ctx.createOscillator();
              const gain = ctx.createGain();
              const t = ctx.currentTime + starts[i];
              osc.type = 'sine';
              osc.frequency.setValueAtTime(freq, t);
              gain.gain.setValueAtTime(0.0001, t);
              gain.gain.exponentialRampToValueAtTime(levels[i], t + 0.025);
              gain.gain.exponentialRampToValueAtTime(0.0001, t + (i === 2 ? 0.22 : 0.19));
              osc.connect(gain);
              gain.connect(ctx.destination);
              osc.start(t);
              osc.stop(t + 0.24);
            }});
            Promise.resolve(ctx.resume()).catch(() => {{ try {{ ctx.close(); }} catch (e) {{}} }});
            setTimeout(() => {{ try {{ ctx.close(); }} catch (e) {{}} }}, 850);
          }};
          const playGoalChime = () => {{
            if (!AudioCtx) return;
            const ctx = new AudioCtx();
            const notes=[659.25,783.99,987.77,783.99];
            const starts=[0,0.22,0.46,0.82];
            notes.forEach((freq,i)=>{{
              const osc=ctx.createOscillator(), gain=ctx.createGain(), t=ctx.currentTime+starts[i];
              osc.type='sine'; osc.frequency.setValueAtTime(freq,t);
              gain.gain.setValueAtTime(0.0001,t);
              gain.gain.exponentialRampToValueAtTime(0.095,t+0.035);
              gain.gain.exponentialRampToValueAtTime(0.0001,t+0.30);
              osc.connect(gain); gain.connect(ctx.destination);
              osc.start(t); osc.stop(t+0.32);
            }});
            Promise.resolve(ctx.resume()).catch(()=>{{try{{ctx.close();}}catch(e){{}}}});
            setTimeout(()=>{{try{{ctx.close();}}catch(e){{}}}},1250);
          }};
          fresh.forEach(e => {{
            if (e.type === 'corner') playCornerRadar();
            else playGoalChime();
          }});          }}
        }} catch (e) {{}}
      }}
    }}
    </script>
    """,
    height=1,
    scrolling=False,
)



# Vista dedicada del análisis seleccionado: conserva el encuentro y permite regresar a la lista.
_current_tool_page = st.session_state.get("main_fixture_tool") or {}
_analysis_page_id = str(_current_tool_page.get("fixture_id") or "")
_analysis_page_tool = _current_tool_page.get("tool")
_analysis_page_active = bool(_analysis_page_id and _analysis_page_tool)
if _analysis_page_active:
    st.markdown(
        f"""
        <style>
        /* Mantener la cabecera principal visible también en cada vista de análisis. */
        section.main > div.block-container {{ padding-top: 220px !important; }}
        [data-testid="stSidebar"] > div:first-child {{ padding-top: 126px !important; }}
        @media (max-width: 640px) {{
          section.main > div.block-container {{ padding-top: 166px !important; padding-left: .65rem !important; padding-right: .65rem !important; }}
          [data-testid="stSidebar"] > div:first-child {{ padding-top: 96px !important; }}
        }}
        /* Pantalla dedicada: dejar únicamente el botón de regreso y el contenido del análisis elegido. */
        {'' if (_analysis_page_tool == "market" and str(_current_tool_page.get("market") or "") in {"goals", "corners"}) else '[class*="st-key-control_row"], [class*="st-key-scan_cta_card"],'}
        {'' if (_analysis_page_tool == "market" and str(_current_tool_page.get("market") or "") in {"goals", "corners"} and refresh) else '[class*="st-key-scan-progress"],'} .match-analysis-panel {{ display:none !important; }}
        /* En la vista individual se oculta la cabecera de "En vivo ahora" y el reloj del listado. */
        [class*="st-key-live_now_expander"] > div[data-testid="stExpander"] > details > summary,
        [class*="st-key-live_now_expander"] [data-testid="stExpander"] > details > summary,
        [class*="st-key-live_league_"] summary,
        [class*="st-key-live_match_{_analysis_page_id}"] summary {{ display:none !important; }}
        [class*="st-key-live_match_{_analysis_page_id}"] .fl-match-scoreboard {{ display:none !important; }}
        [class*="st-key-live_league_"]:not(:has([class*="st-key-live_match_{_analysis_page_id}"])) {{ display:none !important; }}
        [class*="st-key-live_league_"] [class*="st-key-live_match_"]:not([class*="st-key-live_match_{_analysis_page_id}"]) {{ display:none !important; }}
        /* La lista de ligas y su contenedor no deben añadir marco, relleno ni huecos a la vista de análisis. */
        [class*="st-key-live_now_section"] {{ margin:0 !important; padding:0 !important; }}
        [class*="st-key-live_now_expander"] {{ border:0 !important; margin:0 !important; padding:0 !important; }}
        [class*="st-key-live_league_"]:has([class*="st-key-live_match_{_analysis_page_id}"]) {{ border:0 !important; margin:0 !important; padding:0 !important; }}
        [class*="st-key-live_match_{_analysis_page_id}"] {{ display:block !important; width:100% !important; max-width:100% !important; margin:0 !important; padding:0 !important; border:0 !important; }}
        /* Quitar el marco exterior heredado de la vista de análisis; conservar los bordes de las tarjetas internas. */
        [data-testid="stVerticalBlockBorderWrapper"]:has([class*="st-key-live_match_{_analysis_page_id}"]) {{
          border:0 !important; outline:0 !important; box-shadow:none !important; background:transparent !important;
        }}
        [data-testid="stVerticalBlockBorderWrapper"]:has([class*="st-key-live_match_{_analysis_page_id}"]) > [data-testid="stVerticalBlock"] {{
          border:0 !important; outline:0 !important; box-shadow:none !important; background:transparent !important;
        }}
        /* Neutralizar también los wrappers ANCESTROS de Streamlit: el marco visible rodea al contenedor del partido desde fuera. */
        section.main > div.block-container:has([class*="st-key-live_match_{_analysis_page_id}"]),
        section.main > div.block-container:has([class*="st-key-live_match_{_analysis_page_id}"]) [data-testid="stVerticalBlockBorderWrapper"],
        section.main > div.block-container:has([class*="st-key-live_match_{_analysis_page_id}"]) [data-testid="stVerticalBlockBorderWrapper"] > [data-testid="stVerticalBlock"],
        section.main > div.block-container:has([class*="st-key-live_match_{_analysis_page_id}"]) [class*="st-key-live_match_{_analysis_page_id}"] {{
          border-left:0 !important; border-right:0 !important; border-top:0 !important;
          outline:0 !important; box-shadow:none !important;
        }}
        /* El separador superior heredado no forma parte del diseño de Goles y señales. */
        section.main > div.block-container:has([class*="st-key-live_match_{_analysis_page_id}"]) hr {{
          display:none !important; border:0 !important; height:0 !important; margin:0 !important;
        }}
        section.main > div.block-container:has([class*="st-key-live_match_{_analysis_page_id}"]) [data-testid="stVerticalBlockBorderWrapper"] {{
          border-color:transparent !important;
        }}
        /* La línea restante pertenece al contenedor de la sección "En vivo ahora", no a las tarjetas. */
        [class*="st-key-live_now_section"],
        [class*="st-key-live_now_section"] > div,
        [class*="st-key-live_now_section"] > div > [data-testid="stExpander"],
        [class*="st-key-live_now_section"] [data-testid="stVerticalBlockBorderWrapper"]:has([class*="st-key-live_match_{_analysis_page_id}"]),
        [class*="st-key-live_now_section"] [data-testid="stVerticalBlockBorderWrapper"]:has([class*="st-key-live_match_{_analysis_page_id}"]) > [data-testid="stVerticalBlock"] {{
          border:0 !important; outline:0 !important; box-shadow:none !important;
          background:transparent !important;
        }}
        [class*="st-key-live_now_section"]::before,
        [class*="st-key-live_now_section"]::after,
        [class*="st-key-live_now_section"] > div::before,
        [class*="st-key-live_now_section"] > div::after {{
          content:none !important; display:none !important; border:0 !important;
        }}
        /* La vista individual no debe heredar un marco del bloque principal de Streamlit. */
        section.main > div.block-container:has([class*="st-key-live_match_{_analysis_page_id}"]) > [data-testid="stVerticalBlock"] {{
          border:0 !important; outline:0 !important; box-shadow:none !important;
        }}
        /* FIX DEFINITIVO: la cabecera visible identifica el panel real; neutralizar solo los wrappers estructurales que la contienen. */
        section.main > div.block-container:has(.goals-section-title),
        section.main > div.block-container:has(.goals-section-title) > [data-testid="stVerticalBlock"],
        section.main > div.block-container:has(.goals-section-title) > [data-testid="stVerticalBlock"] > [data-testid="stVerticalBlockBorderWrapper"],
        section.main > div.block-container:has(.goals-section-title) > [data-testid="stVerticalBlock"] > [data-testid="stVerticalBlockBorderWrapper"] > [data-testid="stVerticalBlock"],
        [data-testid="stVerticalBlockBorderWrapper"]:has(.goals-section-title),
        [data-testid="stVerticalBlockBorderWrapper"]:has(.goals-section-title) > [data-testid="stVerticalBlock"] {{
          border:0 !important; border-left:0 !important; border-right:0 !important; border-top:0 !important;
          outline:0 !important; box-shadow:none !important; background:transparent !important;
        }}
        section.main > div.block-container:has(.goals-section-title) hr,
        section.main > div.block-container:has(.goals-section-title) > [data-testid="stVerticalBlock"] > hr {{
          display:none !important; border:0 !important; height:0 !important; margin:0 !important; padding:0 !important;
        }}
        section.main > div.block-container:has(.goals-section-title)::before,
        section.main > div.block-container:has(.goals-section-title)::after,
        section.main > div.block-container:has(.goals-section-title) > [data-testid="stVerticalBlock"]::before,
        section.main > div.block-container:has(.goals-section-title) > [data-testid="stVerticalBlock"]::after {{
          content:none !important; display:none !important; border:0 !important; box-shadow:none !important;
        }}
        /* El marco oscuro viene del expander de liga que contiene el partido seleccionado, no de las tarjetas internas. */
        [data-testid="stExpander"]:has(.goals-section-title),
        [data-testid="stExpander"]:has(.goals-section-title) > details,
        [data-testid="stExpander"]:has(.goals-section-title) > details > div,
        [data-testid="stExpander"]:has(.goals-section-title) > details > div > [data-testid="stVerticalBlock"],
        [class*="st-key-live_league_"]:has(.goals-section-title),
        [class*="st-key-live_league_"]:has(.goals-section-title) > div {{
          border:0 !important; outline:0 !important; box-shadow:none !important; background:transparent !important;
        }}
        [data-testid="stExpander"]:has(.goals-section-title)::before,
        [data-testid="stExpander"]:has(.goals-section-title)::after,
        [data-testid="stExpander"]:has(.goals-section-title) > details::before,
        [data-testid="stExpander"]:has(.goals-section-title) > details::after {{
          content:none !important; display:none !important;
        }}
        [class*="st-key-live_match_{_analysis_page_id}"] [data-testid="stExpander"] {{ border:0 !important; margin:0 !important; padding:0 !important; }}
        [class*="st-key-live_match_{_analysis_page_id}"] [data-testid="stExpander"] > details > div {{ padding:0 !important; margin:0 !important; }}
        /* Mantener visibles las cuatro herramientas durante toda la navegación del análisis. */
        [data-testid="stSidebar"] [class*="st-key-main_stats_{_analysis_page_id}"],
        [data-testid="stSidebar"] [class*="st-key-main_market_{_analysis_page_id}_goals"],
        [data-testid="stSidebar"] [class*="st-key-main_market_{_analysis_page_id}_corners"],
        [data-testid="stSidebar"] [class*="st-key-main_h2h_{_analysis_page_id}"] {{ display:block !important; visibility:visible !important; opacity:1 !important; }}
        /* El contenido del análisis debe ocupar todo el ancho y no heredar espaciados del listado. */
        [class*="st-key-live_match_{_analysis_page_id}"] [data-testid="stVerticalBlock"] {{ gap:.35rem !important; row-gap:.35rem !important; }}
        /* Acciones de análisis en una sola fila, con tarjetas compactas y legibles. */
        [class*="st-key-analysis_nav_back_row"] [data-testid="stHorizontalBlock"] {{ display:grid !important; grid-template-columns:repeat(3,minmax(0,1fr)) !important; gap:10px !important; align-items:stretch !important; }}
        [class*="st-key-analysis_nav_back_row"] [data-testid="column"] {{ width:auto !important; min-width:0 !important; max-width:100% !important; flex:none !important; }}
        [class*="st-key-analysis_nav_back_row"] [data-testid="stButton"] {{ width:100% !important; }}
        [class*="st-key-analysis_nav_back_row"] [data-testid="stButton"] > button {{ min-height:54px !important; height:auto !important; max-height:none !important; padding:11px 8px !important; justify-content:center !important; text-align:center !important; font-size:clamp(.76rem,1.5vw,.96rem) !important; white-space:normal !important; overflow-wrap:anywhere !important; }}
        @media(max-width:640px) {{
          [class*="st-key-analysis_nav_back_row"] [data-testid="stHorizontalBlock"] {{ grid-template-columns:repeat(3,minmax(0,1fr)) !important; gap:6px !important; }}
          [class*="st-key-analysis_nav_back_row"] [data-testid="stButton"] > button {{ min-height:50px !important; padding:9px 4px !important; font-size:.72rem !important; letter-spacing:-.02em !important; }}
        }}
        /* Los controles se muestran en la barra lateral; ocultar solo la fila principal, no el feedback. */
        [class*="st-key-analysis_nav_back_row"] > div > [data-testid="stHorizontalBlock"] {{ display:none !important; }}
        [data-testid="stSidebar"] [class*="st-key-sidebar_analysis_back"] [data-testid="stButton"] > button,
        [data-testid="stSidebar"] [class*="st-key-sidebar_analysis_scan"] [data-testid="stButton"] > button,
        [data-testid="stSidebar"] [class*="st-key-sidebar_analysis_refresh"] [data-testid="stButton"] > button {{
            display:flex !important; align-items:center !important; justify-content:flex-start !important; width:100% !important;
            min-height:48px !important; margin:0 0 8px 0 !important; padding:12px 14px !important; box-sizing:border-box !important;
            border:1px solid #80661B !important; border-radius:11px !important;
            background:linear-gradient(110deg,#211E14,#17191F) !important; color:#FFE36A !important; -webkit-text-fill-color:#FFE36A !important;
            font-size:.88rem !important; font-weight:800 !important; white-space:normal !important; text-align:left !important;
            box-shadow:inset 0 1px 0 rgba(255,255,255,.04),0 2px 8px rgba(0,0,0,.18) !important;
            transition:background .18s ease,border-color .18s ease,box-shadow .18s ease,transform .14s ease !important;
        }}
        [data-testid="stSidebar"] [class*="st-key-sidebar_analysis_back"] [data-testid="stButton"] > button:hover,
        [data-testid="stSidebar"] [class*="st-key-sidebar_analysis_scan"] [data-testid="stButton"] > button:hover,
        [data-testid="stSidebar"] [class*="st-key-sidebar_analysis_refresh"] [data-testid="stButton"] > button:hover {{
            border-color:#FFE566 !important; background:linear-gradient(110deg,#3A3016,#242018) !important; background-color:#242018 !important;
            color:#FFF1A8 !important; -webkit-text-fill-color:#FFF1A8 !important; box-shadow:0 0 14px rgba(250,204,21,.15) !important;
            transform:translateY(-1px) !important;
        }}
        /* Navegación horizontal en análisis; el menú lateral se conserva disponible. */
        [data-testid="stMain"] {{ margin-left:0 !important; }}
        [class*="st-key-analysis_page_nav"] {{ width:100% !important; margin:0 0 12px 0 !important; }}
        [class*="st-key-analysis_page_nav"] [data-testid="stHorizontalBlock"] {{
          display:grid !important; grid-template-columns:repeat(4,minmax(0,1fr)) !important;
          grid-auto-flow:column !important; gap:0 !important; column-gap:0 !important; width:100% !important; min-width:0 !important; margin:0 !important; padding:0 !important; box-sizing:border-box !important; align-items:stretch !important;
        }}
        [class*="st-key-analysis_page_nav"] [data-testid="column"] {{ display:block !important; min-width:0 !important; width:100% !important; max-width:100% !important; flex:none !important; padding:0 !important; margin:0 !important; box-sizing:border-box !important; }}
        [class*="st-key-analysis_page_nav"] [data-testid="column"] > div {{ width:100% !important; min-width:0 !important; margin:0 !important; }}
        [class*="st-key-topnav_stats_"] button, [class*="st-key-topnav_goals_"] button,
        [class*="st-key-topnav_corners_"] button, [class*="st-key-topnav_h2h_"] button {{
          min-height:58px !important; height:58px !important; padding:8px 5px !important;
          border:1px solid #80661B !important; border-radius:12px !important;
          background:linear-gradient(145deg,#1C1E23,#111317) !important;
          color:#E8E8E8 !important; font-size:.82rem !important; font-weight:800 !important;
          white-space:normal !important; line-height:1.2 !important;
        }}
        [class*="st-key-topnav_stats_"] button[kind="primary"],
        [class*="st-key-topnav_goals_"] button[kind="primary"],
        [class*="st-key-topnav_corners_"] button[kind="primary"],
        [class*="st-key-topnav_h2h_"] button[kind="primary"] {{
          background:linear-gradient(145deg,#3A3016,#211D11) !important;
          border:2px solid #FACC15 !important; color:#FFD52A !important;
          box-shadow:0 0 14px rgba(250,204,21,.13) !important;
        }}
        /* Botón de regreso compacto, circular y premium para la vista individual. */
        [class*="st-key-topnav_back_"] {{ margin:2px 0 10px 0 !important; width:48px !important; max-width:48px !important; }}
        [class*="st-key-topnav_back_"] [data-testid="stButton"] {{ width:48px !important; max-width:48px !important; }}
        [class*="st-key-topnav_back_"] button {{
          display:flex !important;align-items:center !important;justify-content:center !important;
          width:44px !important;min-width:44px !important;max-width:44px !important;
          height:44px !important;min-height:44px !important;max-height:44px !important;
          padding:0 !important;border:1.5px solid #C9A227 !important;border-radius:50% !important;
          background:linear-gradient(145deg,#FFF9E8,#F4E5B5) !important;
          color:#6F5410 !important;-webkit-text-fill-color:#6F5410 !important;
          font-size:25px !important;font-weight:700 !important;line-height:1 !important;
          box-shadow:0 2px 8px rgba(176,137,24,.18),inset 0 1px 0 rgba(255,255,255,.9) !important;
          transition:transform .16s ease,box-shadow .16s ease,background .16s ease !important;
        }}
        [class*="st-key-topnav_back_"] button:hover {{
          transform:translateX(-2px) !important;background:linear-gradient(145deg,#FFEFAE,#EFD77B) !important;
          border-color:#A98213 !important;box-shadow:0 3px 12px rgba(176,137,24,.28) !important;
        }}
        [class*="st-key-topnav_back_"] button:focus-visible {{
          outline:3px solid rgba(201,162,39,.28) !important;outline-offset:3px !important;
        }}
        @media(max-width:640px) {{
          [class*="st-key-analysis_page_nav"] [data-testid="stHorizontalBlock"] {{ gap:5px !important; }}
          [class*="st-key-topnav_stats_"] button, [class*="st-key-topnav_goals_"] button,
          [class*="st-key-topnav_corners_"] button, [class*="st-key-topnav_h2h_"] button {{
            min-height:54px !important; height:54px !important; padding:6px 3px !important;
            font-size:.62rem !important; letter-spacing:-.025em !important;
          }}
        }}
        /* En la vista dedicada ocultamos los controles globales para priorizar la navegación del análisis. */
        [class*="st-key-top_status_controls"] {{ display:none !important; height:0 !important; min-height:0 !important; margin:0 !important; padding:0 !important; }}
        [class*="st-key-top_status_controls"] > div {{ display:none !important; height:0 !important; margin:0 !important; padding:0 !important; }}
        /* Subir la navegación y reducir el espacio vacío superior de la sección. */
        [class*="st-key-analysis_nav_back_row"] {{ margin-top:0 !important; }}
        [class*="st-key-analysis_nav_back_row"],
        [class*="st-key-analysis_nav_scan_row"],
        [class*="st-key-analysis_nav_refresh_row"] {{ margin-bottom:7px !important; }}
        /* Navegación compacta con el mismo lenguaje visual de las tarjetas profesionales de Football Lab. */
        [class*="st-key-analysis_nav_back_row"] [data-testid="stHorizontalBlock"],
        [class*="st-key-analysis_nav_scan_row"] [data-testid="stHorizontalBlock"],
        [class*="st-key-analysis_nav_refresh_row"] [data-testid="stHorizontalBlock"] {{
            display:grid !important;grid-template-columns:92px minmax(0,1fr) !important;
            align-items:center !important;column-gap:14px !important;width:100% !important;
        }}
        [class*="st-key-analysis_nav_back_row"] [data-testid="column"],
        [class*="st-key-analysis_nav_scan_row"] [data-testid="column"],
        [class*="st-key-analysis_nav_refresh_row"] [data-testid="column"] {{
            display:block !important;width:auto !important;min-width:0 !important;max-width:100% !important;flex:none !important;
        }}
        [class*="st-key-analysis_nav_back_row"] [data-testid="column"]:first-child,
        [class*="st-key-analysis_nav_scan_row"] [data-testid="column"]:first-child,
        [class*="st-key-analysis_nav_refresh_row"] [data-testid="column"]:first-child {{
            width:92px !important;min-width:92px !important;max-width:92px !important;flex:0 0 92px !important;
            align-self:center !important;overflow:visible !important;
        }}
        [class*="st-key-analysis_nav_back_row"] [data-testid="stButton"],
        [class*="st-key-analysis_nav_scan_row"] [data-testid="stButton"],
        [class*="st-key-analysis_nav_refresh_row"] [data-testid="stButton"] {{
            display:block !important;width:100% !important;min-width:0 !important;max-width:100% !important;position:relative !important;z-index:5 !important;
        }}
        [class*="st-key-analysis_nav_back_row"] [data-testid="stButton"] > div,
        [class*="st-key-analysis_nav_scan_row"] [data-testid="stButton"] > div,
        [class*="st-key-analysis_nav_refresh_row"] [data-testid="stButton"] > div {{
            width:100% !important;min-width:0 !important;max-width:100% !important;
        }}
        [class*="st-key-analysis_nav_back_row"] [data-testid="stButton"] > button,
        [class*="st-key-analysis_nav_scan_row"] [data-testid="stButton"] > button,
        [class*="st-key-analysis_nav_refresh_row"] [data-testid="stButton"] > button {{
            display:flex !important;align-items:center !important;justify-content:center !important;
            position:relative !important;isolation:isolate !important;overflow:hidden !important;
            width:100% !important;min-width:0 !important;max-width:100% !important;height:92px !important;min-height:92px !important;max-height:92px !important;
            padding:0 !important;box-sizing:border-box !important;border:2px solid #FACC15 !important;border-radius:19px !important;
            background-color:#090A0D !important;
            background-image:radial-gradient(ellipse at 50% 50%,rgba(250,204,21,.15),transparent 68%),linear-gradient(145deg,#201D14,#111419) !important;
            color:transparent !important;-webkit-text-fill-color:transparent !important;
            box-shadow:inset 0 1px 0 rgba(255,255,255,.07),inset 0 0 15px rgba(250,204,21,.09),0 4px 14px rgba(0,0,0,.28) !important;
            transition:border-color .2s ease,background .2s ease,box-shadow .2s ease,transform .2s ease !important;
        }}
        [class*="st-key-analysis_nav_back_row"] [data-testid="stButton"] > button p,
        [class*="st-key-analysis_nav_scan_row"] [data-testid="stButton"] > button p,
        [class*="st-key-analysis_nav_refresh_row"] [data-testid="stButton"] > button p {{
            position:relative !important;z-index:3 !important;display:block !important;margin:0 !important;
            font-size:0 !important;line-height:1 !important;color:transparent !important;-webkit-text-fill-color:transparent !important;
        }}
        /* Volver: flecha compacta centrada, sin tocar los bordes. */
        [class*="st-key-analysis_nav_back_row"] [data-testid="stButton"] > button::before {{
            content:"" !important;position:absolute !important;left:50% !important;top:50% !important;
            width:30px !important;height:4px !important;border-radius:4px !important;background:#FFE978 !important;
            transform:translate(-35%,-50%) !important;box-shadow:0 0 7px rgba(250,204,21,.65) !important;
            animation:analysis-arrow-line-pulse 1.65s ease-in-out infinite !important;pointer-events:none !important;z-index:5 !important;
        }}
        [class*="st-key-analysis_nav_back_row"] [data-testid="stButton"] > button::after {{
            content:"" !important;position:absolute !important;left:calc(50% - 15px) !important;top:50% !important;
            width:12px !important;height:12px !important;box-sizing:border-box !important;
            border-left:4px solid #FFE978 !important;border-bottom:4px solid #FFE978 !important;
            transform:translateY(-50%) rotate(45deg) !important;box-shadow:-2px 2px 5px rgba(250,204,21,.2) !important;
            animation:analysis-arrow-head-pulse 1.65s ease-in-out infinite !important;pointer-events:none !important;z-index:6 !important;
        }}
        /* Escanear: radar espiral y balón animado, replicando la tarjeta principal. */
        [class*="st-key-analysis_nav_scan_row"] [data-testid="stButton"] > button::before {{
            content:"" !important;position:absolute !important;left:50% !important;top:50% !important;width:64px !important;height:64px !important;
            transform:translate(-50%,-50%) !important;border:3px solid #FACC15 !important;border-radius:50% !important;box-sizing:border-box !important;
            background-color:#090A0D !important;
            background-image:radial-gradient(circle at center,#FACC15 0 6%,#14151A 7% 14%,transparent 15%),repeating-radial-gradient(circle at center,transparent 0 8px,rgba(250,204,21,.65) 9px 11px,transparent 12px 17px),conic-gradient(from 0deg,transparent 0 12%,rgba(250,204,21,.98) 16%,transparent 28% 48%,rgba(250,204,21,.55) 55%,transparent 72%) !important;
            box-shadow:0 0 20px rgba(250,204,21,.55),inset 0 0 18px rgba(250,204,21,.28) !important;
            animation:analysis-radar-rotate 3s linear infinite !important;pointer-events:none !important;z-index:1 !important;
        }}
        [class*="st-key-analysis_nav_scan_row"] [data-testid="stButton"] > button::after {{
            content:"⚽" !important;position:absolute !important;display:flex !important;left:50% !important;top:50% !important;width:43px !important;height:43px !important;
            align-items:center !important;justify-content:center !important;transform:translate(-50%,-50%) !important;
            font-size:40px !important;line-height:1 !important;color:#FFE978 !important;-webkit-text-fill-color:#FFE978 !important;
            filter:drop-shadow(0 0 10px rgba(250,204,21,.75)) !important;animation:analysis-ball-rotate 2s ease-in-out infinite !important;
            pointer-events:none !important;z-index:2 !important;
        }}
        /* Actualizar: símbolo de recarga giratorio con halo dorado. */
        [class*="st-key-analysis_nav_refresh_row"] [data-testid="stButton"] > button::before {{
            content:"⟳" !important;position:absolute !important;display:flex !important;left:50% !important;top:50% !important;width:58px !important;height:58px !important;
            align-items:center !important;justify-content:center !important;transform:translate(-50%,-50%) !important;
            color:#FFE978 !important;-webkit-text-fill-color:#FFE978 !important;font-family:system-ui,sans-serif !important;
            font-size:62px !important;font-weight:500 !important;line-height:1 !important;text-shadow:0 0 7px rgba(250,204,21,.65),0 0 14px rgba(250,204,21,.25) !important;
            animation:analysis-refresh-spin 2.4s linear infinite !important;pointer-events:none !important;z-index:5 !important;
        }}
        [class*="st-key-analysis_nav_back_row"] [data-testid="stButton"] > button:hover,
        [class*="st-key-analysis_nav_scan_row"] [data-testid="stButton"] > button:hover,
        [class*="st-key-analysis_nav_refresh_row"] [data-testid="stButton"] > button:hover {{
            border-color:#FFF09A !important;background-image:radial-gradient(ellipse at 50% 50%,rgba(250,204,21,.27),transparent 70%),linear-gradient(145deg,#302916,#17191F) !important;
            box-shadow:inset 0 1px 0 rgba(255,255,255,.12),0 0 18px rgba(250,204,21,.24) !important;
            transform:translateY(-2px) scale(1.035) !important;z-index:10 !important;
        }}
        .analysis-nav-label {{
            display:block !important;width:100% !important;box-sizing:border-box !important;
            color:#FDE68A !important;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif !important;
            font-size:clamp(1rem,2.8vw,1.22rem) !important;font-weight:700 !important;line-height:1.25 !important;
            letter-spacing:.01em !important;padding:8px 0 !important;text-align:left !important;
        }}
        @keyframes analysis-radar-rotate {{
            from {{ transform:translate(-50%,-50%) rotate(0deg); }}
            to {{ transform:translate(-50%,-50%) rotate(360deg); }}
        }}
        @keyframes analysis-ball-rotate {{
            0% {{ transform:translate(-50%,-50%) rotate(0deg) scale(1); }}
            50% {{ transform:translate(-50%,-50%) rotate(180deg) scale(1.08); }}
            100% {{ transform:translate(-50%,-50%) rotate(360deg) scale(1); }}
        }}
        @keyframes analysis-arrow-line-pulse {{
            0%,100% {{ transform:translate(-35%,-50%) scaleX(.94);opacity:.86; }}
            50% {{ transform:translate(-35%,-50%) scaleX(1.04);opacity:1; }}
        }}
        @keyframes analysis-arrow-head-pulse {{
            0%,100% {{ transform:translateY(-50%) rotate(45deg) scale(.94);opacity:.86; }}
            50% {{ transform:translateY(-50%) rotate(45deg) scale(1.04);opacity:1; }}
        }}
        @keyframes analysis-refresh-spin {{
            from {{ transform:translate(-50%,-50%) rotate(0deg); }}
            to {{ transform:translate(-50%,-50%) rotate(360deg); }}
        }}
        @media(max-width:640px) {{
          [class*="st-key-analysis_nav_back_row"] [data-testid="stHorizontalBlock"],
          [class*="st-key-analysis_nav_scan_row"] [data-testid="stHorizontalBlock"],
          [class*="st-key-analysis_nav_refresh_row"] [data-testid="stHorizontalBlock"] {{
              grid-template-columns:88px minmax(0,1fr) !important;column-gap:12px !important;
          }}
          [class*="st-key-analysis_nav_back_row"] [data-testid="column"]:first-child,
          [class*="st-key-analysis_nav_scan_row"] [data-testid="column"]:first-child,
          [class*="st-key-analysis_nav_refresh_row"] [data-testid="column"]:first-child {{
              width:88px !important;min-width:88px !important;max-width:88px !important;flex:0 0 88px !important;
          }}
          [class*="st-key-analysis_nav_back_row"] [data-testid="stButton"] > button,
          [class*="st-key-analysis_nav_scan_row"] [data-testid="stButton"] > button,
          [class*="st-key-analysis_nav_refresh_row"] [data-testid="stButton"] > button {{
              height:86px !important;min-height:86px !important;max-height:86px !important;border-radius:17px !important;
          }}
          [class*="st-key-analysis_nav_scan_row"] [data-testid="stButton"] > button::before {{ width:57px !important;height:57px !important; }}
          [class*="st-key-analysis_nav_scan_row"] [data-testid="stButton"] > button::after {{ font-size:36px !important;width:39px !important;height:39px !important; }}
          [class*="st-key-analysis_nav_refresh_row"] [data-testid="stButton"] > button::before {{ font-size:56px !important;width:52px !important;height:52px !important; }}
          .analysis-nav-label {{ font-size:1rem !important; }}
        }}
        @media(prefers-reduced-motion:reduce) {{
          [class*="st-key-analysis_nav_back_row"] [data-testid="stButton"] > button::before,
          [class*="st-key-analysis_nav_back_row"] [data-testid="stButton"] > button::after,
          [class*="st-key-analysis_nav_scan_row"] [data-testid="stButton"] > button::before,
          [class*="st-key-analysis_nav_scan_row"] [data-testid="stButton"] > button::after,
          [class*="st-key-analysis_nav_refresh_row"] [data-testid="stButton"] > button::before {{ animation-duration:2.5s !important; }}
        }}
                /* Corrección visual de navegación: cada opción es un botón completo y legible. */
        [class*="st-key-analysis_nav_back_row"],
        [class*="st-key-analysis_nav_scan_row"],
        [class*="st-key-analysis_nav_refresh_row"] {{ width:100% !important; margin:0 0 8px 0 !important; padding:0 !important; }}
        [class*="st-key-analysis_nav_back_row"] [data-testid="stHorizontalBlock"] {{ display:grid !important; grid-template-columns:repeat(3,minmax(0,1fr)) !important; gap:10px !important; align-items:stretch !important; width:100% !important; }}
        [class*="st-key-analysis_nav_back_row"] [data-testid="column"] {{ width:auto !important; min-width:0 !important; max-width:100% !important; flex:none !important; }}
        [class*="st-key-analysis_nav_back_row"] [data-testid="stButton"] > button,
        [class*="st-key-analysis_nav_scan_row"] [data-testid="stButton"] > button,
        [class*="st-key-analysis_nav_refresh_row"] [data-testid="stButton"] > button {{
            display:flex !important; align-items:center !important; justify-content:flex-start !important; gap:12px !important;
            width:100% !important; height:auto !important; min-height:54px !important; max-height:none !important;
            box-sizing:border-box !important; padding:13px 18px !important; overflow:visible !important;
            border:1px solid #80661B !important; border-radius:13px !important;
            background:linear-gradient(110deg,#211E14 0%,#17191F 58%,#101115 100%) !important;
            background-color:#17191F !important; color:#FFE36A !important; -webkit-text-fill-color:#FFE36A !important;
            font-size:1rem !important; font-weight:800 !important; letter-spacing:.01em !important; line-height:1.25 !important;
            text-align:left !important; box-shadow:inset 0 1px 0 rgba(255,255,255,.045),0 3px 10px rgba(0,0,0,.22) !important;
            transform:none !important; transition:border-color .18s ease,background .18s ease,box-shadow .18s ease,transform .14s ease !important;
        }}
        [class*="st-key-analysis_nav_back_row"] [data-testid="stButton"] > button p,
        [class*="st-key-analysis_nav_scan_row"] [data-testid="stButton"] > button p,
        [class*="st-key-analysis_nav_refresh_row"] [data-testid="stButton"] > button p {{
            display:block !important; margin:0 !important; font-size:inherit !important; line-height:inherit !important;
            color:inherit !important; -webkit-text-fill-color:inherit !important;
        }}
        [class*="st-key-analysis_nav_back_row"] [data-testid="stButton"] > button::before,
        [class*="st-key-analysis_nav_back_row"] [data-testid="stButton"] > button::after,
        [class*="st-key-analysis_nav_scan_row"] [data-testid="stButton"] > button::before,
        [class*="st-key-analysis_nav_scan_row"] [data-testid="stButton"] > button::after,
        [class*="st-key-analysis_nav_refresh_row"] [data-testid="stButton"] > button::before,
        [class*="st-key-analysis_nav_refresh_row"] [data-testid="stButton"] > button::after {{ content:none !important; display:none !important; }}
        [class*="st-key-analysis_nav_back_row"] [data-testid="stButton"] > button:hover,
        [class*="st-key-analysis_nav_scan_row"] [data-testid="stButton"] > button:hover,
        [class*="st-key-analysis_nav_refresh_row"] [data-testid="stButton"] > button:hover {{
            border-color:#FFE566 !important; background:linear-gradient(110deg,#3A3016 0%,#242018 58%,#17191F 100%) !important;
            background-color:#242018 !important; color:#FFF1A8 !important; -webkit-text-fill-color:#FFF1A8 !important;
            box-shadow:0 0 0 1px rgba(250,204,21,.08),0 0 16px rgba(250,204,21,.16) !important; transform:translateY(-1px) !important;
        }}
        [class*="st-key-analysis_nav_back_row"] [data-testid="stButton"] > button:active,
        [class*="st-key-analysis_nav_scan_row"] [data-testid="stButton"] > button:active,
        [class*="st-key-analysis_nav_refresh_row"] [data-testid="stButton"] > button:active {{ transform:scale(.99) !important; }}
        @media(max-width:640px) {{
            [class*="st-key-analysis_nav_back_row"] [data-testid="stButton"] > button,
            [class*="st-key-analysis_nav_scan_row"] [data-testid="stButton"] > button,
            [class*="st-key-analysis_nav_refresh_row"] [data-testid="stButton"] > button {{ min-height:50px !important; padding:12px 14px !important; font-size:.94rem !important; }}
        }}

  /* Elimina adornos automáticos del navegador dentro del input de búsqueda. */
  [data-testid="stSidebar"] [class*="st-key-search_goal_matches"] input[type="text"] {{
    -webkit-appearance:none !important;
    appearance:none !important;
    background-image:none !important;
    padding-right:13px !important;
  }}
  [data-testid="stSidebar"] [class*="st-key-search_goal_matches"] input[type="text"]::-webkit-search-decoration,
  [data-testid="stSidebar"] [class*="st-key-search_goal_matches"] input[type="text"]::-webkit-search-cancel-button,
  [data-testid="stSidebar"] [class*="st-key-search_goal_matches"] input[type="text"]::-webkit-search-results-button,
  [data-testid="stSidebar"] [class*="st-key-search_goal_matches"] input[type="text"]::-webkit-search-results-decoration,
  [data-testid="stSidebar"] [class*="st-key-search_goal_matches"] input[type="text"]::-webkit-credentials-auto-fill-button,
  [data-testid="stSidebar"] [class*="st-key-search_goal_matches"] input[type="text"]::-webkit-contacts-auto-fill-button,
  [data-testid="stSidebar"] [class*="st-key-search_goal_matches"] input[type="text"]::-ms-clear,
  [data-testid="stSidebar"] [class*="st-key-search_goal_matches"] input[type="text"]::-ms-reveal {{
    display:none !important;
    -webkit-appearance:none !important;
    appearance:none !important;
    width:0 !important;
    height:0 !important;
    margin:0 !important;
    padding:0 !important;
  }}
  /* Buscador lateral integrado: campo carbón + acción dorada. */
  [data-testid="stSidebar"] [class*="st-key-search_goal_matches"] {{ margin:0 0 20px 0 !important; min-width:0 !important; }}
  [data-testid="stSidebar"] [class*="st-key-search_goal_matches"] > div {{ gap:0 !important; }}
  [data-testid="stSidebar"] [class*="st-key-search_goal_matches"] input {{ min-height:48px !important; height:48px !important; padding:0 13px !important; border:1.5px solid #C49A20 !important; border-right:0 !important; border-radius:11px 0 0 11px !important; background:linear-gradient(135deg,#202329,#111419) !important; color:#F5F5F5 !important; font-size:.82rem !important; font-weight:550 !important; box-shadow:inset 0 1px 0 rgba(255,255,255,.04),0 3px 12px rgba(0,0,0,.22) !important; transition:border-color .2s ease,box-shadow .2s ease,background .2s ease !important; }}
  [data-testid="stSidebar"] [class*="st-key-search_goal_matches"] input::placeholder {{ color:#A5AAB4 !important; opacity:1 !important; }}
  [data-testid="stSidebar"] [class*="st-key-search_goal_matches"] input:hover {{ border-color:#FFE566 !important; background:linear-gradient(135deg,#252830,#17191E) !important; }}
  [data-testid="stSidebar"] [class*="st-key-search_goal_matches"] input:focus, [data-testid="stSidebar"] [class*="st-key-search_goal_matches"] input:focus-visible {{ border-color:#FFE566 !important; box-shadow:inset 0 0 0 1px rgba(250,204,21,.18),0 0 15px rgba(250,204,21,.14) !important; background:#191B20 !important; }}
  [data-testid="stSidebar"] [class*="st-key-sidebar_search_button"] {{ margin:0 0 20px 0 !important; min-width:0 !important; }}
  [data-testid="stSidebar"] [class*="st-key-sidebar_search_button"] button {{ min-height:48px !important; height:48px !important; width:100% !important; padding:0 !important; border:1.5px solid #FACC15 !important; border-radius:0 11px 11px 0 !important; background:linear-gradient(145deg,#FFE566,#E6AD08) !important; color:#171717 !important; box-shadow:inset 0 1px 0 rgba(255,255,255,.35),0 0 13px rgba(250,204,21,.16) !important; transition:background .2s ease,box-shadow .2s ease,transform .2s ease !important; }}
  [data-testid="stSidebar"] [class*="st-key-sidebar_search_button"] button:hover {{ background:linear-gradient(145deg,#FFF0A0,#FACC15) !important; border-color:#FFF0A0 !important; box-shadow:0 0 18px rgba(250,204,21,.28) !important; transform:translateY(-1px) !important; }}
  [data-testid="stSidebar"] [class*="st-key-sidebar_search_button"] button [data-testid="stIconMaterial"] {{ color:#171717 !important; font-size:1.3rem !important; }}
  [data-testid="stSidebar"] [class*="st-key-sidebar_search_button"] button:focus, [data-testid="stSidebar"] [class*="st-key-sidebar_search_button"] button:focus-visible {{ outline:none !important; box-shadow:0 0 0 2px rgba(250,204,21,.24),0 0 18px rgba(250,204,21,.24) !important; }}

  /* En móvil, el menú lateral ocupa menos pantalla; escritorio conserva su ancho actual. */
  @media (max-width: 640px) {{
    section[data-testid="stSidebar"],
    [data-testid="stSidebar"] {{
      width: min(82vw, 320px) !important;
      min-width: min(82vw, 320px) !important;
      max-width: min(82vw, 320px) !important;
    }}
    [data-testid="stSidebar"] > div:first-child {{
      width: 100% !important;
      min-width: 0 !important;
      max-width: 100% !important;
      box-sizing: border-box !important;
    }}
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"],
    [data-testid="stSidebar"] [data-testid="stElementContainer"] {{
      min-width: 0 !important;
      max-width: 100% !important;
    }}
    [data-testid="stSidebar"] .brand-header {{
      max-width: 100% !important;
    }}
    [data-testid="stSidebar"] [class*="st-key-main_stats_"] button,
    [data-testid="stSidebar"] [class*="st-key-main_market_"] button,
    [data-testid="stSidebar"] [class*="st-key-main_h2h_"] button {{
      min-height: 64px !important;
      padding-left: 10px !important;
      padding-right: 30px !important;
      font-size: .84rem !important;
      overflow-wrap: anywhere !important;
    }}
    [data-testid="stSidebar"] [class*="st-key-main_stats_"] button::after,
    [data-testid="stSidebar"] [class*="st-key-main_market_"] button::after,
    [data-testid="stSidebar"] [class*="st-key-main_h2h_"] button::after {{
      right: 10px !important;
    }}
  }}
  @media (max-width: 380px) {{
    section[data-testid="stSidebar"],
    [data-testid="stSidebar"] {{
      width: min(84vw, 292px) !important;
      min-width: min(84vw, 292px) !important;
      max-width: min(84vw, 292px) !important;
    }}
    [data-testid="stSidebar"] [class*="st-key-main_stats_"] button,
    [data-testid="stSidebar"] [class*="st-key-main_market_"] button,
    [data-testid="stSidebar"] [class*="st-key-main_h2h_"] button {{
      font-size: .78rem !important;
    }}
  }}

        /* Regreso a partidos: enlace compacto y uniforme debajo de la navegación superior. */
        [class*="st-key-analysis_page_nav"] {{
          position:relative !important; z-index:30 !important;
          width:100% !important; margin-top:-112px !important; margin-bottom:18px !important;
          padding:0 2px !important; box-sizing:border-box !important;
        }}
        [class*="st-key-analysis_page_nav"] [class*="st-key-topnav_back_"] {{
          display:flex !important; justify-content:flex-start !important;
          width:100% !important; margin:112px 0 0 0 !important; padding:0 !important;
        }}
        [class*="st-key-analysis_page_nav"] [class*="st-key-topnav_back_"] [data-testid="stButton"] {{
          width:auto !important; max-width:100% !important; margin:0 !important;
        }}
        [class*="st-key-analysis_page_nav"] [class*="st-key-topnav_back_"] button {{
          display:inline-flex !important; align-items:center !important; justify-content:center !important;
          width:58px !important; min-width:58px !important; max-width:58px !important;
          min-height:58px !important; height:58px !important; padding:0 !important;
          border:2px solid #FACC15 !important; border-radius:50% !important;
          background:linear-gradient(145deg,#252117 0%,#111419 72%) !important;
          box-shadow:0 0 0 1px rgba(250,204,21,.12),0 5px 18px rgba(0,0,0,.32),inset 0 1px 0 rgba(255,229,102,.12) !important;
          color:#FACC15 !important; -webkit-text-fill-color:#FACC15 !important;
          font-size:0 !important; line-height:1 !important; font-weight:900 !important;
          color:transparent !important; -webkit-text-fill-color:transparent !important;
          position:relative !important; overflow:visible !important; text-align:center !important;
          transition:color .18s ease,border-color .18s ease,box-shadow .18s ease,transform .18s ease,background .18s ease !important;
        }}
        [class*="st-key-analysis_page_nav"] [class*="st-key-topnav_back_"] button::before {{
          content:"" !important; display:block !important; position:absolute !important;
          width:42px !important; height:42px !important; left:50% !important; top:50% !important;
          transform:translate(-50%,-50%) !important; pointer-events:none !important;
          background-repeat:no-repeat !important; background-position:center !important; background-size:contain !important;
          background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'%3E%3Cpath d='M3 20 L18 5 L22 9 L11 18 H37 V22 H11 L22 31 L18 35 Z' fill='%23FACC15'/%3E%3C/svg%3E") !important;
          filter:drop-shadow(0 0 3px rgba(250,204,21,.55)) !important;
        }}
        [class*="st-key-analysis_page_nav"] [class*="st-key-topnav_back_"] button:hover::before {{
          background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'%3E%3Cpath d='M3 20 L18 5 L22 9 L11 18 H37 V22 H11 L22 31 L18 35 Z' fill='%23FFE566'/%3E%3C/svg%3E") !important;
        }}
        [class*="st-key-analysis_page_nav"] [class*="st-key-topnav_back_"] button:hover {{
          color:#FFE566 !important; -webkit-text-fill-color:#FFE566 !important;
          border-color:#FFE566 !important; background:linear-gradient(145deg,#332B17 0%,#151820 72%) !important;
          box-shadow:0 0 0 2px rgba(250,204,21,.12),0 0 22px rgba(250,204,21,.22),0 6px 20px rgba(0,0,0,.34) !important;
          transform:translateX(-2px) scale(1.03) !important;
        }}
        [class*="st-key-analysis_page_nav"] [class*="st-key-topnav_back_"] button:focus,
        [class*="st-key-analysis_page_nav"] [class*="st-key-topnav_back_"] button:focus-visible {{
          outline:2px solid rgba(250,204,21,.45) !important; outline-offset:4px !important;
          box-shadow:0 0 0 2px rgba(250,204,21,.12),0 5px 18px rgba(0,0,0,.32) !important;
        }}
        @media(max-width:640px) {{
          /* H2H: mantener todo el contenido dentro del ancho real del móvil. */
          section.main, [data-testid="stMain"], section.main > div.block-container {{
            width:100% !important; max-width:100% !important; min-width:0 !important;
            margin-left:0 !important; margin-right:0 !important; box-sizing:border-box !important;
            overflow-x:hidden !important;
          }}
          section.main > div.block-container:has(.h2h-page-kicker) {{
            padding-left:12px !important; padding-right:12px !important;
          }}
          section.main > div.block-container:has(.h2h-page-kicker) .h2h-page-kicker,
          section.main > div.block-container:has(.h2h-page-kicker) .h2h-page-kicker + div,
          section.main > div.block-container:has(.h2h-page-kicker) .h2h-summary-layout,
          section.main > div.block-container:has(.h2h-page-kicker) .h2h-history-list {{
            width:calc(100% - 28px) !important; max-width:calc(100% - 28px) !important;
            min-width:0 !important; margin-left:14px !important; margin-right:14px !important;
            box-sizing:border-box !important; justify-self:center !important;
          }}
          section.main > div.block-container:has(.h2h-page-kicker) .h2h-summary-layout > *,
          section.main > div.block-container:has(.h2h-page-kicker) .h2h-history-list > * {{
            max-width:100% !important; min-width:0 !important; box-sizing:border-box !important;
          }}
          section.main > div.block-container:has(.h2h-page-kicker) .h2h-description {{
            width:100% !important; max-width:100% !important; min-width:0 !important;
            margin-left:0 !important; margin-right:0 !important; padding-left:6px !important;
            padding-right:6px !important; box-sizing:border-box !important;
          }}
          [class*="st-key-analysis_page_nav"] {{
            width:100% !important; max-width:100% !important; min-width:0 !important;
            margin-left:0 !important; margin-right:0 !important; padding-left:8px !important;
            padding-right:8px !important; box-sizing:border-box !important; overflow:visible !important;
          }}
          [class*="st-key-analysis_page_nav"] [class*="st-key-topnav_back_"] {{
            width:62px !important; max-width:62px !important; min-width:62px !important;
            margin-left:0 !important; margin-right:0 !important; box-sizing:border-box !important;
          }}
          [class*="st-key-analysis_page_nav"] [class*="st-key-topnav_back_"] [data-testid="stButton"] {{
            width:62px !important; max-width:62px !important; min-width:62px !important;
            box-sizing:border-box !important;
          }}
          [class*="st-key-analysis_page_nav"] [class*="st-key-topnav_back_"] button {{
            width:58px !important; max-width:58px !important; min-width:58px !important;
            height:58px !important; min-height:58px !important; padding:0 !important;
            box-sizing:border-box !important; font-size:0 !important;
          }}
        }}
</style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="analysis_page_nav"):
        # Acceso de regreso sin abrir el panel lateral.
        _is_standings_page = _analysis_page_tool == "standings"
        _back_help = "Volver a la pantalla principal de partidos"
        _back_clicked = st.button(" ", key=f"topnav_back_{_analysis_page_id}", help=_back_help)
        if _back_clicked:
            if _is_standings_page:
                st.session_state["main_fixture_tool"] = {"fixture_id": _analysis_page_id, "tool": "stats"}
            else:
                _came_from_upcoming = st.session_state.get("fixture_mode", "live") == "upcoming"
                st.session_state["main_fixture_tool"] = {}
                if not _came_from_upcoming:
                    st.session_state[f"live_match_{_analysis_page_id}"] = True
                    for _match in st.session_state.get("live_fixtures", []):
                        _fixture = _match.get("fixture") or {}
                        if str(_fixture.get("id")) == _analysis_page_id:
                            _league = _match.get("league") or {}
                            _country = _league.get("country") or "Otros países"
                            _league_name = _league.get("name") or "Liga sin nombre"
                            st.session_state[f"live_league_{_country}_{_league_name}"] = True
                            break
                    st.session_state["live_now_expander"] = True
                    st.session_state["return_to_fixture_id"] = _analysis_page_id
                else:
                    # Conservar HOY/MAÑANA al volver desde un encuentro programado.
                    st.session_state["upcoming_day"] = st.session_state.get("upcoming_day", "HOY")
            st.rerun()
    st.markdown(
        '<div class="match-analysis-panel"><div class="match-analysis-kicker">FOOTBALL LAB · ANÁLISIS INDIVIDUAL</div><div class="match-analysis-title">Vista ampliada del partido</div><div class="signal-meta">Consulta el análisis seleccionado y vuelve a los partidos cuando termines.</div></div>',
        unsafe_allow_html=True,
    )

# El formulario envía la búsqueda solo al pulsar Enter o la lupa.
st.session_state.pop("live_search_submit_requested", None)

fixtures = (
    st.session_state.get("upcoming_fixtures", [])
    if st.session_state.get("fixture_mode", "live") == "upcoming"
    else st.session_state.live_fixtures
)

# Buscar partidos o ligas desde la barra lateral y navegar directamente al resultado.
if search_clicked:
    _query = str(st.session_state.get("search_goal_matches", "") or "").strip().casefold()
    if not _query:
        # Una búsqueda vacía restablece la lista completa de partidos en vivo.
        st.session_state.pop("live_search_query", None)
        st.session_state.pop("live_search_message", None)
    else:
        st.session_state["live_search_query"] = _query
        st.session_state.pop("live_search_message", None)
        _team_matches = []
        _league_matches = []
        for _fixture_item in fixtures:
            _teams_item = _fixture_item.get("teams") or {}
            _home_item = _teams_item.get("home") or {}
            _away_item = _teams_item.get("away") or {}
            _league_item = _fixture_item.get("league") or {}
            _home_name_item = str(_home_item.get("name") or "").casefold()
            _away_name_item = str(_away_item.get("name") or "").casefold()
            _league_name_item = str(_league_item.get("name") or "").casefold()
            _country_name_item = str(_league_item.get("country") or "").casefold()
            if _query in _home_name_item or _query in _away_name_item:
                _team_matches.append(_fixture_item)
            if _query in _league_name_item or _query in _country_name_item:
                _league_matches.append(_fixture_item)
        if _team_matches:
            _chosen_fixture = _team_matches[0]
            _chosen_id = str((_chosen_fixture.get("fixture") or {}).get("id") or "")
            _chosen_league = _chosen_fixture.get("league") or {}
            _chosen_country = _chosen_league.get("country") or "Otros países"
            _chosen_league_name = _chosen_league.get("name") or "Liga sin nombre"
            st.session_state["selected_live_fixture_id"] = _chosen_id
            st.session_state["selected_live_fixture"] = _chosen_fixture
            st.session_state["main_fixture_tool"] = {}
            st.session_state["live_now_expander"] = True
            st.session_state[f"live_league_{_chosen_country}_{_chosen_league_name}"] = True
            st.session_state["live_search_query"] = _query
            st.session_state["live_search_message"] = f"Partido encontrado: {(_chosen_fixture.get('teams') or {}).get('home', {}).get('name', 'Local')} vs {(_chosen_fixture.get('teams') or {}).get('away', {}).get('name', 'Visitante')}."
        elif _league_matches:
            st.session_state["live_search_query"] = _query
            st.session_state["live_now_expander"] = True
            for _league_fixture in _league_matches:
                _league_info = _league_fixture.get("league") or {}
                _country_info = _league_info.get("country") or "Otros países"
                _league_name_info = _league_info.get("name") or "Liga sin nombre"
                st.session_state[f"live_league_{_country_info}_{_league_name_info}"] = True
            st.session_state["live_search_message"] = f"Se encontraron {len(_league_matches)} partidos en la liga o país indicado."
        else:
            # Conservar la consulta para que el listado quede vacío y muestre el estado sin resultados.
            st.session_state["live_search_query"] = _query
            st.session_state["live_search_message"] = "No hay resultados"
    st.rerun()

# Borrar el texto de búsqueda restaura todos los partidos en vivo automáticamente.
if not str(st.session_state.get("search_goal_matches", "") or "").strip():
    st.session_state.pop("live_search_query", None)
    st.session_state.pop("live_search_message", None)

if not fixtures:
    st.markdown("### Tu centro de análisis")
    if st.session_state.get("fixture_mode", "live") == "upcoming":
        if st.session_state.get("upcoming_fixtures_error"):
            st.warning("No se pudieron cargar los próximos partidos. Intenta nuevamente en unos minutos.")
        else:
            st.info(f"No hay partidos programados disponibles para {_upcoming_day.lower()} en este momento.")
    else:
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
    # Mostrar partidos en vivo; si se envió una búsqueda, priorizar sus resultados.
    filtered = list(fixtures)
    _submitted_query = str(st.session_state.get("live_search_query", "") or "").strip().casefold()
    if not str(st.session_state.get("search_goal_matches", "") or "").strip():
        _submitted_query = ""
    if _submitted_query:
        _team_filtered = []
        _league_filtered = []
        for _item in filtered:
            _teams = _item.get("teams") or {}
            _home = _teams.get("home") or {}
            _away = _teams.get("away") or {}
            _league = _item.get("league") or {}
            if _submitted_query in str(_home.get("name") or "").casefold() or _submitted_query in str(_away.get("name") or "").casefold():
                _team_filtered.append(_item)
            if _submitted_query in str(_league.get("name") or "").casefold() or _submitted_query in str(_league.get("country") or "").casefold():
                _league_filtered.append(_item)
        filtered = _team_filtered[:1] if _team_filtered else _league_filtered
    with st.container(key="live_now_section"):
        with st.expander((f"Próximos partidos · {_upcoming_day} ({len(filtered)})" if st.session_state.get("fixture_mode", "live") == "upcoming" else f"En vivo ahora ({len(filtered)})"), expanded=st.session_state.get("live_now_expander", False) or bool(_submitted_query) or st.session_state.get("fixture_mode", "live") == "upcoming", key="live_now_expander", on_change="rerun"):
            if not filtered and _submitted_query:
                st.markdown(
                    '<div style="display:flex;align-items:center;justify-content:center;gap:10px;'
                    'margin:10px 0 14px;padding:22px 14px;border:1px solid #34312A;border-radius:12px;'
                    'background:linear-gradient(135deg,#15171C,#101216);color:#FACC15;font-weight:800;'
                    'font-size:1rem;"><span style="font-size:1.25rem;">⌕</span> No hay resultados</div>',
                    unsafe_allow_html=True,
                )
            if filtered:
                grouped = {}
                for match in filtered:
                    league_data = match.get("league") or {}
                    country = league_data.get("country") or "Otros países"
                    league_name = league_data.get("name") or "Liga sin nombre"
                    grouped.setdefault((country, league_name), []).append(match)
                _country_flags = {
                    "Argentina": "🇦🇷", "Brazil": "🇧🇷", "Brasil": "🇧🇷",
                    "Colombia": "🇨🇴", "Paraguay": "🇵🇾", "Guatemala": "🇬🇹",
                    "England": "🏴", "Spain": "🇪🇸", "Italy": "🇮🇹",
                    "Germany": "🇩🇪", "France": "🇫🇷", "Portugal": "🇵🇹",
                    "Mexico": "🇲🇽", "United States": "🇺🇸", "USA": "🇺🇸",
                    "Chile": "🇨🇱", "Uruguay": "🇺🇾", "Peru": "🇵🇪",
                    "Ecuador": "🇪🇨", "Bolivia": "🇧🇴", "Venezuela": "🇻🇪",
                    "Netherlands": "🇳🇱", "Turkey": "🇹🇷", "Saudi Arabia": "🇸🇦",
                    "Japan": "🇯🇵", "South Korea": "🇰🇷", "World": "🌍",
                }
                for (country, league_name), league_matches in sorted(grouped.items()):
                    _league_meta = next(
                        (item.get("league") or {} for item in league_matches if item.get("league")),
                        {},
                    )
                    _league_logo = str(_league_meta.get("logo") or "").strip()
                    _league_icon = f"![]({_league_logo}) " if _league_logo else f"{_country_flags.get(country, '🏳️')} "
                    _league_count = len(league_matches)
                    _league_expander_label = f"{_league_icon}**{country} · {league_name}**　　**({_league_count})**"
                    with st.expander(_league_expander_label, expanded=st.session_state.get(f"live_league_{country}_{league_name}", False), key=f"live_league_{country}_{league_name}", on_change="rerun"):
                        # Cada partido tiene una sola tarjeta principal; evitamos duplicar el marcador
                        # en una cuadrícula y otra vez dentro del expander de análisis.
                        # Match tools are available from the main live scanner, before a full market scan.
                        for match in league_matches:
                            match_fixture = match.get("fixture") or {}
                            match_id = match_fixture.get("id")
                            # Compatibilidad: algunos bloques de análisis usan el alias fixture_id.
                            fixture_id = match_id
                            match_teams = match.get("teams") or {}
                            match_home = match_teams.get("home") or {}
                            match_away = match_teams.get("away") or {}
                            match_home_id, match_away_id = match_home.get("id"), match_away.get("id")
                            match_home_name = str(match_home.get("name") or "Local")
                            match_away_name = str(match_away.get("name") or "Visitante")
                            match_home_logo = str(match_home.get("logo") or "")
                            match_away_logo = str(match_away.get("logo") or "")
                            match_goals = match.get("goals") or {}
                            score_label = f"{match_goals.get('home', '—')}–{match_goals.get('away', '—')}"
                            match_minute = ((match_fixture.get("status") or {}).get("elapsed"))
                            match_label = f"{match_home_name} vs {match_away_name}"
                            if not match_id:
                                continue
                            # Los partidos no son expanders individuales: al abrir una liga aparecen todos los marcadores grandes.
                            # La única flecha para contraer/expandir es la de la liga.
                            with st.container(key=f"live_match_{match_id}"):
                                # Marcador detallado primero: reloj a la izquierda y una fila por equipo.
                                _clock_text = (datetime.fromisoformat(str(match_fixture.get("date")).replace("Z", "+00:00")).astimezone(_colombia_tz).strftime("%H:%M") if st.session_state.get("fixture_mode", "live") == "upcoming" and match_fixture.get("date") else (f"{match_minute}:00" if match_minute is not None else str(((match_fixture.get("status") or {}).get("short") or "EN VIVO"))))
                                _clock_data_attr = f' data-base-minute="{int(match_minute)}"' if match_minute is not None else ""
                                _home_score = "—" if st.session_state.get("fixture_mode", "live") == "upcoming" else (match_goals.get("home") if match_goals.get("home") is not None else "—")
                                _away_score = "—" if st.session_state.get("fixture_mode", "live") == "upcoming" else (match_goals.get("away") if match_goals.get("away") is not None else "—")
                                _home_crest = f'<img class="fl-match-crest" src="{html.escape(match_home_logo, quote=True)}" alt="">' if match_home_logo else '<span class="fl-match-crest-empty">⚽</span>'
                                _away_crest = f'<img class="fl-match-crest" src="{html.escape(match_away_logo, quote=True)}" alt="">' if match_away_logo else '<span class="fl-match-crest-empty">⚽</span>'
                                _home_red_cards, _away_red_cards = (0, 0) if st.session_state.get("fixture_mode", "live") == "upcoming" else fixture_red_card_counts(match_id, match_home_id, match_away_id)
                                _home_red_badge = f'<span class="fl-red-card-badge" title="Tarjeta roja">🟥{(" ×" + str(_home_red_cards)) if _home_red_cards > 1 else ""}</span>' if _home_red_cards else ""
                                _away_red_badge = f'<span class="fl-red-card-badge" title="Tarjeta roja">🟥{(" ×" + str(_away_red_cards)) if _away_red_cards > 1 else ""}</span>' if _away_red_cards else ""
                                _status_short = str((match_fixture.get("status") or {}).get("short") or "")
                                _live_badge = ('<span class="fl-match-live">PRÓXIMO</span>' if st.session_state.get("fixture_mode", "live") == "upcoming" else ('<span class="fl-match-live">EN VIVO</span>' if _status_short in {"1H", "HT", "2H", "ET", "BT", "P", "LIVE"} or match_minute is not None else ""))
                                _is_selected_fixture = str(st.session_state.get("selected_live_fixture_id") or "") == str(match_id)
                                _scoreboard_class = "fl-match-scoreboard is-selected" if _is_selected_fixture else "fl-match-scoreboard"
                                st.markdown(
                                    f'<div class="{_scoreboard_class}">'
                                    f'<div class="fl-match-clock"><div class="fl-match-minute"{_clock_data_attr}>{html.escape(_clock_text)}</div>{_live_badge}</div>'
                                    f'<div class="fl-match-teams">'
                                    f'<div class="fl-match-team"><span class="fl-match-goals">{html.escape(str(_home_score))}</span>{_home_crest}<span class="fl-match-team-name">{html.escape(match_home_name)}</span>{_home_red_badge}</div>'
                                    f'<div class="fl-match-team"><span class="fl-match-goals">{html.escape(str(_away_score))}</span>{_away_crest}<span class="fl-match-team-name">{html.escape(match_away_name)}</span>{_away_red_badge}</div>'
                                    f'</div></div>',
                                    unsafe_allow_html=True,
                                )
                                _select_this_fixture = st.button(" ", key=f"select_live_match_{match_id}", help=f"Seleccionar {match_label}", use_container_width=True)
                                if _select_this_fixture:
                                    st.session_state["selected_live_fixture_id"] = str(match_id)
                                    st.session_state["selected_live_fixture"] = match
                                    st.session_state["main_fixture_tool"] = {}
                                    st.rerun()
                                if str(st.session_state.get("selected_live_fixture_id") or "") == str(match_id):
                                    st.caption(f"ID del partido (fixture): {match_id}")
                                selected_tool = st.session_state.get("main_fixture_tool") or {}
                                if str(selected_tool.get("fixture_id")) == str(match_id):
                                    tool_name = selected_tool.get("tool")
                                    if tool_name != "stats" and not _analysis_page_active:
                                        st.markdown('<div class="match-analysis-kicker">PARTIDO SELECCIONADO</div>', unsafe_allow_html=True)
                                    if tool_name == "stats":
                                        # Adaptador AI: reutiliza api_get y la caché existente; no añade
                                        # endpoints ni solicitudes de red al flujo actual.
                                        _ai_data_engine = FootballDataEngine(api_get, st.session_state.stats_cache)
                                        if st.session_state.get("fixture_mode", "live") == "upcoming":
                                            stat_data = []
                                            stats_error = None
                                        else:
                                            if str(match_id) not in st.session_state.stats_cache or str(match_id) in st.session_state.get("stats_errors", {}):
                                                try:
                                                    stat_data = _ai_data_engine.get_fixture_statistics(match_id)
                                                    st.session_state.stats_cache[str(match_id)] = stat_data
                                                    st.session_state.setdefault("stats_errors", {}).pop(str(match_id), None)
                                                except Exception as _stats_exc:
                                                    st.session_state.stats_cache[str(match_id)] = []
                                                    st.session_state.setdefault("stats_errors", {})[str(match_id)] = str(_stats_exc)
                                            stat_data = st.session_state.stats_cache.get(str(match_id), [])
                                            stats_error = st.session_state.get("stats_errors", {}).get(str(match_id))
                                        stats_error = st.session_state.get("stats_errors", {}).get(str(match_id))

                                        # Snapshot versionado para la futura IA prepartido/en vivo.
                                        # Se construye únicamente con datos ya disponibles en la sesión.
                                        _live_odds_cache = st.session_state.get("live_odds_by_fixture", {}) or {}
                                        _match_odds = _live_odds_cache.get(str(match_id), _live_odds_cache.get(match_id, {}))
                                        _ai_snapshots = st.session_state.setdefault("ai_match_snapshots", {})
                                        _ai_snapshots[str(match_id)] = _ai_data_engine.snapshot(
                                            match, statistics=stat_data, odds=_match_odds
                                        )
                                        while len(_ai_snapshots) > 100:
                                            _ai_snapshots.pop(next(iter(_ai_snapshots)))
                                        if stats_error:
                                            st.warning(f"No se pudieron cargar las estadísticas: {stats_error}")
                                        elif stat_data:
                                            stat_names = ("Ball Possession", "Total Shots", "Shots on Goal", "Corner Kicks", "Yellow Cards", "Red Cards", "Fouls", "Offsides", "Goalkeeper Saves", "Total passes", "Passes %")
                                            stat_labels = {"Ball Possession":"Posesión del balón", "Total Shots":"Tiros totales", "Shots on Goal":"Tiros a puerta", "Corner Kicks":"Córners", "Yellow Cards":"Tarjetas amarillas", "Red Cards":"Tarjetas rojas", "Fouls":"Faltas", "Offsides":"Fueras de juego", "Goalkeeper Saves":"Atajadas", "Total passes":"Pases", "Passes %":"Precisión de pases"}
                                            home_stats = {entry.get("type"): entry.get("value") for entry in ((stat_data[0].get("statistics") or []) if len(stat_data) > 0 else [])}
                                            away_stats = {entry.get("type"): entry.get("value") for entry in ((stat_data[1].get("statistics") or []) if len(stat_data) > 1 else [])}
                                            home_name = html.escape(str(match_home.get("name") or "Local"))
                                            away_name = html.escape(str(match_away.get("name") or "Visitante"))
                                            home_logo = html.escape(str(match_home.get("logo") or ""), quote=True)
                                            away_logo = html.escape(str(match_away.get("logo") or ""), quote=True)
                                            league_label = html.escape(str((match.get("league") or {}).get("name") or "Competición en vivo"))
                                            minute_value = ((match.get("fixture") or {}).get("status") or {}).get("elapsed")
                                            minute_label = f"{minute_value}′" if minute_value is not None else "EN VIVO"
                                            goals = match.get("goals") or {}
                                            home_goals = goals.get("home") if goals.get("home") is not None else "–"
                                            away_goals = goals.get("away") if goals.get("away") is not None else "–"
                                            home_badge = f'<img src="{home_logo}" alt="" onerror="this.style.display=\'none\'">' if home_logo else '<span class="stats-team-fallback">⚽</span>'
                                            away_badge = f'<img src="{away_logo}" alt="" onerror="this.style.display=\'none\'">' if away_logo else '<span class="stats-team-fallback">⚽</span>'
                                            stats_html = (
                                                '<section class="live-stats-panel">'
                                                '<header class="live-stats-heading"><span class="live-stats-heading-icon">▮▮▮</span><span>Estadísticas en vivo</span><span class="live-stats-live"><i></i> EN VIVO</span></header>'
                                                '<div class="live-stats-scoreboard">'
                                                f'<div class="live-stats-league">{league_label} <span>·</span> {html.escape(str(minute_label))}</div>'
                                                f'<div class="live-stats-teams"><div class="live-stats-team">{home_badge}<strong>{home_name}</strong></div>'
                                                f'<div class="live-stats-score">{home_goals} - {away_goals}</div>'
                                                f'<div class="live-stats-team">{away_badge}<strong>{away_name}</strong></div></div>'
                                                '<div class="live-stats-pitch"><div class="pitch-half"></div><div class="pitch-circle"></div><div class="pitch-box pitch-box-left"></div><div class="pitch-box pitch-box-right"></div>'
                                                f'<div class="pitch-minute">{html.escape(str(minute_label))}</div><div class="pitch-score">{home_goals} - {away_goals}</div>'
                                                f'<div class="pitch-team pitch-team-left">{home_badge}<span>{home_name}</span></div><div class="pitch-team pitch-team-right">{away_badge}<span>{away_name}</span></div></div>'
                                                '</div><div class="live-stats-metrics">'
                                            )
                                            rendered = 0
                                            for stat_name in stat_names:
                                                if stat_name not in home_stats and stat_name not in away_stats:
                                                    continue
                                                hv, av = home_stats.get(stat_name), away_stats.get(stat_name)
                                                def display_stat(value):
                                                    return "N/D" if value is None else html.escape(str(value))
                                                def numeric_stat(value):
                                                    try:
                                                        return float(str(value).replace("%", "").replace(",", ".").strip())
                                                    except (TypeError, ValueError):
                                                        return 0.0
                                                hnum, anum = numeric_stat(hv), numeric_stat(av)
                                                total = hnum + anum
                                                hwidth = (hnum / total * 100) if total > 0 else 50
                                                awidth = (anum / total * 100) if total > 0 else 50
                                                stats_html += (
                                                    f'<div class="live-stat-row"><div class="live-stat-values"><strong>{display_stat(hv)}</strong><span>{html.escape(stat_labels[stat_name])}</span><strong>{display_stat(av)}</strong></div>'
                                                    f'<div class="live-stat-track"><span class="live-stat-home" style="width:{hwidth:.1f}%"></span><span class="live-stat-away" style="width:{awidth:.1f}%"></span></div></div>'
                                                )
                                                rendered += 1
                                            stats_html += '</div></section>'
                                            if rendered:
                                                st.markdown(stats_html, unsafe_allow_html=True)
                                            else:
                                                st.info("La API no entregó estadísticas detalladas para este partido.")
                                        else:
                                            if st.session_state.get("fixture_mode", "live") == "upcoming":
                                                st.info("El partido aún no comienza. Las estadísticas en vivo aparecerán al iniciar; mientras tanto puedes consultar los indicadores históricos y las proyecciones.")
                                            else:
                                                st.info("La API no entregó estadísticas para este partido.")

                                        # TARJETAS AMARILLAS: promedios de localía, visitante e H2H.
                                        _card_league = match.get("league") or {}
                                        _card_league_id = _card_league.get("id")
                                        _card_season = _card_league.get("season")
                                        _card_home_id, _card_away_id = match_home.get("id"), match_away.get("id")
                                        _card_cache = st.session_state.setdefault("yellow_card_analysis_cache", {})
                                        _card_cache_key = f"{_card_league_id}:{_card_season}:{_card_home_id}:{_card_away_id}"
                                        if _card_cache_key not in _card_cache:
                                            _card_result = {"home": [], "away": [], "h2h": []}
                                            def _card_fixture_average(team_id, venue):
                                                _fixtures_payload = api_get("fixtures", {"team": team_id, "league": _card_league_id, "season": _card_season, "last": 20})
                                                _fixtures_list = _fixtures_payload.get("response") or []
                                                _selected_fixtures = []
                                                for _fx in _fixtures_list:
                                                    _fx_teams = _fx.get("teams") or {}
                                                    _is_home = (_fx_teams.get("home") or {}).get("id") == team_id
                                                    if (_is_home and venue == "home") or ((not _is_home) and venue == "away"):
                                                        _selected_fixtures.append(_fx)
                                                _values = []
                                                for _fx in _selected_fixtures[:10]:
                                                    _fx_id = ((_fx.get("fixture") or {}).get("id"))
                                                    if not _fx_id:
                                                        continue
                                                    _st_payload = api_get("fixtures/statistics", {"fixture": _fx_id})
                                                    _st_response = _st_payload.get("response") or []
                                                    for _team_stats in _st_response:
                                                        if ((_team_stats.get("team") or {}).get("id")) == team_id:
                                                            _yellow = next((x.get("value") for x in (_team_stats.get("statistics") or []) if x.get("type") == "Yellow Cards"), None)
                                                            if _yellow is not None:
                                                                try: _values.append(float(str(_yellow).replace(",", ".")))
                                                                except (TypeError, ValueError): pass
                                                            break
                                                return {"average": (sum(_values) / len(_values)) if _values else None, "matches": len(_values)}
                                            try:
                                                _card_result["home"] = _card_fixture_average(_card_home_id, "home")
                                                _card_result["away"] = _card_fixture_average(_card_away_id, "away")
                                                _h2h_payload = api_get("fixtures/headtohead", {"h2h": f"{_card_home_id}-{_card_away_id}", "last": 10})
                                                _h2h_fixtures = _h2h_payload.get("response") or []
                                                _h2h_values = []
                                                for _fx in _h2h_fixtures:
                                                    _fx_teams = _fx.get("teams") or {}
                                                    _fx_home_id = (_fx_teams.get("home") or {}).get("id")
                                                    _fx_away_id = (_fx_teams.get("away") or {}).get("id")
                                                    # Comparar solo enfrentamientos con la misma condición de localía del partido actual.
                                                    if _fx_home_id != _card_home_id or _fx_away_id != _card_away_id:
                                                        continue
                                                    _fx_id = ((_fx.get("fixture") or {}).get("id"))
                                                    if not _fx_id:
                                                        continue
                                                    _st_payload = api_get("fixtures/statistics", {"fixture": _fx_id})
                                                    _st_response = _st_payload.get("response") or []
                                                    _yellow_total = 0.0
                                                    _has_yellow = False
                                                    for _team_stats in _st_response:
                                                        _yellow = next((x.get("value") for x in (_team_stats.get("statistics") or []) if x.get("type") == "Yellow Cards"), None)
                                                        if _yellow is not None:
                                                            try:
                                                                _yellow_total += float(str(_yellow).replace(",", "."))
                                                                _has_yellow = True
                                                            except (TypeError, ValueError): pass
                                                    if _has_yellow: _h2h_values.append(_yellow_total)
                                                _card_result["h2h"] = {"average": (sum(_h2h_values) / len(_h2h_values)) if _h2h_values else None, "matches": len(_h2h_values)}
                                            except Exception:
                                                _card_result["error"] = True
                                            _card_cache[_card_cache_key] = _card_result
                                        _card_result = _card_cache[_card_cache_key]
                                        _card_home_avg = (_card_result.get("home") or {}).get("average")
                                        _card_away_avg = (_card_result.get("away") or {}).get("average")
                                        _card_h2h_avg = (_card_result.get("h2h") or {}).get("average")
                                        _card_total_today = max(0, (_card_home_avg + _card_away_avg + _card_h2h_avg) / 2 - 0.3) if _card_home_avg is not None and _card_away_avg is not None and _card_h2h_avg is not None else None
                                        def _card_fmt(value):
                                            return f"{value:.2f}" if value is not None else "N/D"
                                        _card_home_count = (_card_result.get("home") or {}).get("matches", 0)
                                        _card_away_count = (_card_result.get("away") or {}).get("matches", 0)
                                        _card_h2h_count = (_card_result.get("h2h") or {}).get("matches", 0)
                                        _card_html = (
                                            '<section class="fl-yellow-analysis"><header><span>🟨</span><strong>Proyección de tarjetas</strong></header>'
                                            '<div class="fl-yellow-grid">'
                                            f'<article><small>{html.escape(str(match_home_name))} · LOCAL</small><b>{_card_fmt(_card_home_avg)}</b><span>{_card_home_count} partidos analizados</span></article>'
                                            f'<article><small>{html.escape(str(match_away_name))} · VISITANTE</small><b>{_card_fmt(_card_away_avg)}</b><span>{_card_away_count} partidos analizados</span></article>'
                                            f'<article><small>HISTORIAL DIRECTO · MISMA LOCALÍA · TOTAL</small><b>{_card_fmt(_card_h2h_avg)}</b><span>{_card_h2h_count} enfrentamientos con datos</span></article>'
                                            '</div>'
                                            f'<div class="fl-yellow-estimate"><small>TOTAL TARJETAS PARA HOY</small><div class="fl-yellow-total"><strong>{_card_fmt(_card_total_today)}</strong><span class="fl-yellow-card-icon">🟨</span></div></div>'
                                            '<p>Estimación calculada con los promedios de local y visitante, el historial directo con la misma localía y un margen conservador de 0,3.</p></section>'
                                        )
                                        st.markdown(_card_html + """
                                        <style>
                                        .fl-yellow-analysis{margin:16px 0;padding:15px;border:1px solid #A88632;border-radius:16px;background:linear-gradient(145deg,#171A20,#0D1015);color:#F8FAFC}
                                        .fl-yellow-analysis header{display:flex;gap:9px;align-items:center;color:#F1F3F6;font-size:clamp(1.28rem,2.35vw,1.58rem);font-weight:800;letter-spacing:.005em;line-height:1.25;text-transform:none;margin-bottom:12px}.fl-yellow-analysis header strong{color:#F1F3F6;font:inherit;text-transform:none}
                                        .fl-yellow-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
                                        .fl-yellow-grid article{display:flex;flex-direction:column;gap:4px;padding:10px;border:1px solid #343944;border-radius:10px;background:#20242B;min-width:0}
                                        .fl-yellow-grid article:nth-child(3){grid-column:1/-1}
                                        .fl-yellow-grid small,.fl-yellow-estimate small{font-size:9px;color:#AEB5C0}
                                        .fl-yellow-grid b{font-size:22px;color:#F2C94C}
                                        .fl-yellow-grid span{font-size:10px;color:#AEB5C0}
                                        .fl-yellow-estimate{display:grid;grid-template-columns:1fr;gap:9px;margin-top:10px;padding:14px;border:2px solid #FACC15;border-radius:12px;background:linear-gradient(135deg,rgba(250,204,21,.16),#191C22 52%,#101216);box-shadow:0 0 0 1px rgba(250,204,21,.22),0 0 16px rgba(250,204,21,.16)}
                                        .fl-yellow-estimate b{font-size:19px;color:#F8FAFC}
                                        .fl-yellow-estimate small{font-size:13px;font-weight:950;letter-spacing:.35px;color:#FFE566}
                                        .fl-yellow-estimate strong{font-size:30px;line-height:1;color:#F2C94C;font-weight:950;font-variant-numeric:tabular-nums;text-shadow:0 0 12px rgba(242,201,76,.22)}
                                        .fl-yellow-total{display:flex;align-items:center;justify-content:center;gap:10px;min-height:48px}
                                        .fl-yellow-card-icon{display:inline-flex;align-items:center;justify-content:center;font-size:34px;line-height:1;filter:drop-shadow(0 0 7px rgba(250,204,21,.55));animation:fl-yellow-card-pulse 1.15s ease-in-out infinite}
                                        @keyframes fl-yellow-card-pulse{0%,100%{transform:scale(1);filter:drop-shadow(0 0 4px rgba(250,204,21,.35));opacity:.88}50%{transform:scale(1.13);filter:drop-shadow(0 0 12px rgba(250,204,21,.9));opacity:1}}
                                        .fl-yellow-analysis p{font-size:10px;color:#AEB5C0;margin:10px 0 0}
                                        @media(prefers-reduced-motion:reduce){.fl-yellow-card-icon{animation:none}}
                                        </style>
                                        """, unsafe_allow_html=True)

                                        # PROYECCIÓN DE TIROS: misma competición y condición local/visitante.
                                        _shots_league_id = _card_league_id
                                        _shots_season = _card_season
                                        _shots_home_id, _shots_away_id = _card_home_id, _card_away_id
                                        _shots_cache = st.session_state.setdefault("shots_analysis_cache", {})
                                        _shots_cache_key = f"{_shots_league_id}:{_shots_season}:{_shots_home_id}:{_shots_away_id}"
                                        if _shots_cache_key not in _shots_cache:
                                            _shots_result = {"home": {}, "away": {}, "h2h": {"total": None, "on_target": None, "matches": 0}}

                                            def _shots_number(_value):
                                                if _value is None:
                                                    return None
                                                try:
                                                    return float(str(_value).replace(",", ".").strip())
                                                except (TypeError, ValueError):
                                                    return None

                                            def _shots_team_average(_team_id, _venue):
                                                _team_result = {"total": None, "on_target": None, "total_matches": 0, "on_target_matches": 0}
                                                if not _team_id or not _shots_league_id or not _shots_season:
                                                    return _team_result
                                                _team_fixtures_payload = api_get("fixtures", {
                                                    "team": _team_id, "league": _shots_league_id,
                                                    "season": _shots_season, "last": 20
                                                })
                                                _team_fixtures = _team_fixtures_payload.get("response") or []
                                                _eligible = []
                                                for _past_fixture in _team_fixtures:
                                                    _past_teams = _past_fixture.get("teams") or {}
                                                    _past_home_id = (_past_teams.get("home") or {}).get("id")
                                                    _past_away_id = (_past_teams.get("away") or {}).get("id")
                                                    _past_status = (((_past_fixture.get("fixture") or {}).get("status") or {}).get("short") or "")
                                                    _same_venue = (_past_home_id == _team_id) if _venue == "home" else (_past_away_id == _team_id)
                                                    if _same_venue and _past_status in {"FT", "AET", "PEN"}:
                                                        _eligible.append(_past_fixture)
                                                _total_values, _on_target_values = [], []
                                                for _past_fixture in _eligible[:10]:
                                                    _past_id = ((_past_fixture.get("fixture") or {}).get("id"))
                                                    if not _past_id:
                                                        continue
                                                    _past_stats_payload = api_get("fixtures/statistics", {"fixture": _past_id})
                                                    _past_stats = _past_stats_payload.get("response") or []
                                                    _team_row = next(
                                                        (row for row in _past_stats if str((row.get("team") or {}).get("id")) == str(_team_id)),
                                                        None
                                                    )
                                                    if not _team_row:
                                                        continue
                                                    _team_stat_values = {
                                                        item.get("type"): item.get("value")
                                                        for item in (_team_row.get("statistics") or [])
                                                    }
                                                    _total_value = _shots_number(_team_stat_values.get("Total Shots"))
                                                    _on_target_value = _shots_number(_team_stat_values.get("Shots on Goal"))
                                                    if _total_value is not None:
                                                        _total_values.append(_total_value)
                                                    if _on_target_value is not None:
                                                        _on_target_values.append(_on_target_value)
                                                _team_result["total"] = (sum(_total_values) / len(_total_values)) if _total_values else None
                                                _team_result["on_target"] = (sum(_on_target_values) / len(_on_target_values)) if _on_target_values else None
                                                _team_result["total_matches"] = len(_total_values)
                                                _team_result["on_target_matches"] = len(_on_target_values)
                                                return _team_result

                                            try:
                                                _shots_result["home"] = _shots_team_average(_shots_home_id, "home")
                                                _shots_result["away"] = _shots_team_average(_shots_away_id, "away")

                                                # H2H: promedio del total combinado de tiros de ambos equipos
                                                # en sus últimos enfrentamientos directos con estadísticas disponibles.
                                                _h2h_total_values, _h2h_on_values = [], []
                                                _h2h_payload = api_get("fixtures/headtohead", {
                                                    "h2h": f"{_shots_home_id}-{_shots_away_id}", "last": 10
                                                })
                                                _h2h_fixtures = _h2h_payload.get("response") or []
                                                for _h2h_fixture in _h2h_fixtures:
                                                    _h2h_status = (((_h2h_fixture.get("fixture") or {}).get("status") or {}).get("short") or "")
                                                    _h2h_fixture_id = (_h2h_fixture.get("fixture") or {}).get("id")
                                                    if not _h2h_fixture_id or _h2h_status not in {"FT", "AET", "PEN"}:
                                                        continue
                                                    _h2h_stats_payload = api_get("fixtures/statistics", {"fixture": _h2h_fixture_id})
                                                    _h2h_rows = _h2h_stats_payload.get("response") or []
                                                    _match_total_shots, _match_on_shots = 0.0, 0.0
                                                    _has_total, _has_on = False, False
                                                    for _h2h_row in _h2h_rows:
                                                        _h2h_values = {
                                                            item.get("type"): item.get("value")
                                                            for item in (_h2h_row.get("statistics") or [])
                                                        }
                                                        _total = _shots_number(_h2h_values.get("Total Shots"))
                                                        _on = _shots_number(_h2h_values.get("Shots on Goal"))
                                                        if _total is not None:
                                                            _match_total_shots += _total
                                                            _has_total = True
                                                        if _on is not None:
                                                            _match_on_shots += _on
                                                            _has_on = True
                                                    if _has_total:
                                                        _h2h_total_values.append(_match_total_shots)
                                                    if _has_on:
                                                        _h2h_on_values.append(_match_on_shots)

                                                _shots_result["h2h"] = {
                                                    "total": (sum(_h2h_total_values) / len(_h2h_total_values)) if len(_h2h_total_values) >= 3 else None,
                                                    "on_target": (sum(_h2h_on_values) / len(_h2h_on_values)) if len(_h2h_on_values) >= 3 else None,
                                                    "matches": min(len(_h2h_total_values), len(_h2h_on_values))
                                                }
                                            except Exception as _shots_exc:
                                                _shots_result["error"] = str(_shots_exc)
                                            _shots_cache[_shots_cache_key] = _shots_result

                                        _shots_result = _shots_cache[_shots_cache_key]
                                        _shots_home = _shots_result.get("home") or {}
                                        _shots_away = _shots_result.get("away") or {}
                                        _shots_home_total = _shots_home.get("total")
                                        _shots_away_total = _shots_away.get("total")
                                        _shots_home_on = _shots_home.get("on_target")
                                        _shots_away_on = _shots_away.get("on_target")
                                        _shots_h2h = _shots_result.get("h2h") or {}
                                        _shots_base_total = (_shots_home_total + _shots_away_total) if _shots_home_total is not None and _shots_away_total is not None else None
                                        _shots_base_on = (_shots_home_on + _shots_away_on) if _shots_home_on is not None and _shots_away_on is not None else None
                                        _shots_total_blended = (0.80 * _shots_base_total + 0.20 * _shots_h2h["total"]) if _shots_base_total is not None and _shots_h2h.get("total") is not None else _shots_base_total
                                        _shots_on_blended = (0.80 * _shots_base_on + 0.20 * _shots_h2h["on_target"]) if _shots_base_on is not None and _shots_h2h.get("on_target") is not None else _shots_base_on
                                        _shots_total_today = max(0, _shots_total_blended - 5.0) if _shots_total_blended is not None else None
                                        _shots_on_today = max(0, _shots_on_blended - 3.0) if _shots_on_blended is not None else None

                                        def _shots_fmt(_value):
                                            return f"{_value:.1f}" if _value is not None else "N/D"

                                        _shots_html = (
                                            '<section class="fl-shots-analysis">'
                                            '<header><span>🎯</span><strong>Proyección de tiros</strong></header>'
                                            '<div class="fl-shots-grid">'
                                            f'<article><small>{html.escape(str(match_home_name))} · LOCAL</small><b>{_shots_fmt(_shots_home_on)}</b><span>Tiros a puerta · {_shots_home.get("on_target_matches", 0)} partidos</span><b class="fl-shots-secondary">{_shots_fmt(_shots_home_total)}</b><span>Tiros totales · {_shots_home.get("total_matches", 0)} partidos</span></article>'
                                            f'<article><small>{html.escape(str(match_away_name))} · VISITANTE</small><b>{_shots_fmt(_shots_away_on)}</b><span>Tiros a puerta · {_shots_away.get("on_target_matches", 0)} partidos</span><b class="fl-shots-secondary">{_shots_fmt(_shots_away_total)}</b><span>Tiros totales · {_shots_away.get("total_matches", 0)} partidos</span></article>'
                                            '</div>'
                                            '<div class="fl-shots-estimates">'
                                            f'<article><small>TIROS A PUERTA HOY</small><strong>{_shots_fmt(_shots_on_today)}</strong></article>'
                                            f'<article><small>TIROS TOTALES HOY</small><strong>{_shots_fmt(_shots_total_today)}</strong></article>'
                                            '</div>'
                                            '<p>Promedios de los últimos 10 partidos finalizados de esta competición, filtrados por localía: local en casa y visitante fuera. Los datos faltantes no se cuentan como cero.</p>'
                                            '</section>'
                                        )
                                        if _shots_result.get("error"):
                                            _shots_html += '<p class="fl-shots-note">No fue posible completar todas las consultas históricas. Se muestran únicamente los datos disponibles.</p>'
                                        st.markdown(_shots_html + """
                                        <style>
                                        .fl-shots-analysis{margin:16px 0;padding:15px;border:1px solid #A88632;border-radius:16px;background:linear-gradient(145deg,#171A20,#0D1015);color:#F8FAFC}
                                        .fl-shots-analysis header{display:flex;align-items:center;gap:9px;margin-bottom:12px;color:#F1F3F6;font-size:clamp(1.28rem,2.35vw,1.58rem);font-weight:800;letter-spacing:.005em;line-height:1.25;text-transform:none}.fl-shots-analysis header strong{color:#F1F3F6;font:inherit;text-transform:none}
                                        .fl-shots-grid,.fl-shots-estimates{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
                                        .fl-shots-grid article{display:flex;flex-direction:column;gap:4px;min-width:0;padding:11px;border:1px solid #343944;border-radius:11px;background:#20242B}
                                        .fl-shots-grid small,.fl-shots-estimates small{font-size:9px;color:#AEB5C0;font-weight:800}
                                        .fl-shots-grid b{font-size:23px;line-height:1.1;color:#F2C94C}
                                        .fl-shots-grid .fl-shots-secondary{margin-top:5px;font-size:18px;color:#F8D96A}
                                        .fl-shots-grid span,.fl-shots-estimates span{font-size:10px;color:#AEB5C0}
                                        .fl-shots-estimates{margin-top:10px}
                                        .fl-shots-estimates article{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:7px;min-width:0;padding:13px 8px;border:1.5px solid #FACC15;border-radius:12px;background:linear-gradient(135deg,rgba(250,204,21,.16),#191C22 60%,#101216);box-shadow:0 0 12px rgba(250,204,21,.10)}
                                        .fl-shots-estimates small{color:#FFE566;text-align:center;font-size:10px;font-weight:950;letter-spacing:.025em}
                                        .fl-shots-estimates strong{font-size:29px;line-height:1;color:#F2C94C;font-weight:950;font-variant-numeric:tabular-nums}
                                        .fl-shots-estimates span{text-align:center}
                                        .fl-shots-analysis p,.fl-shots-note{margin:10px 0 0;color:#AEB5C0;font-size:10px;line-height:1.45}
                                        @media(max-width:380px){.fl-shots-analysis{padding:11px}.fl-shots-grid,.fl-shots-estimates{gap:6px}.fl-shots-grid article{padding:8px}.fl-shots-grid b{font-size:20px}.fl-shots-estimates strong{font-size:25px}}

                                        </style>
                                        """, unsafe_allow_html=True)
                                        st.markdown("""
                                        <style>
                                        [class*="st-key-league_standings_cta"] {
                                          display:block !important; width:100% !important; max-width:100% !important;
                                          min-width:0 !important; margin:12px 0 16px !important;
                                          padding:0 !important; box-sizing:border-box !important;
                                        }
                                        [class*="st-key-league_standings_cta"] [data-testid="stButton"],
                                        [class*="st-key-league_standings_cta"] [data-testid="stButton"] > div {
                                          display:block !important; width:100% !important; min-width:0 !important;
                                          max-width:100% !important; margin:0 !important; padding:0 !important;
                                          box-sizing:border-box !important;
                                        }
                                        [class*="st-key-league_standings_cta"] [data-testid="stButton"] > button {
                                          display:flex !important; flex-direction:row !important; align-items:center !important;
                                          justify-content:flex-start !important; gap:10px !important;
                                          width:100% !important; min-width:0 !important; max-width:100% !important;
                                          height:54px !important; min-height:54px !important; max-height:54px !important;
                                          padding:0 16px !important; box-sizing:border-box !important; overflow:hidden !important;
                                          border:1px solid #A88A36 !important; border-radius:13px !important;
                                          color:#FFE27A !important; -webkit-text-fill-color:#FFE27A !important;
                                          background:linear-gradient(105deg,#302817 0%,#1D1F25 58%,#15171C 100%) !important;
                                          font-size:1rem !important; font-weight:900 !important; letter-spacing:.035em !important;
                                          line-height:1 !important; text-align:left !important; white-space:nowrap !important;
                                          box-shadow:inset 0 1px 0 rgba(255,255,255,.065),0 4px 13px rgba(0,0,0,.24),inset 3px 0 0 rgba(250,204,21,.65) !important;
                                          transition:border-color .18s ease,background .18s ease,box-shadow .18s ease,transform .18s ease !important;
                                        }
                                        [class*="st-key-league_standings_cta"] [data-testid="stButton"] > button > div {
                                          display:flex !important; flex:0 1 auto !important; align-items:center !important;
                                          justify-content:flex-start !important; width:auto !important; min-width:0 !important;
                                          margin:0 !important; padding:0 !important; gap:10px !important;
                                        }
                                        [class*="st-key-league_standings_cta"] [data-testid="stButton"] > button p {
                                          display:block !important; visibility:visible !important; opacity:1 !important;
                                          margin:0 !important; padding:0 !important; color:inherit !important;
                                          -webkit-text-fill-color:inherit !important; font-size:inherit !important;
                                          font-weight:900 !important; letter-spacing:.035em !important;
                                          line-height:1 !important; white-space:nowrap !important; text-align:left !important;
                                        }
                                        [class*="st-key-league_standings_cta"] [data-testid="stButton"] > button [data-testid="stIconMaterial"],
                                        [class*="st-key-league_standings_cta"] [data-testid="stButton"] > button svg {
                                          display:block !important; visibility:visible !important; opacity:1 !important;
                                          color:#E8CC70 !important; fill:currentColor !important;
                                          width:21px !important; height:21px !important; font-size:21px !important; flex:0 0 21px !important;
                                        }
                                        [class*="st-key-league_standings_cta"] [data-testid="stButton"] > button::after {
                                          content:"›" !important; display:block !important; margin-left:auto !important;
                                          color:#E8CC70 !important; font-size:1.65rem !important; font-weight:500 !important;
                                          line-height:.8 !important;
                                        }
                                        [class*="st-key-league_standings_cta"] [data-testid="stButton"] > button:hover {
                                          border-color:#E8CC70 !important; color:#FFF0A5 !important; -webkit-text-fill-color:#FFF0A5 !important;
                                          background:linear-gradient(110deg,#3B3219 0%,#22242A 72%) !important;
                                          box-shadow:0 0 17px rgba(232,204,112,.15) !important; transform:translateY(-1px) !important;
                                        }
                                        @media(max-width:640px) {
                                          [class*="st-key-league_standings_cta"] { margin:10px 0 14px !important; }
                                          [class*="st-key-league_standings_cta"] [data-testid="stButton"] > button {
                                            height:50px !important; min-height:50px !important; max-height:50px !important;
                                            padding:0 13px !important; font-size:.94rem !important; border-radius:11px !important;
                                          }
                                          [class*="st-key-league_standings_cta"] [data-testid="stButton"] > button [data-testid="stIconMaterial"],
                                          [class*="st-key-league_standings_cta"] [data-testid="stButton"] > button svg {
                                            width:19px !important; height:19px !important; font-size:19px !important; flex-basis:19px !important;
                                          }
                                        }
                                        </style>
                                        """, unsafe_allow_html=True)
                                        with st.container(key="league_standings_cta"):
                                            if st.button("Ver clasificación", key=f"open_standings_{match_id}", icon=":material/emoji_events:", use_container_width=True, type="secondary"):
                                                st.session_state["main_fixture_tool"] = {"fixture_id": str(match_id), "tool": "standings"}
                                                st.rerun()
                                        # FORMACIONES: consulta bajo demanda para no consumir cuota en cada partido.
                                        _lineups_toggle_key = f"show_lineups_{match_id}"
                                        _lineups_open = bool(st.session_state.get(_lineups_toggle_key, False))
                                        if st.button(
                                            "Ocultar formaciones" if _lineups_open else "Ver formaciones",
                                            key=f"toggle_lineups_{match_id}",
                                            icon=":material/groups:",
                                            type="secondary",
                                            use_container_width=True,
                                        ):
                                            st.session_state[_lineups_toggle_key] = not _lineups_open
                                            st.rerun()

                                        if st.session_state.get(_lineups_toggle_key, False):
                                            try:
                                                _lineups_payload = api_get("fixtures/lineups", {"fixture": match_id})
                                                _lineups_response = _lineups_payload.get("response") or []
                                                if not _lineups_response:
                                                    st.info(
                                                        "Las alineaciones todavía no están disponibles. "
                                                        "La API las mostrará cuando la competición las publique; "
                                                        "vuelve a consultar más cerca del inicio del partido."
                                                    )
                                                else:
                                                    _lineups_by_team = {
                                                        str((item.get("team") or {}).get("id")): item
                                                        for item in _lineups_response
                                                    }
                                                    _lineup_tabs = st.tabs([
                                                        str(match_home.get("name") or "LOCAL").upper(),
                                                        str(match_away.get("name") or "VISITANTE").upper(),
                                                    ])
                                                    for _lineup_tab, _team in zip(_lineup_tabs, (match_home, match_away)):
                                                        with _lineup_tab:
                                                            _team_id_key = str(_team.get("id"))
                                                            _team_lineup = _lineups_by_team.get(_team_id_key) or {}
                                                            _team_name_lineup = str(_team.get("name") or "Equipo")
                                                            _team_logo_lineup = str(_team.get("logo") or "")
                                                            _formation = str(_team_lineup.get("formation") or "N/D")
                                                            _coach = _team_lineup.get("coach") or {}
                                                            _coach_name = str(_coach.get("name") or "Por confirmar")
                                                            _starting_xi = _team_lineup.get("startXI") or []
                                                            _substitutes = _team_lineup.get("substitutes") or []
                                                            st.markdown(
                                                                f'<div class="fl-lineup-head">'
                                                                f'<div class="fl-lineup-team">'
                                                                f'<img src="{html.escape(_team_logo_lineup, quote=True)}" alt="" />'
                                                                f'<div><div class="fl-lineup-team-name">{html.escape(_team_name_lineup)}</div>'
                                                                f'<div class="fl-lineup-meta">SISTEMA TÁCTICO · {html.escape(_formation)}</div></div>'
                                                                f'</div><div class="fl-lineup-coach">ENTRENADOR<br><b>{html.escape(_coach_name)}</b></div></div>',
                                                                unsafe_allow_html=True,
                                                            )
                                                            if _starting_xi:
                                                                _players = []
                                                                for _entry in _starting_xi:
                                                                    _player = _entry.get("player") or {}
                                                                    _grid = str(_player.get("grid") or "").strip()
                                                                    _row = _col = None
                                                                    if ":" in _grid:
                                                                        try:
                                                                            _row, _col = [int(_part) for _part in _grid.split(":", 1)]
                                                                        except (TypeError, ValueError):
                                                                            _row = _col = None
                                                                    _players.append({
                                                                        "name": str(_player.get("name") or "Jugador"),
                                                                        "number": _player.get("number"),
                                                                        "pos": str(_player.get("pos") or ""),
                                                                        "row": _row,
                                                                        "col": _col,
                                                                    })
                                                                _grid_rows = [p["row"] for p in _players if p["row"] is not None]
                                                                _grid_cols = [p["col"] for p in _players if p["col"] is not None]
                                                                _max_row = max(_grid_rows) if _grid_rows else 4
                                                                _max_col = max(_grid_cols) if _grid_cols else 5
                                                                _fallback_groups = {"G": [], "D": [], "M": [], "F": []}
                                                                for _p in _players:
                                                                    if _p["row"] is None or _p["col"] is None:
                                                                        _fallback_groups.get(_p["pos"].upper()[:1], _fallback_groups["M"]).append(_p)
                                                                for _p in _players:
                                                                    if _p["row"] is None or _p["col"] is None:
                                                                        _group = _p["pos"].upper()[:1]
                                                                        _row_map = {"G": 1, "D": 2, "M": 3, "F": 4}
                                                                        _p["row"] = _row_map.get(_group, 3)
                                                                        _same_row = [q for q in _players if q["row"] == _p["row"]]
                                                                        _p["col"] = _same_row.index(_p) + 1
                                                                _max_row = max([p["row"] for p in _players] or [4])
                                                                _max_col = max([p["col"] for p in _players] or [5])
                                                                _markers = []
                                                                for _p in _players:
                                                                    _left = max(8, min(92, ((_p["col"] - 0.5) / max(1, _max_col)) * 100))
                                                                    _top = max(8, min(92, ((_max_row - _p["row"] + 0.5) / max(1, _max_row)) * 100))
                                                                    _number = "—" if _p["number"] is None else str(_p["number"])
                                                                    _markers.append(
                                                                        f'<div class="fl-player" style="left:{_left:.1f}%;top:{_top:.1f}%">'
                                                                        f'<span class="fl-player-shirt">{html.escape(_number)}</span>'
                                                                        f'<span class="fl-player-name">{html.escape(_p["name"])}</span></div>'
                                                                    )
                                                                st.markdown(
                                                                    '<style>'
                                                                    '.fl-lineup-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin:8px 0 14px;padding:12px 14px;border:1px solid rgba(226,190,75,.45);border-radius:14px;background:linear-gradient(120deg,rgba(232,197,83,.13),rgba(20,25,37,.08));}'
                                                                    '.fl-lineup-team{display:flex;align-items:center;gap:11px;min-width:0;}'
                                                                    '.fl-lineup-team img{width:42px;height:42px;object-fit:contain;}'
                                                                    '.fl-lineup-team-name{font-weight:900;font-size:1rem;color:var(--text-color);}'
                                                                    '.fl-lineup-meta{font-size:.7rem;letter-spacing:.1em;font-weight:800;color:#B18A22;margin-top:3px;}'
                                                                    '.fl-lineup-coach{text-align:right;font-size:.65rem;letter-spacing:.08em;color:var(--text-color);opacity:.72;}'
                                                                    '.fl-lineup-coach b{font-size:.82rem;letter-spacing:0;color:var(--text-color);opacity:1;}'
                                                                    '.fl-lineup-pitch{position:relative;width:100%;max-width:510px;height:570px;margin:0 auto 16px;overflow:hidden;border:2px solid #D9C16B;border-radius:15px;background:repeating-linear-gradient(0deg,#176B38 0px,#176B38 72px,#1B773E 72px,#1B773E 144px);box-shadow:0 8px 22px rgba(0,0,0,.18);}'
                                                                    '.fl-lineup-pitch:before{content:"";position:absolute;inset:10px;border:1.5px solid rgba(255,255,255,.72);border-radius:5px;}'
                                                                    '.fl-lineup-pitch:after{content:"";position:absolute;left:10px;right:10px;top:50%;border-top:1.5px solid rgba(255,255,255,.65);}'
                                                                    '.fl-pitch-center{position:absolute;left:50%;top:50%;width:112px;height:112px;transform:translate(-50%,-50%);border:1.5px solid rgba(255,255,255,.7);border-radius:50%;}'
                                                                    '.fl-pitch-box-top,.fl-pitch-box-bottom{position:absolute;left:25%;width:50%;height:14%;border:1.5px solid rgba(255,255,255,.7);}'
                                                                    '.fl-pitch-box-top{top:10px;border-top:0;}.fl-pitch-box-bottom{bottom:10px;border-bottom:0;}'
                                                                    '.fl-player{position:absolute;z-index:2;display:flex;flex-direction:column;align-items:center;gap:3px;width:76px;transform:translate(-50%,-50%);text-align:center;}'
                                                                    '.fl-player-shirt{display:flex;align-items:center;justify-content:center;width:31px;height:31px;border:2px solid #F6D76A;border-radius:50%;background:linear-gradient(145deg,#242A36,#090D15);color:#FFE27A;font-size:.76rem;font-weight:950;box-shadow:0 2px 9px rgba(0,0,0,.4);}'
                                                                    '.fl-player-name{display:block;max-width:76px;padding:2px 4px;border-radius:5px;background:rgba(7,12,18,.78);color:#fff;font-size:.62rem;font-weight:750;line-height:1.15;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-shadow:0 1px 2px #000;}'
                                                                    '.fl-bench-title{margin:14px 0 8px;color:#B18A22;font-weight:950;letter-spacing:.09em;font-size:.82rem;}'
                                                                    '.fl-bench-list{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:10px;}'
                                                                    '.fl-bench-player{display:flex;align-items:center;gap:6px;padding:6px 9px;border:1px solid rgba(190,158,65,.35);border-radius:9px;background:rgba(180,145,45,.08);color:var(--text-color);font-size:.76rem;font-weight:650;}'
                                                                    '.fl-bench-number{color:#B18A22;font-weight:950;}'
                                                                    '@media(max-width:640px){.fl-lineup-pitch{height:500px;max-width:100%;}.fl-player{width:64px;}.fl-player-name{max-width:64px;font-size:.56rem;}.fl-player-shirt{width:28px;height:28px;font-size:.7rem;}.fl-pitch-center{width:86px;height:86px;}}'
                                                                    '</style>'
                                                                    + '<div class="fl-lineup-pitch"><div class="fl-pitch-center"></div>'
                                                                    + '<div class="fl-pitch-box-top"></div><div class="fl-pitch-box-bottom"></div>'
                                                                    + ''.join(_markers) + '</div>',
                                                                    unsafe_allow_html=True,
                                                                )
                                                            else:
                                                                st.info("La API todavía no ha publicado los titulares de este equipo.")
                                                            _bench_html = []
                                                            for _entry in _substitutes:
                                                                _player = _entry.get("player") or {}
                                                                _number = "—" if _player.get("number") is None else str(_player.get("number"))
                                                                _name = str(_player.get("name") or "Jugador")
                                                                _bench_html.append(
                                                                    f'<span class="fl-bench-player"><b class="fl-bench-number">{html.escape(_number)}</b>'
                                                                    f'{html.escape(_name)}</span>'
                                                                )
                                                            st.markdown(
                                                                '<div class="fl-bench-title">SUPLENTES</div><div class="fl-bench-list">'
                                                                + (''.join(_bench_html) if _bench_html else '<span class="fl-bench-player">Suplentes por confirmar</span>')
                                                                + '</div>',
                                                                unsafe_allow_html=True,
                                                            )
                                            except Exception as _lineups_exc:
                                                st.warning(f"No se pudieron consultar las formaciones: {_lineups_exc}")

                                    elif tool_name == "standings":
                                        _standings_league = match.get("league") or {}
                                        _standings_league_id = _standings_league.get("id")
                                        _standings_season = _standings_league.get("season")
                                        _standings_league_name = str(_standings_league.get("name") or "Competición")
                                        _standings_flag = str(_standings_league.get("flag") or "").strip()
                                        _standings_flag_html = (
                                            f'<img class="fl-standings-league-flag" src="{html.escape(_standings_flag, quote=True)}" alt="" loading="lazy">'
                                            if _standings_flag.startswith("https://") else
                                            '<span class="fl-standings-league-flag-emoji">🏆</span>'
                                        )
                                        st.markdown(
                                            f'<div class="fl-standings-heading">{_standings_flag_html}<span class="fl-standings-heading-title">CLASIFICACIÓN</span><span class="fl-standings-heading-divider">·</span><span class="fl-standings-heading-league">{html.escape(_standings_league_name.upper())}</span></div>',
                                            unsafe_allow_html=True,
                                        )
                                        st.markdown(
                                            '<style>'
                                            '.fl-standings-heading{display:flex;align-items:center;gap:10px;flex-wrap:wrap;width:100%;max-width:100%;min-width:0;box-sizing:border-box;margin:8px 0 12px;padding:13px 15px;border:1px solid rgba(250,204,21,.3);border-left:3px solid #FACC15;border-radius:12px;background:linear-gradient(100deg,rgba(250,204,21,.13),rgba(250,204,21,.025));color:#FFF1A8;font-weight:950;letter-spacing:.045em;line-height:1.3;text-shadow:0 0 15px rgba(250,204,21,.18);}'
                                            '.fl-standings-league-flag{display:inline-block;width:27px;height:19px;flex:0 0 27px;object-fit:cover;border-radius:3px;box-shadow:0 2px 7px rgba(0,0,0,.35);}'
                                            '.fl-standings-league-flag-emoji{display:inline-flex;align-items:center;justify-content:center;width:27px;height:27px;flex:0 0 27px;font-size:23px;}'
                                            '.fl-standings-heading-title{color:#FACC15;font-size:1rem;}'
                                            '.fl-standings-heading-divider{color:#8B783E;}'
                                            '.fl-standings-heading-league{min-width:0;overflow-wrap:anywhere;color:#FFF0B0;font-size:1rem;}'
                                            'section.main > div.block-container:has(.fl-standings-heading){width:100%!important;max-width:1120px!important;box-sizing:border-box!important;}'
                                            '@media(max-width:640px){section.main > div.block-container:has(.fl-standings-heading){width:100%!important;max-width:100vw!important;padding-left:12px!important;padding-right:12px!important;padding-top:12px!important;overflow-x:hidden!important;box-sizing:border-box!important;}section.main > div.block-container:has(.fl-standings-heading) [data-testid="stVerticalBlock"]{min-width:0!important;max-width:100%!important;box-sizing:border-box!important;}.fl-standings-heading{gap:7px;margin:4px 0 10px;padding:11px 10px;border-radius:10px;}.fl-standings-heading-title,.fl-standings-heading-league{font-size:.84rem;letter-spacing:.025em;}.fl-standings-league-flag{width:24px;height:17px;flex-basis:24px;}}'
                                            '</style>',
                                            unsafe_allow_html=True,
                                        )
                                        st.markdown(
                                            f'<div style="margin:8px 0 16px;color:#AEB4C0;font-size:.9rem;">Tabla oficial de la competición · Temporada {html.escape(str(_standings_season or "actual"))}</div>',
                                            unsafe_allow_html=True,
                                        )
                                        if not _standings_league_id or not _standings_season:
                                            st.info("La API no proporcionó el identificador o la temporada de esta competición. No podemos consultar una tabla fiable.")
                                        else:
                                            _standings_cache_key = f"standings-v1-{_standings_league_id}-{_standings_season}"
                                            if _standings_cache_key not in st.session_state.setdefault("standings_cache", {}):
                                                try:
                                                    _standings_payload = api_get(
                                                        "standings",
                                                        {"league": int(_standings_league_id), "season": int(_standings_season)},
                                                    )
                                                    st.session_state.standings_cache[_standings_cache_key] = {
                                                        "response": _standings_payload.get("response") or [],
                                                        "error": None,
                                                    }
                                                except Exception as _standings_exc:
                                                    st.session_state.standings_cache[_standings_cache_key] = {
                                                        "response": [],
                                                        "error": str(_standings_exc),
                                                    }
                                            _standings_result = st.session_state.get("standings_cache", {}).get(_standings_cache_key) or {}
                                            if _standings_result.get("error"):
                                                st.warning(f"No se pudo consultar la clasificación: {_standings_result['error']}")
                                            else:
                                                _standings_response = _standings_result.get("response") or []
                                                _standings_league_data = ((_standings_response[0] or {}).get("league") or {}) if _standings_response else {}
                                                _standings_groups = _standings_league_data.get("standings") or []
                                                if not _standings_groups:
                                                    st.info("Esta competición no ofrece una tabla de posiciones tradicional. Puede tratarse de una copa, fase eliminatoria o torneo sin clasificación de liga.")
                                                else:
                                                    _selected_home_id = str(match_home_id or "")
                                                    _selected_away_id = str(match_away_id or "")
                                                    for _group_index, _group_rows in enumerate(_standings_groups):
                                                        if not isinstance(_group_rows, list) or not _group_rows:
                                                            continue
                                                        _group_name = str((_group_rows[0] or {}).get("group") or "")
                                                        if len(_standings_groups) > 1 or _group_name:
                                                            st.markdown(
                                                                f'<div style="margin:18px 0 9px;color:#F4D978;font-weight:850;letter-spacing:.08em;text-transform:uppercase;">{html.escape(_group_name or f"Grupo {_group_index + 1}")}</div>',
                                                                unsafe_allow_html=True,
                                                            )
                                                        _table_rows_html = []
                                                        for _standing in _group_rows:
                                                            _team_info = _standing.get("team") or {}
                                                            _team_id = str(_team_info.get("id") or "")
                                                            _team_name = html.escape(str(_team_info.get("name") or "Equipo"))
                                                            _team_logo = str(_team_info.get("logo") or "").strip()
                                                            _logo_html = f'<img src="{html.escape(_team_logo, quote=True)}" alt="" loading="lazy">' if _team_logo.startswith("https://") else ""
                                                            _all_stats = _standing.get("all") or {}
                                                            _goals_stats = _all_stats.get("goals") or {}
                                                            _played = _all_stats.get("played", 0)
                                                            _wins = _all_stats.get("win", 0)
                                                            _draws = _all_stats.get("draw", 0)
                                                            _losses = _all_stats.get("lose", 0)
                                                            _goals_for = _goals_stats.get("for", 0)
                                                            _goals_against = _goals_stats.get("against", 0)
                                                            _goal_diff = _standing.get("goalsDiff", 0)
                                                            _points = _standing.get("points", 0)
                                                            _raw_form = str(_standing.get("form") or "")
                                                            _form_items = []
                                                            for _result in _raw_form.replace(" ", "").upper():
                                                                _result_label = {"W": "G", "L": "D", "D": "E", "G": "G", "E": "E"}.get(_result)
                                                                if _result_label:
                                                                    _form_items.append(f'<span class="fl-form-chip fl-form-{_result_label.lower()}">{_result_label}</span>')
                                                            _form_html = "".join(_form_items) or '<span class="fl-form-empty">—</span>'
                                                            if _team_id == _selected_home_id:
                                                                _focus_class = " is-home-focus"
                                                            elif _team_id == _selected_away_id:
                                                                _focus_class = " is-away-focus"
                                                            else:
                                                                _focus_class = ""
                                                            _table_rows_html.append(
                                                                f'<tr class="{_focus_class.strip()}">'
                                                                f'<td class="fl-standings-rank"><span>{html.escape(str(_standing.get("rank") or "—"))}</span></td>'
                                                                f'<td class="fl-standings-team">{_logo_html}<span>{_team_name}</span></td>'
                                                                f'<td>{html.escape(str(_played))}</td><td class="fl-stat-win">{html.escape(str(_wins))}</td>'
                                                                f'<td class="fl-stat-draw">{html.escape(str(_draws))}</td><td class="fl-stat-loss">{html.escape(str(_losses))}</td>'
                                                                f'<td>{html.escape(str(_goals_for))}</td><td>{html.escape(str(_goals_against))}</td>'
                                                                f'<td class="fl-standings-diff">{html.escape(str(_goal_diff))}</td><td class="fl-standings-points">{html.escape(str(_points))}</td>'
                                                                f'<td class="fl-standings-form">{_form_html}</td></tr>'
                                                            )
                                                        _standings_table_html = (
                                                            '<div class="fl-standings-scroll"><table class="fl-standings-table">'
                                                            '<thead><tr><th>POS</th><th>EQUIPO</th><th>PJ</th><th class="fl-head-win">G</th><th class="fl-head-draw">E</th><th class="fl-head-loss">D</th><th>GF</th><th>GC</th><th>DG</th><th class="fl-head-points">PTS</th><th>FORMA</th></tr></thead>'
                                                            f'<tbody>{"".join(_table_rows_html)}</tbody></table></div>'
                                                        )
                                                        st.markdown(
                                                            '<style>'
                                                            '.fl-standings-scroll{width:100%;max-width:100%;overflow-x:auto;overscroll-behavior-x:contain;border:1px solid rgba(212,175,55,.48);border-radius:16px;background:linear-gradient(145deg,#151A22,#0D1118);-webkit-overflow-scrolling:touch;margin:10px 0 16px;box-shadow:0 12px 28px rgba(0,0,0,.22),inset 0 1px 0 rgba(255,255,255,.035);scrollbar-width:thin;scrollbar-color:#80651C #171B22;}'
                                                            '.fl-standings-table{width:100%;min-width:730px;border-collapse:separate;border-spacing:0;color:#E8EAF0;font-size:12px;font-variant-numeric:tabular-nums;}'
                                                            '.fl-standings-table th{padding:13px 10px;text-align:center;color:#E8D48A;background:linear-gradient(180deg,#292719,#1D1D19);font-size:10px;font-weight:900;letter-spacing:.1em;white-space:nowrap;border-bottom:1px solid rgba(218,183,77,.48);}'
                                                            '.fl-standings-table td{height:51px;padding:10px;text-align:center;white-space:nowrap;border-bottom:1px solid rgba(255,255,255,.065);background:rgba(255,255,255,.012);}'
                                                            '.fl-standings-table tbody tr:nth-child(even) td{background:rgba(255,255,255,.035);}.fl-standings-table tbody tr:hover td{background:rgba(250,204,21,.065);}.fl-standings-table tr:last-child td{border-bottom:0;}'
                                                            '.fl-standings-table .fl-standings-rank{width:48px;color:#C9B878;font-weight:900;}.fl-standings-table .fl-standings-rank span{display:inline-flex;align-items:center;justify-content:center;min-width:27px;height:27px;border-radius:9px;background:linear-gradient(145deg,#292B31,#191C22);border:1px solid rgba(255,255,255,.09);}'
                                                            '.fl-standings-table .fl-standings-team{text-align:left;min-width:174px;font-weight:800;}.fl-standings-table .fl-standings-team img{width:25px;height:25px;object-fit:contain;vertical-align:middle;margin-right:10px;filter:drop-shadow(0 2px 3px rgba(0,0,0,.35));}'
                                                            '.fl-standings-table .fl-standings-points{color:#FFE071;font-weight:950;font-size:14px;background:rgba(250,204,21,.075);}.fl-standings-table .fl-standings-diff{font-weight:850;color:#CBD5E1;}'
                                                            '.fl-standings-table .fl-stat-win{color:#FACC15;font-weight:900;background:rgba(250,204,21,.085);}.fl-standings-table .fl-stat-draw{color:#D1D5DB;font-weight:850;background:rgba(156,163,175,.09);}.fl-standings-table .fl-stat-loss{color:#FF646B;font-weight:900;background:rgba(239,68,68,.09);}'
                                                            '.fl-standings-table th.fl-head-win{color:#17130A;background:linear-gradient(180deg,#FFE56B,#EAB308);}.fl-standings-table th.fl-head-draw{color:#FFF;background:linear-gradient(180deg,#68717D,#3F4650);}.fl-standings-table th.fl-head-loss{color:#FFF;background:linear-gradient(180deg,#F04452,#991B2B);}.fl-standings-table th.fl-head-points{color:#FFE27A;background:linear-gradient(180deg,#3A3018,#252014);}'
                                                            '.fl-standings-table .fl-standings-form{min-width:112px;}.fl-form-chip{display:inline-flex;align-items:center;justify-content:center;width:20px;height:22px;margin:0 2px;border-radius:6px;font-size:10px;font-weight:950;box-shadow:inset 0 1px 0 rgba(255,255,255,.16);}'
                                                            '.fl-form-g{color:#17130A;background:linear-gradient(145deg,#FFE66D,#EAB308);}.fl-form-e{color:#F8FAFC;background:linear-gradient(145deg,#727B87,#4B5563);}.fl-form-d{color:#FFF;background:linear-gradient(145deg,#F04452,#991B2B);}.fl-form-empty{color:#7D8490;}'
                                                            '.fl-standings-table tr.is-home-focus td{background:rgba(14,165,233,.12)!important;border-top:1px solid rgba(56,189,248,.3);border-bottom:1px solid rgba(56,189,248,.3);}.fl-standings-table tr.is-home-focus .fl-standings-rank span{color:#E0F2FE;background:linear-gradient(145deg,#075985,#0C4A6E);border-color:#38BDF8;}.fl-standings-table tr.is-home-focus .fl-standings-team span{color:#7DD3FC;}'
                                                            '.fl-standings-table tr.is-away-focus td{background:rgba(250,204,21,.12)!important;border-top:1px solid rgba(250,204,21,.3);border-bottom:1px solid rgba(250,204,21,.3);}.fl-standings-table tr.is-away-focus .fl-standings-rank span{color:#FFF2B2;background:linear-gradient(145deg,#8A6508,#5B4308);border-color:#FACC15;}.fl-standings-table tr.is-away-focus .fl-standings-team span{color:#FFE477;}'
                                                            '@media(max-width:640px){.fl-standings-table{min-width:730px;font-size:11px;}.fl-standings-table th{padding:12px 8px;font-size:9px;}.fl-standings-table td{height:47px;padding:9px 8px;}.fl-standings-table .fl-standings-team{min-width:158px;}.fl-standings-table .fl-standings-team img{width:22px;height:22px;margin-right:8px;}.fl-form-chip{width:18px;height:20px;margin:0 1px;}}'
                                                            '</style>',
                                                            unsafe_allow_html=True,
                                                        )
                                                        st.markdown(_standings_table_html, unsafe_allow_html=True)
                                                    st.caption("Local en azul y visitante en dorado. G = ganados, E = empates y D = derrotas; la columna FORMA usa las mismas letras y colores. Desliza horizontalmente para ver todas las columnas en el celular.")
                                    elif tool_name == "tracker":
                                        if st.session_state.get("fixture_mode", "live") == "upcoming":
                                            st.info("El Tracker en vivo estará disponible cuando comience este partido. Puedes consultar desde ahora Stats, Goles, Córners y H2H.")
                                        else:
                                            # LIVE TRACKER: animación ilustrativa guiada por posesión; no representa coordenadas reales.
                                            _tracker_id = str(match_id)
                                            if _tracker_id not in st.session_state.stats_cache or _tracker_id in st.session_state.get("stats_errors", {}):
                                                try:
                                                    _tracker_payload = api_get("fixtures/statistics", {"fixture": match_id})
                                                    st.session_state.stats_cache[_tracker_id] = _tracker_payload.get("response") or []
                                                    st.session_state.setdefault("stats_errors", {}).pop(_tracker_id, None)
                                                except Exception as _tracker_exc:
                                                    st.session_state.stats_cache[_tracker_id] = []
                                                    st.session_state.setdefault("stats_errors", {})[_tracker_id] = str(_tracker_exc)
                                            _tracker_data = st.session_state.stats_cache.get(_tracker_id, [])
                                            _tracker_home_stats = {entry.get("type"): entry.get("value") for entry in ((_tracker_data[0].get("statistics") or []) if len(_tracker_data) > 0 else [])}
                                            _tracker_away_stats = {entry.get("type"): entry.get("value") for entry in ((_tracker_data[1].get("statistics") or []) if len(_tracker_data) > 1 else [])}
                                            def _tracker_num(value, fallback):
                                                try:
                                                    return float(str(value).replace("%", "").replace(",", "."))
                                                except (TypeError, ValueError):
                                                    return fallback
                                            _tracker_hp = _tracker_num(_tracker_home_stats.get("Ball Possession"), 50.0)
                                            _tracker_ap = _tracker_num(_tracker_away_stats.get("Ball Possession"), 100.0 - _tracker_hp)
                                            _tracker_total = max(1.0, _tracker_hp + _tracker_ap)
                                            _tracker_hpct = max(0, min(100, round(_tracker_hp / _tracker_total * 100)))
                                            _tracker_apct = 100 - _tracker_hpct
                                            _tracker_minute = ((match.get("fixture") or {}).get("status") or {}).get("elapsed")
                                            _tracker_minute_label = f"{_tracker_minute}′" if _tracker_minute is not None else "EN VIVO"
                                            _tracker_home = html.escape(str(match_home.get("name") or "Local"))
                                            _tracker_away = html.escape(str(match_away.get("name") or "Visitante"))
                                            _tracker_home_logo = html.escape(str(match_home.get("logo") or ""), quote=True)
                                            _tracker_away_logo = html.escape(str(match_away.get("logo") or ""), quote=True)
                                            _tracker_home_badge = f'<img src="{_tracker_home_logo}" alt="">' if _tracker_home_logo else "⚽"
                                            _tracker_away_badge = f'<img src="{_tracker_away_logo}" alt="">' if _tracker_away_logo else "⚽"

                                            # Eventos reales de gol agrupados por equipo.
                                            _tracker_events_cache = st.session_state.setdefault("tracker_goal_events_cache", {})
                                            _tracker_events_key = str(match_id)
                                            if _tracker_events_key not in _tracker_events_cache:
                                                try:
                                                    _tracker_events_payload = api_get("fixtures/events", {"fixture": match_id})
                                                    _tracker_events_cache[_tracker_events_key] = _tracker_events_payload.get("response") or []
                                                except Exception:
                                                    _tracker_events_cache[_tracker_events_key] = []
                                            _tracker_goal_events = [ev for ev in (_tracker_events_cache.get(_tracker_events_key) or []) if str(ev.get("type") or "").casefold() == "goal" and str(ev.get("detail") or "").casefold() not in {"missed penalty", "penalty missed"}]
                                            _tracker_goal_events.sort(key=lambda ev: (int(((ev.get("time") or {}).get("elapsed")) or 0), int(((ev.get("time") or {}).get("extra")) or 0)))
                                            _tracker_home_scorers, _tracker_away_scorers = [], []
                                            for _tracker_goal in _tracker_goal_events:
                                                _tracker_goal_team_id = (_tracker_goal.get("team") or {}).get("id")
                                                _tracker_goal_time = _tracker_goal.get("time") or {}
                                                _tracker_goal_elapsed, _tracker_goal_extra = _tracker_goal_time.get("elapsed"), _tracker_goal_time.get("extra")
                                                _tracker_goal_minute = f"{_tracker_goal_elapsed}+{_tracker_goal_extra}′" if _tracker_goal_extra else f"{_tracker_goal_elapsed}′" if _tracker_goal_elapsed is not None else ""
                                                _tracker_goal_player = html.escape(str((_tracker_goal.get("player") or {}).get("name") or "Autor no disponible"))
                                                _tracker_goal_detail = str(_tracker_goal.get("detail") or "")
                                                _tracker_goal_note = " · " + html.escape(_tracker_goal_detail) if _tracker_goal_detail and _tracker_goal_detail.casefold() not in {"normal goal", "goal"} else ""
                                                _tracker_goal_line = f'<span class="fl-tracker-scorer">⚽ {_tracker_goal_player} <b>{html.escape(_tracker_goal_minute)}</b>{_tracker_goal_note}</span>'
                                                if _tracker_goal_team_id == match_home.get("id"):
                                                    _tracker_home_scorers.append(_tracker_goal_line)
                                                elif _tracker_goal_team_id == match_away.get("id"):
                                                    _tracker_away_scorers.append(_tracker_goal_line)
                                            _tracker_home_scorers_html = '<div class="fl-tracker-scorers">' + "".join(_tracker_home_scorers) + "</div>" if _tracker_home_scorers else ""
                                            _tracker_away_scorers_html = '<div class="fl-tracker-scorers">' + "".join(_tracker_away_scorers) + "</div>" if _tracker_away_scorers else ""
                                            _tracker_home_shots = _tracker_num(_tracker_home_stats.get("Total Shots"), 0)
                                            _tracker_away_shots = _tracker_num(_tracker_away_stats.get("Total Shots"), 0)
                                            _tracker_home_corners = _tracker_num(_tracker_home_stats.get("Corner Kicks"), 0)
                                            _tracker_away_corners = _tracker_num(_tracker_away_stats.get("Corner Kicks"), 0)
                                            _tracker_home_activity = min(100, round(_tracker_hpct * .55 + min(100, _tracker_home_shots * 5) * .25 + min(100, _tracker_home_corners * 12) * .20))
                                            _tracker_away_activity = min(100, round(_tracker_apct * .55 + min(100, _tracker_away_shots * 5) * .25 + min(100, _tracker_away_corners * 12) * .20))
                                            _tracker_ball_left = max(12, min(88, 50 + (_tracker_hpct - 50) * .62))
                                            _tracker_direction = "Local" if _tracker_hpct >= 50 else "Visitante"
                                            _tracker_event = "Actividad equilibrada" if abs(_tracker_hpct - 50) < 7 else f"Mayor iniciativa: {_tracker_direction}"
                                            st.markdown(
                                                f'<section class="fl-tracker-wrap">'
                                                f'<div class="fl-tracker-head"><div><div class="fl-tracker-kicker">FOOTBALL LAB · LIVE EXPERIENCE</div><div class="fl-tracker-title">LIVE TRACKER</div><div class="fl-tracker-subtitle">Dominio territorial animado · {html.escape(_tracker_minute_label)}</div></div><span class="fl-tracker-live"><i></i> EN VIVO</span></div>'
                                                f'<div class="fl-tracker-score"><div class="fl-tracker-team">{_tracker_home_badge}<strong>{_tracker_home}</strong><small>LOCAL</small>{_tracker_home_scorers_html}</div><div class="fl-tracker-score-mid"><b>{match_goals.get("home") if match_goals.get("home") is not None else "—"} – {match_goals.get("away") if match_goals.get("away") is not None else "—"}</b><small>{html.escape(_tracker_minute_label)}</small></div><div class="fl-tracker-team away">{_tracker_away_badge}<strong>{_tracker_away}</strong><small>VISITANTE</small>{_tracker_away_scorers_html}</div></div>'
                                                f'<div class="fl-tracker-possession"><div><span>{_tracker_home}</span><b>{_tracker_hpct}%</b></div><div class="fl-tracker-possession-track"><i style="width:{_tracker_hpct}%"></i></div><div><span>{_tracker_away}</span><b>{_tracker_apct}%</b></div></div>'
                                                f'<div class="fl-tracker-pitch-card"><div class="fl-tracker-pitch-label"><span>← {_tracker_home} ataca</span><span>{_tracker_away} ataca →</span></div>'
                                                f'<div class="fl-tracker-pitch"><div class="fl-tracker-pitch-mid"></div><div class="fl-tracker-circle"></div><div class="fl-tracker-box left"></div><div class="fl-tracker-box right"></div><div class="fl-tracker-goal left"></div><div class="fl-tracker-goal right"></div><div class="fl-tracker-lane lane-a"></div><div class="fl-tracker-lane lane-b"></div><div class="fl-tracker-ball" style="--ball-x:{_tracker_ball_left}%"><span>⚽</span></div><div class="fl-tracker-pulse"></div></div>'
                                                f'<div class="fl-tracker-pitch-legend"><span><i class="home"></i> Actividad local</span><span><i class="away"></i> Actividad visitante</span></div></div>'
                                                f'<div class="fl-tracker-metrics"><div><small>ACTIVIDAD LOCAL</small><b>{_tracker_home_activity}%</b><span>{_tracker_home_shots:.0f} tiros · {_tracker_home_corners:.0f} córners</span></div><div><small>ACTIVIDAD VISITANTE</small><b>{_tracker_away_activity}%</b><span>{_tracker_away_shots:.0f} tiros · {_tracker_away_corners:.0f} córners</span></div></div>'
                                                f'<div class="fl-tracker-status"><span class="fl-tracker-status-dot"></span>{html.escape(_tracker_event)}</div>'
                                                f'<div class="fl-tracker-disclaimer">DEMO ANIMADA · La posición del balón es ilustrativa y se desplaza según la posesión y la actividad estadística disponible. No es seguimiento GPS ni una ubicación real del balón. Las estadísticas pueden tener retraso o no estar disponibles.</div></section>',
                                                unsafe_allow_html=True,
                                            )
                                            st.markdown("""<style>
                                            .fl-tracker-wrap{background:linear-gradient(145deg,#171A20,#0D1015);border:1px solid #69551D;border-radius:20px;padding:clamp(13px,2.5vw,24px);color:#F8FAFC;box-shadow:0 14px 38px rgba(0,0,0,.24),inset 0 1px 0 rgba(255,255,255,.04);margin:4px 0 20px}
                                            .fl-tracker-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:16px}.fl-tracker-kicker{font-size:9px;letter-spacing:.2em;font-weight:900;color:#BFA34A}.fl-tracker-title{font-size:clamp(22px,4vw,32px);font-weight:950;letter-spacing:.04em;color:#FFE16A}.fl-tracker-subtitle{font-size:12px;color:#9CA3AF;margin-top:2px}.fl-tracker-live{font-size:10px;font-weight:900;letter-spacing:.1em;color:#FF7474;border:1px solid #71363A;background:#35191D;border-radius:99px;padding:7px 10px;white-space:nowrap}.fl-tracker-live i{display:inline-block;width:6px;height:6px;background:#FF5252;border-radius:50%;margin-right:5px;box-shadow:0 0 9px #FF5252;animation:flTrackerBlink 1s infinite}
                                            .fl-tracker-score{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:10px;padding:13px 0;border-top:1px solid #292D34;border-bottom:1px solid #292D34}.fl-tracker-team{display:flex;flex-wrap:wrap;align-items:center;gap:8px;min-width:0;font-weight:800}.fl-tracker-team img{width:30px;height:30px;object-fit:contain}.fl-tracker-team strong{font-size:clamp(10px,1.5vw,14px);overflow-wrap:anywhere}.fl-tracker-team small{font-size:8px;color:#A1A1AA;letter-spacing:.12em}.fl-tracker-team.away{justify-content:flex-end;text-align:right}.fl-tracker-score-mid{text-align:center}.fl-tracker-scorers{display:flex;flex-direction:column;gap:3px;width:100%;flex-basis:100%;font-weight:500}.fl-tracker-scorer{font-size:10px;line-height:1.3;color:#D1D5DB;overflow-wrap:anywhere}.fl-tracker-scorer b{color:#FFE16A;font-weight:800;white-space:nowrap}.fl-tracker-team.away .fl-tracker-scorers{align-items:flex-end}.fl-tracker-score-mid b{font-size:clamp(19px,3vw,26px);color:#FFE16A;white-space:nowrap}.fl-tracker-score-mid small{display:block;color:#A1A1AA;font-size:10px}
                                            .fl-tracker-possession{display:grid;grid-template-columns:1fr 1fr;gap:7px 14px;margin:17px 0}.fl-tracker-possession>div:not(.fl-tracker-possession-track){display:flex;justify-content:space-between;gap:8px;font-size:11px;color:#D1D5DB}.fl-tracker-possession b{color:#FFE16A;font-size:15px}.fl-tracker-possession-track{grid-column:1/3;height:9px;border-radius:99px;background:#1766B6;overflow:hidden}.fl-tracker-possession-track i{display:block;height:100%;background:linear-gradient(90deg,#FF3D4F,#FF9A62);border-radius:99px;transition:width .8s ease}
                                            .fl-tracker-pitch-card{border:1px solid #343A42;border-radius:15px;background:#101B17;padding:10px}.fl-tracker-pitch-label,.fl-tracker-pitch-legend{display:flex;justify-content:space-between;gap:8px;color:#E5C85B;font-size:10px;font-weight:800;margin:2px 3px 9px}.fl-tracker-pitch{position:relative;width:100%;aspect-ratio:1.72/1;overflow:hidden;border:1.5px solid rgba(231,240,230,.72);border-radius:7px;background:repeating-linear-gradient(90deg,#174A35 0%,#174A35 12.5%,#1A513A 12.5%,#1A513A 25%);isolation:isolate}
                                            .fl-tracker-pitch:before,.fl-tracker-pitch:after{content:"";position:absolute;top:0;bottom:0;width:1px;background:rgba(255,255,255,.65);left:50%;z-index:1}.fl-tracker-pitch:after{top:50%;bottom:auto;left:50%;width:10px;height:10px;border:1px solid rgba(255,255,255,.65);border-radius:50%;transform:translate(-50%,-50%);background:transparent}
                                            .fl-tracker-pitch-mid{position:absolute;left:50%;top:0;bottom:0;border-left:1px solid rgba(255,255,255,.55)}.fl-tracker-circle{position:absolute;left:50%;top:50%;width:23%;aspect-ratio:1;border:1px solid rgba(255,255,255,.55);border-radius:50%;transform:translate(-50%,-50%)}
                                            .fl-tracker-box{position:absolute;top:25%;height:50%;width:16%;border:1px solid rgba(255,255,255,.58)}.fl-tracker-box.left{left:0;border-left:0}.fl-tracker-box.right{right:0;border-right:0}.fl-tracker-goal{position:absolute;top:40%;height:20%;width:2.2%;border:1px solid rgba(255,255,255,.5)}.fl-tracker-goal.left{left:-1px}.fl-tracker-goal.right{right:-1px}
                                            .fl-tracker-lane{position:absolute;top:0;bottom:0;width:38%;filter:blur(19px);opacity:.52;z-index:0;animation:flTrackerGlow 5s ease-in-out infinite alternate}.fl-tracker-lane.lane-a{left:0;background:radial-gradient(ellipse at 65% 50%,rgba(255,55,72,.85),transparent 68%)}.fl-tracker-lane.lane-b{right:0;background:radial-gradient(ellipse at 35% 50%,rgba(34,139,255,.9),transparent 68%);animation-delay:-2.5s}
                                            .fl-tracker-ball{position:absolute;z-index:4;left:var(--ball-x);top:50%;transform:translate(-50%,-50%);animation:flTrackerBall 4.5s ease-in-out infinite alternate;filter:drop-shadow(0 0 9px rgba(255,255,255,.9))}.fl-tracker-ball span{display:flex;align-items:center;justify-content:center;width:34px;height:34px;border-radius:50%;background:rgba(255,255,255,.96);font-size:23px;box-shadow:0 0 0 5px rgba(255,255,255,.12),0 0 22px rgba(255,255,255,.48)}
                                            .fl-tracker-pulse{position:absolute;z-index:2;left:var(--ball-x);top:50%;width:55px;height:55px;border:1px solid rgba(255,255,255,.55);border-radius:50%;transform:translate(-50%,-50%);animation:flTrackerPulse 2s ease-out infinite}
                                            .fl-tracker-pitch-legend{margin:9px 3px 1px;color:#BFC7C2;font-weight:600}.fl-tracker-pitch-legend i{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px}.fl-tracker-pitch-legend i.home{background:#FF5364}.fl-tracker-pitch-legend i.away{background:#269BFF}
                                            .fl-tracker-metrics{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:12px}.fl-tracker-metrics>div{border:1px solid #343A42;border-radius:12px;padding:12px;background:#141920;min-width:0}.fl-tracker-metrics small{display:block;color:#A6AAB2;font-size:9px;letter-spacing:.1em;font-weight:850}.fl-tracker-metrics b{display:block;color:#FFE16A;font-size:23px;margin:4px 0}.fl-tracker-metrics span{display:block;color:#C4C9D1;font-size:10px}.fl-tracker-status{margin-top:12px;padding:11px 13px;border-radius:10px;background:#1B2027;color:#F4D66E;font-weight:750;font-size:12px}.fl-tracker-status-dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:#FACC15;margin-right:8px;box-shadow:0 0 9px #FACC15}.fl-tracker-disclaimer{margin-top:11px;color:#8F98A6;font-size:9px;line-height:1.5;letter-spacing:.02em}
                                            @keyframes flTrackerBall{0%{left:calc(var(--ball-x) - 8%);top:43%}50%{top:58%}100%{left:calc(var(--ball-x) + 8%);top:48%}}@keyframes flTrackerGlow{from{opacity:.25}to{opacity:.72}}@keyframes flTrackerPulse{0%{opacity:.75;transform:translate(-50%,-50%) scale(.45)}100%{opacity:0;transform:translate(-50%,-50%) scale(1.8)}}@keyframes flTrackerBlink{50%{opacity:.35}}
                                            @media(max-width:640px){.fl-tracker-wrap{padding:12px;border-radius:15px}.fl-tracker-team{flex-wrap:wrap;gap:4px}.fl-tracker-team img{width:24px;height:24px}.fl-tracker-team small{display:none}.fl-tracker-pitch-label{font-size:9px}.fl-tracker-ball span{width:29px;height:29px;font-size:20px}.fl-tracker-metrics{gap:7px}.fl-tracker-metrics>div{padding:9px}.fl-tracker-metrics b{font-size:19px}.fl-tracker-disclaimer{font-size:8px}}
                                            @media(prefers-reduced-motion:reduce){.fl-tracker-ball,.fl-tracker-pulse,.fl-tracker-lane,.fl-tracker-live i{animation:none!important}}
                                            </style>""", unsafe_allow_html=True)
                                    elif tool_name == "h2h":
                                        _match_league = match.get("league") or {}
                                        h2h_key = f"h2h-v3-home-{match_home_id}-{match_away_id}-{_match_league.get('id') or 'all'}"
                                        if "h2h_cache" not in st.session_state:
                                            st.session_state.h2h_cache = {}
                                        if h2h_key not in st.session_state.h2h_cache:
                                            try:
                                                _h2h_payload = api_get("fixtures/headtohead", {"h2h": f"{match_home_id}-{match_away_id}", "last": 50})
                                                _all_h2h_matches = _h2h_payload.get("response") or []
                                                _finished_h2h = [past for past in _all_h2h_matches if ((past.get("fixture") or {}).get("status") or {}).get("short") in {"FT", "AET", "PEN"}]
                                                _same_home_h2h = [past for past in _finished_h2h if str((((past.get("teams") or {}).get("home") or {}).get("id"))) == str(match_home_id)]
                                                _same_home_h2h.sort(key=lambda past: ((past.get("fixture") or {}).get("date") or ""), reverse=True)
                                                _same_league_home_h2h = [past for past in _same_home_h2h if (past.get("league") or {}).get("id") == _match_league.get("id")] if _match_league.get("id") else _same_home_h2h
                                                _selected_h2h = _same_league_home_h2h[:10]
                                                if len(_selected_h2h) < 10:
                                                    _selected_ids = {(past.get("fixture") or {}).get("id") for past in _selected_h2h}
                                                    _extras = [past for past in _same_home_h2h if (past.get("fixture") or {}).get("id") not in _selected_ids]
                                                    _selected_h2h.extend(_extras[:10-len(_selected_h2h)])
                                                st.session_state.h2h_cache[h2h_key] = {"matches": _selected_h2h[:10], "scope": "league" if _selected_h2h and all((past.get("league") or {}).get("id") == _match_league.get("id") for past in _selected_h2h) else "home_all"}
                                            except Exception as _h2h_exc:
                                                st.session_state.h2h_cache[h2h_key] = {"error": str(_h2h_exc)}
                                        h2h_data = st.session_state.get("h2h_cache", {}).get(h2h_key)
                                        if isinstance(h2h_data, dict) and isinstance(h2h_data.get("matches"), list):
                                            _h2h_matches_to_save = h2h_data["matches"]
                                            persist_analysis_snapshot(
                                                match_id, "h2h",
                                                {"home": match_home_name, "away": match_away_name, "minute": match_minute,
                                                 "home_score": match_goals.get("home"), "away_score": match_goals.get("away")},
                                                {"home_team_id": match_home_id, "away_team_id": match_away_id, "requested_last": 10},
                                                {"matches": _h2h_matches_to_save, "matches_returned": len(_h2h_matches_to_save),
                                                 "scope": h2h_data.get("scope")},
                                            )
                                        st.markdown('<div class="h2h-page-kicker">HISTORIAL <span>·</span> ENFRENTAMIENTOS DIRECTOS</div>', unsafe_allow_html=True)
                                        if isinstance(h2h_data, dict) and h2h_data.get("error"):
                                            st.warning(f"No se pudieron consultar los enfrentamientos: {h2h_data['error']}")
                                        elif isinstance(h2h_data, dict) and h2h_data.get("matches"):
                                            h2h_matches = h2h_data["matches"]
                                            if h2h_data.get("scope") == "league":
                                                league_name_safe = html.escape(str(_match_league.get("name") or "la competición actual"))
                                                st.markdown(f'<div class="h2h-description">Últimos {len(h2h_matches)} enfrentamientos finalizados de {league_name_safe}, con el equipo local actual jugando en casa.</div>', unsafe_allow_html=True)
                                            else:
                                                st.markdown(f'<div class="h2h-description">Últimos {len(h2h_matches)} enfrentamientos finalizados con el equipo local actual jugando en casa; se prioriza la misma competición y se completa con otras si hace falta.</div>', unsafe_allow_html=True)
                                            h2h_rows = []
                                            valid_goal_totals = []
                                            first_half_goal_totals = []
                                            second_half_goal_totals = []
                                            draw_count = 0
                                            both_score_count = 0
                                            home_wins_count = 0
                                            away_wins_count = 0
                                            for past in h2h_matches:
                                                pf, pt, pg = past.get("fixture") or {}, past.get("teams") or {}, past.get("goals") or {}
                                                ph, pa = pt.get("home") or {}, pt.get("away") or {}
                                                raw_date = (pf.get("date") or "")[:10]
                                                try:
                                                    date_label = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%d-%m-%y")
                                                except ValueError:
                                                    date_label = raw_date
                                                date_label = html.escape(date_label)
                                                ph_name, pa_name = html.escape(str(ph.get("name") or "Local")), html.escape(str(pa.get("name") or "Visitante"))
                                                ph_logo, pa_logo = html.escape(str(ph.get("logo") or ""), quote=True), html.escape(str(pa.get("logo") or ""), quote=True)
                                                home_goals, away_goals = pg.get("home"), pg.get("away")
                                                _past_score = past.get("score") or {}
                                                _half_score = _past_score.get("halftime") or {}
                                                _half_home, _half_away = _half_score.get("home"), _half_score.get("away")
                                                if (
                                                    isinstance(home_goals, (int, float)) and isinstance(away_goals, (int, float))
                                                    and isinstance(_half_home, (int, float)) and isinstance(_half_away, (int, float))
                                                    and 0 <= _half_home <= home_goals and 0 <= _half_away <= away_goals
                                                ):
                                                    first_half_goal_totals.append(_half_home + _half_away)
                                                    second_half_goal_totals.append((home_goals - _half_home) + (away_goals - _half_away))
                                                if isinstance(home_goals, (int, float)) and isinstance(away_goals, (int, float)):
                                                    valid_goal_totals.append(home_goals + away_goals)
                                                    if home_goals == away_goals:
                                                        draw_count += 1
                                                    elif home_goals > away_goals:
                                                        home_wins_count += 1
                                                    else:
                                                        away_wins_count += 1
                                                    if home_goals > 0 and away_goals > 0:
                                                        both_score_count += 1
                                                h2h_fixture_id = pf.get("id")
                                                _h2h_result_code = "E"
                                                if isinstance(home_goals, (int, float)) and isinstance(away_goals, (int, float)):
                                                    if home_goals > away_goals:
                                                        _h2h_result_code = "V"
                                                    elif home_goals < away_goals:
                                                        _h2h_result_code = "D"
                                                h2h_rows.append({
                                                    "fixture_id": h2h_fixture_id,
                                                    "date_html": date_label,
                                                    "home_html": ph_name,
                                                    "home_logo": ph_logo,
                                                    "home_id": ph.get("id"),
                                                    "away_html": pa_name,
                                                    "away_logo": pa_logo,
                                                    "away_id": pa.get("id"),
                                                    "home_goals": home_goals,
                                                    "away_goals": away_goals,
                                                    "result_code": _h2h_result_code,
                                                })
                                            if valid_goal_totals:
                                                average_goals = sum(valid_goal_totals) / len(valid_goal_totals)
                                            else:
                                                average_goals = 0.0
                                            h2h_sample_size = len(valid_goal_totals)
                                            h2h_period_sample_size = min(len(first_half_goal_totals), len(second_half_goal_totals))
                                            first_half_average = sum(first_half_goal_totals) / h2h_period_sample_size if h2h_period_sample_size else None
                                            second_half_average = sum(second_half_goal_totals) / h2h_period_sample_size if h2h_period_sample_size else None
                                            first_half_average_label = f"{first_half_average:.2f}" if first_half_average is not None else "—"
                                            second_half_average_label = f"{second_half_average:.2f}" if second_half_average is not None else "—"
                                            if h2h_sample_size:
                                                home_pct = round(home_wins_count / h2h_sample_size * 100, 1)
                                                draw_pct = round(draw_count / h2h_sample_size * 100, 1)
                                                away_pct = round(100.0 - home_pct - draw_pct, 1)
                                                both_pct = round(both_score_count / h2h_sample_size * 100, 1)
                                            else:
                                                home_pct = draw_pct = away_pct = both_pct = 0.0
                                            def h2h_pct_label(value):
                                                return f"{value:.1f}".replace(".", ",") + "%"
                                            summary_html = (
                                                '<div class="h2h-summary-layout">'
                                                f'<div class="h2h-sample-card"><div class="h2h-summary-label">MUESTRA</div><div class="h2h-sample-value">{h2h_sample_size} PARTIDOS</div></div>'
                                                '<div class="h2h-results-grid">'
                                                f'<div class="h2h-result-card"><div class="h2h-summary-label">GANADOR LOCAL</div><div class="h2h-result-count">{home_wins_count}/{h2h_sample_size}</div></div>'
                                                f'<div class="h2h-result-card"><div class="h2h-summary-label">EMPATE</div><div class="h2h-result-count">{draw_count}/{h2h_sample_size}</div></div>'
                                                f'<div class="h2h-result-card"><div class="h2h-summary-label">GANADOR VISITANTE</div><div class="h2h-result-count">{away_wins_count}/{h2h_sample_size}</div></div>'
                                                '</div>'
                                                '<div class="h2h-distribution">'
                                                '<div class="h2h-distribution-heading"><span>DISTRIBUCIÓN DE RESULTADOS</span><strong>100%</strong></div>'
                                                '<div class="h2h-distribution-track">'
                                                f'<span class="h2h-distribution-home" style="width:{home_pct}%"></span>'
                                                f'<span class="h2h-distribution-draw" style="width:{draw_pct}%"></span>'
                                                f'<span class="h2h-distribution-away" style="width:{away_pct}%"></span>'
                                                '</div>'
                                                f'<div class="h2h-distribution-legend"><span class="h2h-legend-local"><i></i>Local {h2h_pct_label(home_pct)}</span><span class="h2h-legend-draw"><i></i>Empate {h2h_pct_label(draw_pct)}</span><span class="h2h-legend-away"><i></i>Visitante {h2h_pct_label(away_pct)}</span></div>'
                                                '</div>'
                                                '<div class="h2h-secondary-grid">'
                                                f'<div class="h2h-secondary-card"><div class="h2h-summary-label">AMBOS MARCAN</div><div class="h2h-secondary-value">{both_score_count}/{h2h_sample_size}</div><div class="h2h-secondary-pct">{h2h_pct_label(both_pct)}</div></div>'
                                                f'<div class="h2h-secondary-card"><div class="h2h-summary-label">PROMEDIO DE GOLES</div><div class="h2h-secondary-value">{average_goals:.2f}</div><div class="h2h-secondary-note">Goles por partido</div></div>'
                                                '</div>'
                                                '<div class="h2h-period-grid">'
                                                f'<div class="h2h-period-card"><div class="h2h-summary-label">PROMEDIO · PRIMER TIEMPO</div><div class="h2h-period-value">{first_half_average_label}</div><div class="h2h-period-note">Goles por partido · {h2h_period_sample_size}/{len(h2h_matches)} con descanso disponible</div></div>'
                                                f'<div class="h2h-period-card"><div class="h2h-summary-label">PROMEDIO · SEGUNDO TIEMPO</div><div class="h2h-period-value">{second_half_average_label}</div><div class="h2h-period-note">Goles por partido · {h2h_period_sample_size}/{len(h2h_matches)} con descanso disponible</div></div>'
                                                '</div>'
                                                '</div>'
                                            )
                                            st.markdown(summary_html, unsafe_allow_html=True)
                                            st.markdown('<div class="h2h-history-list">', unsafe_allow_html=True)
                                            for _h2h_index, _h2h_row in enumerate(h2h_rows):
                                                _h2h_fixture_id = _h2h_row.get("fixture_id")
                                                _h2h_timeline_key = f"h2h_goal_timeline_open_{h2h_key}"
                                                _h2h_is_open = st.session_state.get(_h2h_timeline_key) == str(_h2h_fixture_id) if _h2h_fixture_id else False
                                                with st.container(key=f"h2h_history_row_{h2h_key}_{_h2h_fixture_id or _h2h_row['date_html']}"):
                                                    _h2h_result_code = str(_h2h_row.get("result_code") or "E")
                                                    _h2h_result_class = {"V": "v", "E": "e", "D": "d"}.get(_h2h_result_code, "e")
                                                    _h2h_home_score = html.escape(str(_h2h_row.get("home_goals"))) if isinstance(_h2h_row.get("home_goals"), (int, float)) else "—"
                                                    _h2h_away_score = html.escape(str(_h2h_row.get("away_goals"))) if isinstance(_h2h_row.get("away_goals"), (int, float)) else "—"
                                                    st.markdown(f'<div class="goal-form-match-meta">{_h2h_row["date_html"]}</div>', unsafe_allow_html=True)
                                                    _h2h_match_cols = st.columns([0.76, 0.10, 0.14], gap="small", vertical_alignment="center")
                                                    with _h2h_match_cols[0]:
                                                        st.markdown(f'<div class="goal-form-team-lines"><div>{_h2h_row["home_html"]}</div><div>{_h2h_row["away_html"]}</div></div>', unsafe_allow_html=True)
                                                    with _h2h_match_cols[1]:
                                                        st.markdown(f'<div class="goal-form-score-lines"><div>{_h2h_home_score}</div><div>{_h2h_away_score}</div></div>', unsafe_allow_html=True)
                                                    with _h2h_match_cols[2]:
                                                        _h2h_action_cols = st.columns([0.46, 0.54], gap="small", vertical_alignment="center")
                                                        with _h2h_action_cols[0]:
                                                            st.markdown(f'<div class="goal-form-actions"><span class="goal-form-result goal-form-result-{_h2h_result_class}">{html.escape(_h2h_result_code)}</span></div>', unsafe_allow_html=True)
                                                        with _h2h_action_cols[1]:
                                                            if _h2h_fixture_id:
                                                                if st.button("📊", key=f"goal_timeline_btn_h2h_{h2h_key}_{_h2h_fixture_id}", help="Ver estadísticas completas de este partido histórico"):
                                                                    st.session_state[_h2h_timeline_key] = None if _h2h_is_open else str(_h2h_fixture_id)
                                                                    st.rerun()
                                                            else:
                                                                st.caption("—")
                                                    if _h2h_is_open and _h2h_fixture_id:
                                                        _h2h_stats_cache = st.session_state.setdefault("h2h_match_stats_cache", {})
                                                        _h2h_stats_cache_key = str(_h2h_fixture_id)
                                                        if _h2h_stats_cache_key not in _h2h_stats_cache:
                                                            _h2h_stats_cache[_h2h_stats_cache_key] = {}
                                                            try:
                                                                _h2h_events_payload = api_get("fixtures/events", {"fixture": _h2h_fixture_id})
                                                                _h2h_stats_cache[_h2h_stats_cache_key]["events"] = _h2h_events_payload.get("response") or []
                                                            except Exception as _h2h_events_exc:
                                                                _h2h_stats_cache[_h2h_stats_cache_key]["events_error"] = str(_h2h_events_exc)
                                                            try:
                                                                _h2h_stats_payload = api_get("fixtures/statistics", {"fixture": _h2h_fixture_id})
                                                                _h2h_stats_cache[_h2h_stats_cache_key]["statistics"] = _h2h_stats_payload.get("response") or []
                                                            except Exception as _h2h_stats_exc:
                                                                _h2h_stats_cache[_h2h_stats_cache_key]["stats_error"] = str(_h2h_stats_exc)
                                                        _h2h_match_data = _h2h_stats_cache[_h2h_stats_cache_key]
                                                        _h2h_home_name = html.unescape(str(_h2h_row.get("home_html") or "Local"))
                                                        _h2h_away_name = html.unescape(str(_h2h_row.get("away_html") or "Visitante"))
                                                        _h2h_team_names = [_h2h_home_name, _h2h_away_name]
                                                        _h2h_scorers = {0: [], 1: []}
                                                        _h2h_events = _h2h_match_data.get("events") or []
                                                        _h2h_goal_events = [
                                                            ev for ev in _h2h_events
                                                            if str(ev.get("type") or "").casefold() == "goal"
                                                            and str(ev.get("detail") or "").casefold() not in {"missed penalty", "penalty missed"}
                                                        ] if isinstance(_h2h_events, list) else []
                                                        _h2h_goal_events.sort(key=lambda ev: (int(((ev.get("time") or {}).get("elapsed")) or 0), int(((ev.get("time") or {}).get("extra")) or 0)))
                                                        for _h2h_ev in _h2h_goal_events:
                                                            _h2h_tm = _h2h_ev.get("time") or {}
                                                            _h2h_elapsed, _h2h_extra = _h2h_tm.get("elapsed"), _h2h_tm.get("extra")
                                                            _h2h_minute = f"{_h2h_elapsed}+{_h2h_extra}′" if _h2h_extra else f"{_h2h_elapsed}′" if _h2h_elapsed is not None else "N/D"
                                                            _h2h_player = (_h2h_ev.get("player") or {}).get("name") or "Autor N/D"
                                                            _h2h_side = _h2h_ev.get("team") or {}
                                                            _h2h_side_id = _h2h_side.get("id")
                                                            if str(_h2h_side_id) == str(_h2h_row.get("home_id")):
                                                                _h2h_scorers[0].append(f'<div class="goal-stats-scorer">⚽ {html.escape(str(_h2h_player))} ({html.escape(str(_h2h_minute))})</div>')
                                                            elif str(_h2h_side_id) == str(_h2h_row.get("away_id")):
                                                                _h2h_scorers[1].append(f'<div class="goal-stats-scorer">⚽ {html.escape(str(_h2h_player))} ({html.escape(str(_h2h_minute))})</div>')
                                                        _h2h_stat_map = {}
                                                        _h2h_stat_team_names = {}
                                                        for _h2h_team_stats in (_h2h_match_data.get("statistics") or []):
                                                            _h2h_team_info = _h2h_team_stats.get("team") or {}
                                                            _h2h_stat_team_name = str(_h2h_team_info.get("name") or "Equipo")
                                                            _h2h_stat_team_names[str(_h2h_team_info.get("id"))] = _h2h_stat_team_name
                                                            for _h2h_stat in (_h2h_team_stats.get("statistics") or []):
                                                                _h2h_stat_map.setdefault(_h2h_stat.get("type"), {})[_h2h_stat_team_name] = _h2h_stat.get("value")
                                                        _h2h_stat_labels = [
                                                            ("Tiros totales", "Total Shots"), ("Tiros a puerta", "Shots on Goal"),
                                                            ("Posesión", "Ball Possession"), ("Córners", "Corner Kicks"),
                                                            ("Tarjetas amarillas", "Yellow Cards"), ("Tarjetas rojas", "Red Cards"),
                                                        ]
                                                        _h2h_table_rows = []
                                                        for _h2h_label, _h2h_api_key in _h2h_stat_labels:
                                                            _h2h_values = _h2h_stat_map.get(_h2h_api_key, {})
                                                            _h2h_left = _h2h_values.get(_h2h_stat_team_names.get(str(_h2h_row.get("home_id")), _h2h_home_name))
                                                            _h2h_right = _h2h_values.get(_h2h_stat_team_names.get(str(_h2h_row.get("away_id")), _h2h_away_name))
                                                            _h2h_table_rows.append(f'<tr><th>{_h2h_label}</th><td>{html.escape(str(_h2h_left if _h2h_left is not None else "N/D"))}</td><td>{html.escape(str(_h2h_right if _h2h_right is not None else "N/D"))}</td></tr>')
                                                        _h2h_home_logo = html.escape(str(_h2h_row.get("home_logo") or ""), quote=True)
                                                        _h2h_away_logo = html.escape(str(_h2h_row.get("away_logo") or ""), quote=True)
                                                        _h2h_home_badge = f'<img src="{_h2h_home_logo}" alt="">' if _h2h_home_logo else '<span>⚽</span>'
                                                        _h2h_away_badge = f'<img src="{_h2h_away_logo}" alt="">' if _h2h_away_logo else '<span>⚽</span>'
                                                        _h2h_home_scorers = "".join(_h2h_scorers[0]) or '<div class="goal-stats-no-scorer">Sin goles</div>'
                                                        _h2h_away_scorers = "".join(_h2h_scorers[1]) or '<div class="goal-stats-no-scorer">Sin goles</div>'
                                                        _h2h_home_score = html.escape(str(_h2h_row.get("home_goals"))) if _h2h_row.get("home_goals") is not None else "—"
                                                        _h2h_away_score = html.escape(str(_h2h_row.get("away_goals"))) if _h2h_row.get("away_goals") is not None else "—"
                                                        _h2h_scoreboard_html = '<div class="goal-stats-scoreboard"><div class="goal-stats-live-team">' + _h2h_home_badge + '<strong>' + html.escape(_h2h_home_name) + '</strong><div class="goal-stats-scorers">' + _h2h_home_scorers + '</div></div><div class="goal-stats-live-score">' + _h2h_home_score + ' - ' + _h2h_away_score + '</div><div class="goal-stats-live-team">' + _h2h_away_badge + '<strong>' + html.escape(_h2h_away_name) + '</strong><div class="goal-stats-scorers">' + _h2h_away_scorers + '</div></div></div>'
                                                        _h2h_home_heading = '<span class="goal-stats-team-heading">' + html.escape(_h2h_home_name) + '</span>'
                                                        _h2h_away_heading = '<span class="goal-stats-team-heading">' + html.escape(_h2h_away_name) + '</span>'
                                                        _h2h_stats_html = '<div class="goal-match-stats-table">' + _h2h_scoreboard_html + '<table><thead><tr><th>Estadística</th><th>' + _h2h_home_heading + '</th><th>' + _h2h_away_heading + '</th></tr></thead><tbody>' + "".join(_h2h_table_rows) + '</tbody></table></div>'
                                                        if _h2h_match_data.get("stats_error") and not _h2h_match_data.get("statistics"):
                                                            st.caption("No fue posible consultar las estadísticas de este partido histórico.")
                                                        else:
                                                            st.markdown(_h2h_stats_html, unsafe_allow_html=True)
                                            st.markdown('</div>', unsafe_allow_html=True)
                                        elif isinstance(h2h_data, list) and h2h_data:
                                            # Compatibilidad con entradas de caché creadas antes de h2h-v2.
                                            st.info("Se encontraron datos H2H antiguos en caché. Vuelve a abrir H2H para cargar el historial actualizado.")
                                        elif h2h_data is not None:
                                            st.info("La API no devolvió enfrentamientos directos finalizados para estos equipos en los resultados consultados.")
                                    elif tool_name == "market":
                                        market_key = selected_tool.get("market")
                                        if market_key == "goals":
                                            _pending_scan_request = st.session_state.get("analysis_scan_request") or {}
                                            _pending_goals_request = str(_pending_scan_request.get("fixture_id")) == str(match_id) and _pending_scan_request.get("market") == "goals"
                                            _goal_radar_clicked = _pending_goals_request and _pending_scan_request.get("action") == "scan"
                                            _goal_refresh_clicked = _pending_goals_request and _pending_scan_request.get("action") == "refresh"
                                            if _pending_goals_request:
                                                st.session_state.pop("analysis_scan_request", None)
                                            if _goal_radar_clicked or _goal_refresh_clicked:
                                                    manual_scan = True
                                                    internal_scan_requested = True
                                                    # El estado de escaneo se muestra una sola vez debajo de los botones superiores.
                                            st.markdown('<div class="match-analysis-title goals-section-title">⚽ Goles y señales</div>', unsafe_allow_html=True)
                                            # Mostrar el marcador actual con escudos, igual que en la sección de córners.
                                            st.markdown(fixture_hero_html(match, mode="goals"), unsafe_allow_html=True)
                                            goal_item = next((item for item in st.session_state.get("goal_scan_results", []) if str((item[0].get("fixture") or {}).get("id")) == str(match_id)), None)
                                            corner_item = next((item for item in st.session_state.get("corner_scan_results", []) if str(((item.get("fixture") or {}).get("fixture") or {}).get("id")) == str(match_id)), None)
                                            if goal_item:
                                                _, estimate, tips, *rest = goal_item
                                                history = (corner_item or {}).get("automatic_history") or {}
                                                live_stats = st.session_state.stats_cache.get(str(match_id), [])
                                                current_goals = match.get("goals") or {}
                                                current_minute = (match_fixture.get("status") or {}).get("elapsed")
                                                home_score = current_goals.get("home")
                                                away_score = current_goals.get("away")
                                                home_name = str(match_home.get("name") or "Local")
                                                away_name = str(match_away.get("name") or "Visitante")
                                                home_on = safe_stat_for_team(live_stats, "Shots on Goal", match_home.get("id"))
                                                away_on = safe_stat_for_team(live_stats, "Shots on Goal", match_away.get("id"))
                                                goal_history_rows = [
                                                    (f"{home_name} · goles a favor en casa", history.get("home_goals_for"), history.get("home_goal_sample", 0)),
                                                    (f"{home_name} · goles recibidos en casa", history.get("home_goals_against"), history.get("home_goal_sample", 0)),
                                                    (f"{away_name} · goles a favor fuera", history.get("away_goals_for"), history.get("away_goal_sample", 0)),
                                                    (f"{away_name} · goles recibidos fuera", history.get("away_goals_against"), history.get("away_goal_sample", 0)),
                                                ]
                                                goal_table_html = '<div class="goal-history-wrap"><div class="goal-history-heading">▥ Promedio de goles</div><table class="goal-history-table"><thead><tr><th>Equipo / indicador</th><th>Promedio</th></tr></thead><tbody>'
                                                for label, avg, sample in goal_history_rows:
                                                    avg_text = f"{avg:.2f}".rstrip("0").rstrip(".") if isinstance(avg, (int, float)) else "N/D"
                                                    sample_text = int(sample or 0)
                                                    goal_table_html += f'<tr><td>{html.escape(str(label))}</td><td>{avg_text} <span style="color:#9CA3AF;font-size:.82em;">({sample_text})</span></td></tr>'
                                                goal_table_html += '</tbody></table></div>'
                                                st.markdown(goal_table_html, unsafe_allow_html=True)

                                                # Promedio esperado de goles del partido: combina ataque propio y goles concedidos por el rival.
                                                home_goal_inputs = [
                                                    history.get("home_goals_for"),
                                                    history.get("away_goals_against"),
                                                ]
                                                away_goal_inputs = [
                                                    history.get("away_goals_for"),
                                                    history.get("home_goals_against"),
                                                ]
                                                home_goal_inputs = [float(value) for value in home_goal_inputs if isinstance(value, (int, float))]
                                                away_goal_inputs = [float(value) for value in away_goal_inputs if isinstance(value, (int, float))]
                                                projected_home_goals = sum(home_goal_inputs) / len(home_goal_inputs) if home_goal_inputs else None
                                                projected_away_goals = sum(away_goal_inputs) / len(away_goal_inputs) if away_goal_inputs else None
                                                expected_match_goals = None
                                                if projected_home_goals is not None and projected_away_goals is not None:
                                                    expected_match_goals = projected_home_goals + projected_away_goals
                                                    st.markdown(
                                                        f"""
                                                        <div class="goal-average-badge" style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;
                                                                    margin:16px 0 18px;padding:7px 10px;
                                                                    border:1px solid #51451D;border-radius:9px;
                                                                    background:linear-gradient(135deg,#17191f,#20232b);
                                                                    width:fit-content;max-width:100%;clear:both;position:relative;">
                                                          <span style="font-size:11px;font-weight:700;color:#FACC15;letter-spacing:.3px;">
                                                            PROMEDIO GOLES
                                                          </span>
                                                          <span style="display:inline-block;padding:4px 9px;
                                                                       border:1px solid #FACC15;border-radius:7px;
                                                                       background:#FACC15;color:#111827;
                                                                       font-size:13px;font-weight:800;line-height:1.1;">
                                                            {expected_match_goals:.2f}
                                                          </span>
                                                        </div>
                                                        """,
                                                        unsafe_allow_html=True,
                                                    )
                                                # Reserve these positions directly under the competition-goals indicator;
                                                # fill them once the H2H context has been calculated below.
                                                goal_h2h_average_slot = st.empty()
                                                goal_today_average_slot = st.empty()

                                                # Deep, cached context: league form, H2H and response after conceding.
                                                deep_cache = st.session_state.setdefault("deep_goal_context_cache", {})
                                                try:
                                                    deep_context = build_deep_goal_context(
                                                        match,
                                                        api_get=api_get,
                                                        cache=deep_cache,
                                                        event_fixture_budget=3,
                                                    )
                                                except Exception as deep_exc:
                                                    deep_context = {"available": False, "notes": [f"Contexto profundo no disponible: {deep_exc}"]}

                                                # El promedio H2H del indicador debe usar el mismo historial de la sección H2H.
                                                h2h_average_goals = (deep_context.get("h2h") or {}).get("avg_goals")
                                                if not isinstance(h2h_average_goals, (int, float)):
                                                    try:
                                                        _goal_h2h_cache = st.session_state.setdefault("h2h_cache", {})
                                                        _goal_h2h_league = match.get("league") or {}
                                                        _goal_h2h_key = f"h2h-v3-home-{match_home_id}-{match_away_id}-{_goal_h2h_league.get('id') or 'all'}"
                                                        _goal_h2h_data = _goal_h2h_cache.get(_goal_h2h_key)
                                                        if not isinstance(_goal_h2h_data, dict) or "matches" not in _goal_h2h_data:
                                                            _goal_h2h_payload = api_get("fixtures/headtohead", {"h2h": f"{match_home_id}-{match_away_id}", "last": 50})
                                                            _goal_h2h_all = _goal_h2h_payload.get("response") or []
                                                            _goal_h2h_finished = [
                                                                past for past in _goal_h2h_all
                                                                if ((past.get("fixture") or {}).get("status") or {}).get("short") in {"FT", "AET", "PEN"}
                                                            ]
                                                            _goal_h2h_home = [
                                                                past for past in _goal_h2h_finished
                                                                if str((((past.get("teams") or {}).get("home") or {}).get("id"))) == str(match_home_id)
                                                            ]
                                                            _goal_h2h_home.sort(key=lambda past: ((past.get("fixture") or {}).get("date") or ""), reverse=True)
                                                            _goal_h2h_league_id = _goal_h2h_league.get("id")
                                                            _goal_h2h_same_league = [
                                                                past for past in _goal_h2h_home
                                                                if (past.get("league") or {}).get("id") == _goal_h2h_league_id
                                                            ] if _goal_h2h_league_id else _goal_h2h_home
                                                            _goal_h2h_selected = _goal_h2h_same_league[:10]
                                                            if len(_goal_h2h_selected) < 10:
                                                                _goal_h2h_selected_ids = {(past.get("fixture") or {}).get("id") for past in _goal_h2h_selected}
                                                                _goal_h2h_selected.extend([
                                                                    past for past in _goal_h2h_home
                                                                    if (past.get("fixture") or {}).get("id") not in _goal_h2h_selected_ids
                                                                ][:10 - len(_goal_h2h_selected)])
                                                            _goal_h2h_data = {"matches": _goal_h2h_selected[:10]}
                                                            _goal_h2h_cache[_goal_h2h_key] = _goal_h2h_data
                                                        _goal_h2h_matches = _goal_h2h_data.get("matches") or []
                                                        _goal_h2h_totals = []
                                                        for _past in _goal_h2h_matches:
                                                            _goals = _past.get("goals") or {}
                                                            _gh, _ga = _goals.get("home"), _goals.get("away")
                                                            if isinstance(_gh, (int, float)) and isinstance(_ga, (int, float)):
                                                                _goal_h2h_totals.append(_gh + _ga)
                                                        if _goal_h2h_totals:
                                                            h2h_average_goals = sum(_goal_h2h_totals) / len(_goal_h2h_totals)
                                                    except Exception:
                                                        pass

                                                if deep_context.get("available"):
                                                    st.markdown('<div class="goal-deep-heading">⌁ ÚLTIMOS PARTIDOS POR CONDICIÓN</div>', unsafe_allow_html=True)
                                                    form_cols = st.columns(1, gap="small")
                                                    for col, team, label, form_data in (
                                                        (form_cols[0], match_home, home_name, deep_context.get("home_form") or {}),
                                                        (form_cols[0], match_away, away_name, deep_context.get("away_form") or {}),
                                                    ):
                                                        team_logo = html.escape(str(team.get("logo") or ""), quote=True)
                                                        logo_html = f'<img class="goal-form-logo" src="{team_logo}" alt="">' if team_logo else ""
                                                        flip_key = f"goal_form_flipped_{match_id}_{team.get('id') or label}"
                                                        is_flipped = bool(st.session_state.get(flip_key, False))
                                                        with col.container(key=f"goal_form_front_{match_id}_{team.get('id') or label}"):
                                                            st.markdown(
                                                                f'<div class="goal-form-header">{logo_html}<div class="goal-form-team">{("ÚLTIMOS PARTIDOS · " if is_flipped else "")}{html.escape(label)}</div></div>',
                                                                unsafe_allow_html=True,
                                                            )
                                                            _, ball_col = st.columns([0.82, 0.18], gap="small", vertical_alignment="center")
                                                            if ball_col.button("⚽", key=f"goal_form_flip_btn_{match_id}_{team.get('id') or label}", help="Ver últimos partidos" if not is_flipped else "Volver al resumen"):
                                                                st.session_state[flip_key] = not is_flipped
                                                                st.rerun()
                                                            if is_flipped:
                                                                recent_matches = form_data.get("recent_matches") or []
                                                                with st.container(key=f"goal_form_back_{match_id}_{team.get('id') or label}"):
                                                                    if not recent_matches:
                                                                        st.caption("No hay partidos recientes disponibles para esta condición.")
                                                                    else:
                                                                        st.caption("📊 Abre las estadísticas de cualquier partido para consultar sus datos y los minutos de los goles.")
                                                                    active_goal_match_key = f"goal_timeline_open_{match_id}"
                                                                    for recent in recent_matches:
                                                                        result_code = str(recent.get("result") or "?").upper()
                                                                        result_class = {"V": "v", "E": "e", "D": "d"}.get(result_code, "e")
                                                                        _raw_recent_date = str(recent.get("date") or "")
                                                                        try:
                                                                            date_label = datetime.strptime(_raw_recent_date[:10], "%Y-%m-%d").strftime("%d-%m-%y")
                                                                        except (TypeError, ValueError):
                                                                            date_label = _raw_recent_date or "Fecha N/D"
                                                                        date_label = html.escape(date_label)
                                                                        home_label = html.escape(str(recent.get("home_name") or "Local"))
                                                                        away_label = html.escape(str(recent.get("away_name") or "Visitante"))
                                                                        hg, ag = recent.get("home_goals"), recent.get("away_goals")
                                                                        score_label = f"{hg}–{ag}" if isinstance(hg, int) and isinstance(ag, int) else "—"
                                                                        recent_id = recent.get("fixture_id")
                                                                        match_row_key = f"{match_id}_{recent_id or date_label}_{team.get('id') or label}"
                                                                        is_timeline_open = st.session_state.get(active_goal_match_key) == str(recent_id) if recent_id else False
                                                                        _hg_label = html.escape(str(hg)) if isinstance(hg, int) else "—"
                                                                        _ag_label = html.escape(str(ag)) if isinstance(ag, int) else "—"
                                                                        st.markdown(f'<div class="goal-form-match-meta">{date_label}</div>', unsafe_allow_html=True)
                                                                        match_action_cols = st.columns([0.76, 0.10, 0.14], gap="small", vertical_alignment="center")
                                                                        with match_action_cols[0]:
                                                                            st.markdown(f'<div class="goal-form-team-lines"><div>{home_label}</div><div>{away_label}</div></div>', unsafe_allow_html=True)
                                                                        with match_action_cols[1]:
                                                                            st.markdown(f'<div class="goal-form-score-lines"><div>{_hg_label}</div><div>{_ag_label}</div></div>', unsafe_allow_html=True)
                                                                        with match_action_cols[2]:
                                                                            result_button_cols = st.columns([0.48, 0.52], gap="small", vertical_alignment="center")
                                                                            with result_button_cols[0]:
                                                                                st.markdown(f'<div class="goal-form-actions"><span class="goal-form-result goal-form-result-{result_class}">{html.escape(result_code)}</span></div>', unsafe_allow_html=True)
                                                                            with result_button_cols[1]:
                                                                                if recent_id:
                                                                                    if st.button("📊", key=f"goal_timeline_btn_{match_row_key}", help="Ver estadísticas completas de este partido"):
                                                                                        st.session_state[active_goal_match_key] = None if is_timeline_open else str(recent_id)
                                                                                        st.rerun()
                                                                                else:
                                                                                    st.caption("—")
                                                                        if is_timeline_open and recent_id:
                                                                            _goal_stats_cache = st.session_state.setdefault("goal_recent_stats_cache", {})
                                                                            _goal_stats_key = str(recent_id)
                                                                            if _goal_stats_key not in _goal_stats_cache:
                                                                                _goal_stats_cache[_goal_stats_key] = {}
                                                                                try:
                                                                                    _events_payload = api_get("fixtures/events", {"fixture": recent_id})
                                                                                    _goal_stats_cache[_goal_stats_key]["events"] = _events_payload.get("response") or []
                                                                                except Exception as _events_exc:
                                                                                    _goal_stats_cache[_goal_stats_key]["events_error"] = str(_events_exc)
                                                                                try:
                                                                                    _stats_payload = api_get("fixtures/statistics", {"fixture": recent_id})
                                                                                    _goal_stats_cache[_goal_stats_key]["statistics"] = _stats_payload.get("response") or []
                                                                                except Exception as _stats_exc:
                                                                                    _goal_stats_cache[_goal_stats_key]["stats_error"] = str(_stats_exc)
                                                                            _match_data = _goal_stats_cache[_goal_stats_key]
                                                                            _event_rows = _match_data.get("events") or []
                                                                            _goal_events = [ev for ev in _event_rows if str(ev.get("type") or "").casefold() == "goal" and str(ev.get("detail") or "").casefold() not in {"missed penalty", "penalty missed"}] if isinstance(_event_rows,list) else []
                                                                            _goal_events.sort(key=lambda ev: (int(((ev.get("time") or {}).get("elapsed")) or 0), int(((ev.get("time") or {}).get("extra")) or 0)))
                                                                            _team_names = [str(recent.get("home_name") or "Local"), str(recent.get("away_name") or "Visitante")]
                                                                            _goal_scorers_by_team = {0: [], 1: []}
                                                                            for _ev in _goal_events:
                                                                                _tm = _ev.get("time") or {}
                                                                                _elapsed, _extra = _tm.get("elapsed"), _tm.get("extra")
                                                                                _minute = f"{_elapsed}+{_extra}′" if _extra else f"{_elapsed}′" if _elapsed is not None else "N/D"
                                                                                _player = (_ev.get("player") or {}).get("name") or "Autor N/D"
                                                                                _side_data = _ev.get("team") or {}
                                                                                _side = str(_side_data.get("name") or "")
                                                                                _side_id = _side_data.get("id")
                                                                                if _side_id is not None and str(_side_id) == str((recent.get("home_id") or "")):
                                                                                    _goal_team_index = 0
                                                                                elif _side_id is not None and str(_side_id) == str((recent.get("away_id") or "")):
                                                                                    _goal_team_index = 1
                                                                                elif _side.casefold() == _team_names[0].casefold():
                                                                                    _goal_team_index = 0
                                                                                elif _side.casefold() == _team_names[1].casefold():
                                                                                    _goal_team_index = 1
                                                                                else:
                                                                                    _goal_team_index = None
                                                                                if _goal_team_index is not None:
                                                                                    _goal_scorers_by_team[_goal_team_index].append(f'<div class="goal-stats-scorer">⚽ {html.escape(str(_player))} ({html.escape(str(_minute))})</div>')
                                                                            _stat_map = {}
                                                                            _team_logos = {}
                                                                            for _team_stats in (_match_data.get("statistics") or []):
                                                                                _team_info = _team_stats.get("team") or {}
                                                                                _team_name = _team_info.get("name") or "Equipo"
                                                                                _team_logos[str(_team_name).casefold()] = _team_info.get("logo") or ""
                                                                                for _stat in (_team_stats.get("statistics") or []):
                                                                                    _stat_map.setdefault(_stat.get("type"), {})[_team_name] = _stat.get("value")
                                                                            _stat_labels = [
                                                                                ("Tiros totales", "Total Shots"), ("Tiros a puerta", "Shots on Goal"),
                                                                                ("Posesión", "Ball Possession"), ("Córners", "Corner Kicks"),
                                                                                ("Tarjetas amarillas", "Yellow Cards"), ("Tarjetas rojas", "Red Cards"),
                                                                            ]
                                                                            _table_rows = []
                                                                            for _label, _api_key in _stat_labels:
                                                                                _values = _stat_map.get(_api_key, {})
                                                                                _left, _right = _values.get(_team_names[0]), _values.get(_team_names[1])
                                                                                _table_rows.append(f'<tr><th>{_label}</th><td>{html.escape(str(_left if _left is not None else "N/D"))}</td><td>{html.escape(str(_right if _right is not None else "N/D"))}</td></tr>')
                                                                            _home_score_badge = html.escape(str(recent.get("home_goals"))) if isinstance(recent.get("home_goals"), int) else "—"
                                                                            _away_score_badge = html.escape(str(recent.get("away_goals"))) if isinstance(recent.get("away_goals"), int) else "—"
                                                                            _home_score_badge = html.escape(str(recent.get("home_goals"))) if isinstance(recent.get("home_goals"), int) else "—"
                                                                            _away_score_badge = html.escape(str(recent.get("away_goals"))) if isinstance(recent.get("away_goals"), int) else "—"
                                                                            _home_logo = html.escape(str(_team_logos.get(_team_names[0].casefold()) or ""), quote=True)
                                                                            _away_logo = html.escape(str(_team_logos.get(_team_names[1].casefold()) or ""), quote=True)
                                                                            _home_badge = f'<img src="{_home_logo}" alt="">' if _home_logo else '<span>⚽</span>'
                                                                            _away_badge = f'<img src="{_away_logo}" alt="">' if _away_logo else '<span>⚽</span>'
                                                                            _home_scorers = "".join(_goal_scorers_by_team[0]) or '<div class="goal-stats-no-scorer">Sin goles</div>'
                                                                            _away_scorers = "".join(_goal_scorers_by_team[1]) or '<div class="goal-stats-no-scorer">Sin goles</div>'
                                                                            _scoreboard_html = '<div class="goal-stats-scoreboard"><div class="goal-stats-live-team">' + _home_badge + '<strong>' + html.escape(_team_names[0]) + '</strong><div class="goal-stats-scorers">' + _home_scorers + '</div></div><div class="goal-stats-live-score">' + _home_score_badge + ' - ' + _away_score_badge + '</div><div class="goal-stats-live-team">' + _away_badge + '<strong>' + html.escape(_team_names[1]) + '</strong><div class="goal-stats-scorers">' + _away_scorers + '</div></div></div>'
                                                                            _home_stats_heading = '<span class="goal-stats-team-heading">' + html.escape(_team_names[0]) + '</span>'
                                                                            _away_stats_heading = '<span class="goal-stats-team-heading">' + html.escape(_team_names[1]) + '</span>'
                                                                            _stats_table = '<div class="goal-match-stats-table">' + _scoreboard_html + '<table><thead><tr><th>Estadística</th><th>' + _home_stats_heading + '</th><th>' + _away_stats_heading + '</th></tr></thead><tbody>' + "".join(_table_rows) + '</tbody></table></div>'
                                                                            if _match_data.get("stats_error") and not _match_data.get("statistics"):
                                                                                st.caption("No fue posible consultar las estadísticas de este partido.")
                                                                            else:
                                                                                st.markdown(_stats_table, unsafe_allow_html=True)
                                                            else:
                                                                st.markdown(
                                                                    f'<div class="goal-form-record">{html.escape(str(form_data.get("record", "N/D")))}</div>'
                                                                    f'<div class="goal-form-line">GF {form_data.get("goals_for_avg") if form_data.get("goals_for_avg") is not None else "N/D"} · GC {form_data.get("goals_against_avg") if form_data.get("goals_against_avg") is not None else "N/D"}</div>'
                                                                    f'<div class="goal-form-line">Ambos marcan {form_data.get("btts_rate") if form_data.get("btts_rate") is not None else "N/D"}% · +2.5 goles {form_data.get("over_2_5_rate") if form_data.get("over_2_5_rate") is not None else "N/D"}%</div>',
                                                                    unsafe_allow_html=True,
                                                                )
                                                    # Se omite el resumen H2H aquí para evitar duplicar el indicador de promedio.
                                                    target_minute = deep_context.get("current_goal_minute")
                                                    target_minute_label = deep_context.get("current_goal_minute_label")
                                                    if target_minute is not None:
                                                        scorer = deep_context.get("current_goal_team")
                                                        if not target_minute_label:
                                                            target_minute_label = f"{target_minute}′"
                                                        scorer_text = f' · Anotado por <b>{html.escape(str(scorer))}</b>' if scorer else ""
                                                        st.markdown(
                                                            f'<div class="goal-last-goal"><b>MINUTO DEL ÚLTIMO GOL EN EL PARTIDO</b><span>{html.escape(str(target_minute_label))}</span>{scorer_text}</div>',
                                                            unsafe_allow_html=True,
                                                        )
                                                else:
                                                    st.caption("El contexto profundo de forma/H2H no está disponible con las consultas actuales; el bot no lo tratará como dato conocido.")

                                                def _goal_average_badge(label, value):
                                                    if label == "PROMEDIO DE GOLES PARA HOY":
                                                        return f"""
                                                        <div class="goal-last-goal">
                                                          <b>{html.escape(label)}</b>
                                                          <span>{value:.2f}</span>
                                                        </div>
                                                        """
                                                    return f"""
                                                    <div class="goal-h2h-average-badge">
                                                      <span style="font-size:11px;font-weight:700;color:#FACC15;letter-spacing:.3px;">
                                                        {label}
                                                      </span>
                                                      <span style="display:inline-block;padding:4px 9px;
                                                                   border:1px solid #FACC15;border-radius:7px;
                                                                   background:#FACC15;color:#111827;
                                                                   font-size:13px;font-weight:800;line-height:1.1;">
                                                        {value:.2f}
                                                      </span>
                                                    </div>
                                                    """
                                                if isinstance(h2h_average_goals, (int, float)):
                                                    goal_h2h_average_slot.markdown(
                                                        _goal_average_badge("PROMEDIO GOLES H2H", float(h2h_average_goals)),
                                                        unsafe_allow_html=True,
                                                    )
                                                    if isinstance(expected_match_goals, (int, float)):
                                                        raw_average_goals_today = (expected_match_goals + float(h2h_average_goals)) / 2
                                                        # Aplicar margen conservador de 0.5 goles y redondear al medio gol
                                                        # más cercano: .58/.68 -> .5; .88 -> siguiente entero.
                                                        adjusted_goals_average = max(0.0, raw_average_goals_today - 0.5)
                                                        half_goal_steps = adjusted_goals_average * 2
                                                        lower_half_step = int(half_goal_steps)
                                                        if half_goal_steps - lower_half_step >= 0.5:
                                                            lower_half_step += 1
                                                        average_goals_today = lower_half_step / 2
                                                        goal_today_average_slot.markdown(
                                                            _goal_average_badge("PROMEDIO DE GOLES PARA HOY", average_goals_today),
                                                            unsafe_allow_html=True,
                                                        )
                                                # Exclude overly obvious under lines (e.g. under 4.5 at 0-0) from the main recommendation.
                                                current_total = (home_score or 0) + (away_score or 0) if isinstance(home_score, int) and isinstance(away_score, int) else None
                                                meaningful_tips = []
                                                for label, probability in (tips or []):
                                                    lower_label = str(label).casefold()
                                                    if current_total is not None and "menos de" in lower_label:
                                                        import re
                                                        line_match = re.search(r"menos de\\s+([0-9]+(?:\\.[0-9]+)?)", lower_label)
                                                        if line_match and float(line_match.group(1)) - current_total >= 3:
                                                            continue
                                                    if "total final:" in lower_label and "+0 desde ahora" in lower_label:
                                                        continue
                                                    meaningful_tips.append((label, probability))
                                                # For a 0-0 match, require live attacking evidence before proposing a team-to-score tip.
                                                if current_total == 0 and isinstance(current_minute, int):
                                                    has_live_threat = any(isinstance(v, (int, float)) and v > 0 for v in (home_on, away_on))
                                                    if not has_live_threat:
                                                        meaningful_tips = [(label, p) for label, p in meaningful_tips if "marcará al menos 1 gol" not in str(label).casefold()]
                                                # Rank surviving candidates using small, explicit historical-context adjustments.
                                                # The displayed percentage remains the base exploratory model probability.
                                                home_form = (deep_context.get("home_form") or {})
                                                away_form = (deep_context.get("away_form") or {})
                                                h2h_form = (deep_context.get("h2h") or {})
                                                home_gf = home_form.get("goals_for_avg")
                                                home_ga = home_form.get("goals_against_avg")
                                                away_gf = away_form.get("goals_for_avg")
                                                away_ga = away_form.get("goals_against_avg")
                                                historical_total = sum(v for v in (home_gf, home_ga, away_gf, away_ga) if isinstance(v, (int, float))) / 2 if all(isinstance(v, (int, float)) for v in (home_gf, home_ga, away_gf, away_ga)) else None
                                                h2h_total = h2h_form.get("avg_goals")
                                                def context_score(candidate):
                                                    label, base_probability = candidate
                                                    label_norm = str(label).casefold()
                                                    adjustment = 0.0
                                                    if "menos de" in label_norm:
                                                        if isinstance(historical_total, (int, float)) and historical_total <= 2.2:
                                                            adjustment += 0.035
                                                        elif isinstance(historical_total, (int, float)) and historical_total >= 3.0:
                                                            adjustment -= 0.04
                                                        if isinstance(h2h_total, (int, float)) and h2h_total >= 2.8:
                                                            adjustment -= 0.025
                                                    elif "goles o más" in label_norm:
                                                        if isinstance(historical_total, (int, float)) and historical_total >= 2.8:
                                                            adjustment += 0.035
                                                        elif isinstance(historical_total, (int, float)) and historical_total <= 2.0:
                                                            adjustment -= 0.025
                                                        if isinstance(h2h_total, (int, float)) and h2h_total >= 2.8:
                                                            adjustment += 0.025
                                                    if "ambos equipos marcan" in label_norm:
                                                        rates = [home_form.get("btts_rate"), away_form.get("btts_rate"), h2h_form.get("btts_rate")]
                                                        rates = [v for v in rates if isinstance(v, (int, float))]
                                                        if rates:
                                                            adjustment += max(-0.04, min(0.04, ((sum(rates) / len(rates)) - 50) / 1000))
                                                    if "terminará con" in label_norm or "marcará al menos 1 gol" in label_norm:
                                                        team_form = home_form if home_name.casefold() in label_norm else away_form if away_name.casefold() in label_norm else {}
                                                        scoring_avg = team_form.get("goals_for_avg")
                                                        conceding_avg = away_ga if team_form is home_form else home_ga if team_form is away_form else None
                                                        if isinstance(scoring_avg, (int, float)) and isinstance(conceding_avg, (int, float)):
                                                            adjustment += max(-0.04, min(0.04, (scoring_avg + conceding_avg - 2.2) * 0.025))
                                                        # If the team is currently behind, use the event-based comeback sample only as a small tiebreaker.
                                                        trailing_id = match_home_id if isinstance(home_score, int) and isinstance(away_score, int) and home_score < away_score else match_away_id if isinstance(home_score, int) and isinstance(away_score, int) and away_score < home_score else None
                                                        named_team_id = match_home_id if home_name.casefold() in label_norm else match_away_id if away_name.casefold() in label_norm else None
                                                        comeback_data = (deep_context.get("comeback") or {}).get(named_team_id, {})
                                                        if trailing_id == named_team_id and comeback_data.get("sample", 0) >= 2:
                                                            rate = comeback_data.get("equalized", 0) / comeback_data["sample"]
                                                            adjustment += max(-0.025, min(0.025, (rate - 0.25) * 0.08))
                                                    return float(base_probability) + adjustment

                                                # Show main and risk tips in this match panel too, not only in the global tab.
                                                live_odds_rows = best_live_odds_by_market(st.session_state.get("live_odds_by_fixture", {}).get(str(match_id), []))
                                                match_main_options, match_risk_options = [], []
                                                current_estimate = next((row[1] for row in st.session_state.get("goal_scan_results", []) if str(((row[0].get("fixture") or {}).get("id"))) == str(match_id)), None)
                                                current_estimate = current_estimate if isinstance(current_estimate, dict) else {}
                                                for odds_row in live_odds_rows:
                                                    market_label = classify_market(odds_row)
                                                    odd = odds_row.get("odd")
                                                    if not market_label or not isinstance(odd, (int, float)) or odd <= 1:
                                                        continue
                                                    model_prob = None
                                                    if market_label == "Empate final":
                                                        model_prob = current_estimate.get("draw_final")
                                                    elif market_label == "Ambos equipos marcan: Sí":
                                                        model_prob = current_estimate.get("btts_final")
                                                    elif market_label == "Ambos equipos marcan: No" and isinstance(current_estimate.get("btts_final"), (int, float)):
                                                        model_prob = 1.0 - current_estimate["btts_final"]
                                                    elif market_label.startswith(("Más de ", "Menos de ")) and "goles" in market_label.casefold():
                                                        import re
                                                        line_match = re.search(r"(\d+(?:[.,]\d+)?)", market_label)
                                                        if line_match:
                                                            line = float(line_match.group(1).replace(",", "."))
                                                            if market_label.startswith("Más de "):
                                                                model_prob = current_estimate.get("over_total_goals", {}).get(str(int(line + 0.5)))
                                                            else:
                                                                model_prob = current_estimate.get("under_total_goals", {}).get(str(line))
                                                    if not isinstance(model_prob, (int, float)) or not 0 < model_prob < 1:
                                                        continue
                                                    edge = float(model_prob) - 1.0 / float(odd)
                                                    if edge < 0.02:
                                                        continue
                                                    option = {"market": market_label, "odd": float(odd), "prob": float(model_prob), "edge": edge, "bookmaker": odds_row.get("bookmaker", "Casa no identificada")}
                                                    if 1.35 <= odd <= 1.60:
                                                        match_main_options.append(option)
                                                    elif odd >= 1.70:
                                                        match_risk_options.append(option)

                                                st.markdown('<div class="tip-section-heading"><span class="tip-heading-icon">◈</span><span>TIP PRINCIPAL</span><span class="tip-heading-status">EN VIVO</span></div>', unsafe_allow_html=True)
                                                if match_main_options:
                                                    selected_main = max(match_main_options, key=lambda x: x["prob"])
                                                    st.markdown(
                                                        f'<div class="tip-card">'
                                                        f'<div class="tip-card-title">{html.escape(selected_main["market"])}</div>'
                                                        f'<div class="tip-card-meta">{html.escape(selected_main["bookmaker"])} · mercado en vivo verificado</div></div>',
                                                        unsafe_allow_html=True,
                                                    )
                                                else:
                                                    st.markdown('<div class="tip-card tip-card-empty"><div class="tip-card-title">Sin oportunidad confirmada por ahora</div><div class="tip-card-meta">Esperando una cuota disponible con respaldo estadístico.</div></div>', unsafe_allow_html=True)

                                                st.markdown('<div class="tip-section-heading risk-heading"><span class="tip-heading-icon">⌁</span><span>TIP DE ALTO RIESGO</span><span class="tip-heading-status">RIESGO ALTO</span></div>', unsafe_allow_html=True)
                                                if match_risk_options:
                                                    selected_risk = max(match_risk_options, key=lambda x: x["prob"])
                                                    st.markdown(
                                                        f'<div class="tip-card risk-tip-card">'
                                                        f'<div class="tip-card-title">{html.escape(selected_risk["market"])}</div>'
                                                        f'<div class="tip-card-meta">{html.escape(selected_risk["bookmaker"])} · mercado en vivo verificado</div></div>',
                                                        unsafe_allow_html=True,
                                                    )
                                                else:
                                                    st.markdown('<div class="tip-card risk-tip-card tip-card-empty"><div class="tip-card-title">Sin oportunidad confirmada por ahora</div><div class="tip-card-meta">No se fuerza una selección ni se inventa un mercado.</div></div>', unsafe_allow_html=True)

                                                # Numerology is strictly risk-only context, never a standalone prediction.
                                                match_stats_for_patterns = st.session_state.stats_cache.get(str(match_id), [])
                                                numerology_patterns = numerology_context(
                                                    home_score, away_score,
                                                    safe_stat_for_team(match_stats_for_patterns, "Corner Kicks", match_home.get("id")),
                                                    safe_stat_for_team(match_stats_for_patterns, "Corner Kicks", match_away.get("id")),
                                                    safe_stat_for_team(match_stats_for_patterns, "Yellow Cards", match_home.get("id")),
                                                    safe_stat_for_team(match_stats_for_patterns, "Yellow Cards", match_away.get("id")),
                                                )
                                            else:
                                                st.info("Primero pulsa «Escanear todos los partidos en vivo». Después, vuelve a abrir Goles y señales para ver promedios por localía, lectura en vivo y tip principal.")
                                        elif market_key == "corners":
                                            _pending_scan_request = st.session_state.get("analysis_scan_request") or {}
                                            _pending_corners_request = str(_pending_scan_request.get("fixture_id")) == str(match_id) and _pending_scan_request.get("market") == "corners"
                                            _corner_radar_clicked = _pending_corners_request and _pending_scan_request.get("action") == "scan"
                                            _corner_refresh_clicked = _pending_corners_request and _pending_scan_request.get("action") == "refresh"
                                            if _pending_corners_request:
                                                st.session_state.pop("analysis_scan_request", None)
                                            if _corner_radar_clicked or _corner_refresh_clicked:
                                                    # Dar prioridad al partido que el usuario tiene abierto antes de
                                                    # construir el contexto histórico de los demás partidos en vivo.
                                                    st.session_state["selected_match_detail"] = {
                                                        "fixture_id": match_id,
                                                        "market": "corners",
                                                    }
                                                    manual_scan = True
                                                    internal_scan_requested = True
                                                    # El estado de escaneo se muestra una sola vez debajo de los botones superiores.
                                            st.markdown('<div class="match-analysis-title goals-section-title">🚩 Córners y señales</div>', unsafe_allow_html=True)
                                            # Reutilizar primero las estadísticas que ya consultó el escáner en vivo.
                                            live_corner_stats = st.session_state.stats_cache.get(str(match_id))
                                            known_stats_error = str(match_id) in st.session_state.get("stats_errors", {})
                                            if live_corner_stats is None or (not live_corner_stats and not known_stats_error):
                                                try:
                                                    live_corner_stats = (api_get("fixtures/statistics", {"fixture": match_id}).get("response") or [])
                                                    st.session_state.stats_cache[str(match_id)] = live_corner_stats
                                                    selected_teams = match.get("teams") or {}
                                                    selected_home_id = (selected_teams.get("home") or {}).get("id")
                                                    selected_away_id = (selected_teams.get("away") or {}).get("id")
                                                    selected_home_corners = safe_stat_for_team(live_corner_stats, "Corner Kicks", selected_home_id)
                                                    selected_away_corners = safe_stat_for_team(live_corner_stats, "Corner Kicks", selected_away_id)
                                                    if selected_home_corners is None or selected_away_corners is None:
                                                        st.session_state.setdefault("stats_errors", {})[str(match_id)] = "La API no entregó córners para ambos equipos."
                                                    else:
                                                        st.session_state.setdefault("stats_errors", {}).pop(str(match_id), None)
                                                except Exception as live_corner_exc:
                                                    live_corner_stats = []
                                                    st.session_state.stats_cache[str(match_id)] = []
                                                    st.session_state.setdefault("stats_errors", {})[str(match_id)] = str(live_corner_exc)
                                            selected_teams = match.get("teams") or {}
                                            selected_home_id = (selected_teams.get("home") or {}).get("id")
                                            selected_away_id = (selected_teams.get("away") or {}).get("id")
                                            selected_home_corners = safe_stat_for_team(live_corner_stats or [], "Corner Kicks", selected_home_id)
                                            selected_away_corners = safe_stat_for_team(live_corner_stats or [], "Corner Kicks", selected_away_id)
                                            st.markdown(fixture_hero_html(match, mode="corners", home_corners=selected_home_corners, away_corners=selected_away_corners), unsafe_allow_html=True)

                                            corner_item = next((item for item in st.session_state.get("corner_scan_results", []) if str(((item.get("fixture") or {}).get("fixture") or {}).get("id")) == str(match_id)), None)
                                            if corner_item:
                                                if corner_item.get("error"):
                                                    st.caption("Las estadísticas en vivo no están disponibles en este momento; se mostrarán los indicadores históricos que sí puedan calcularse.")
                                                home_c, away_c = corner_item.get("home_corners"), corner_item.get("away_corners")
                                                current_minute = (match_fixture.get("status") or {}).get("elapsed")
                                                current_total = (home_c + away_c) if isinstance(home_c, (int, float)) and isinstance(away_c, (int, float)) else None
                                                history = corner_item.get("automatic_history") or {}
                                                if (history.get("pending") or history.get("corners_pending")) and st.button("📚 Consultar historial de este partido", key=f"load_history_selected_{match_id}"):
                                                    try:
                                                        history_cache = st.session_state.setdefault("automatic_history_cache", {})
                                                        history_cache["_automatic_history_stats_calls"] = 0
                                                        history_cache["_automatic_history_team_fixture_calls"] = 0
                                                        corner_item["automatic_history"] = build_automatic_history(
                                                            corner_item["fixture"],
                                                            api_get=api_get,
                                                            cache=history_cache,
                                                            stats_budget=8,
                                                            live_corner_finalizer=lambda completed_fixture, final_stats: (
                                                                finalize_live_corner_fixture(LIVE_CORNER_CAPTURE_DB, completed_fixture, final_stats)
                                                            ),
                                                        )
                                                    except Exception as history_exc:
                                                        corner_item["automatic_history"] = {"available": False, "pending": True, "note": f"No se pudo consultar el historial: {history_exc}"}
                                                    history = corner_item.get("automatic_history") or {}
                                                def corner_period_cards_html(first_value, second_value, note):
                                                    first_label = f"{first_value:.2f}" if isinstance(first_value, (int, float)) else "N/D"
                                                    second_label = f"{second_value:.2f}" if isinstance(second_value, (int, float)) else "N/D"
                                                    safe_note = html.escape(str(note or ""))
                                                    return (
                                                        '<div class="corner-period-grid">'
                                                        f'<div class="corner-period-card"><div class="corner-period-label">CÓRNERS · PRIMER TIEMPO</div><div class="corner-period-value">{first_label}</div><div class="corner-period-note">{safe_note}</div></div>'
                                                        f'<div class="corner-period-card"><div class="corner-period-label">CÓRNERS · SEGUNDO TIEMPO</div><div class="corner-period-value">{second_label}</div><div class="corner-period-note">{safe_note}</div></div>'
                                                        '</div>'
                                                    )
                                                # Los córners actuales ya aparecen en la tarjeta superior del partido.
                                                # Evitamos repetir local, visitante y total en tres tarjetas separadas.

                                                corner_teams = match.get("teams") or {}
                                                corner_home_name = str((corner_teams.get("home") or {}).get("name") or "Local")
                                                corner_away_name = str((corner_teams.get("away") or {}).get("name") or "Visitante")
                                                history_rows = [
                                                    {"Indicador": f"{corner_home_name} · córners a favor en casa", "Promedio": history.get("home_corners_for"), "Muestra": history.get("home_corner_sample", 0)},
                                                    {"Indicador": f"{corner_home_name} · córners concedidos en casa", "Promedio": history.get("home_corners_against"), "Muestra": history.get("home_corner_sample", 0)},
                                                    {"Indicador": f"{corner_away_name} · córners a favor fuera", "Promedio": history.get("away_corners_for"), "Muestra": history.get("away_corner_sample", 0)},
                                                    {"Indicador": f"{corner_away_name} · córners concedidos fuera", "Promedio": history.get("away_corners_against"), "Muestra": history.get("away_corner_sample", 0)},
                                                ]
                                                history_html = '<div class="goal-history-wrap"><div class="goal-history-heading">📊 Promedios de córners en la competición actual</div><table class="goal-history-table"><thead><tr><th>Indicador</th><th>Promedio</th></tr></thead><tbody>'
                                                for row in history_rows:
                                                    avg = row["Promedio"]
                                                    avg_text = f"{avg:.2f}".rstrip("0").rstrip(".") if isinstance(avg, (int, float)) else "N/D"
                                                    sample_text = int(row.get("Muestra") or 0)
                                                    history_html += f"<tr><td>{html.escape(row['Indicador'])}</td><td>{avg_text} <span style='color:#9CA3AF;font-size:.82em;'>({sample_text})</span></td></tr>"
                                                history_html += "</tbody></table></div>"
                                                st.markdown(history_html, unsafe_allow_html=True)
                                                st.caption(
                                                    f"Muestra histórica: {int(history.get('home_corner_sample') or 0)} partidos como local · "
                                                    f"{int(history.get('away_corner_sample') or 0)} como visitante. "
                                                    "Solo se cuentan encuentros con estadísticas de córners disponibles."
                                                )

                                                # Proyección total estimada a partir de los cuatro promedios de localía.
                                                # Para cada equipo se promedian sus córners a favor y los concedidos por el rival.
                                                competition_corner_average = None
                                                home_inputs = [
                                                    history.get("home_corners_for"),
                                                    history.get("away_corners_against"),
                                                ]
                                                away_inputs = [
                                                    history.get("away_corners_for"),
                                                    history.get("home_corners_against"),
                                                ]
                                                home_inputs = [float(value) for value in home_inputs if isinstance(value, (int, float))]
                                                away_inputs = [float(value) for value in away_inputs if isinstance(value, (int, float))]
                                                projected_home_corners = sum(home_inputs) / len(home_inputs) if home_inputs else None
                                                projected_away_corners = sum(away_inputs) / len(away_inputs) if away_inputs else None
                                                def _corner_pair_mean(first_value, second_value):
                                                    available_values = [float(v) for v in (first_value, second_value) if isinstance(v, (int, float))]
                                                    return sum(available_values) / len(available_values) if available_values else None
                                                projected_home_first = _corner_pair_mean(history.get("home_corners_for_first"), history.get("away_corners_against_first"))
                                                projected_away_first = _corner_pair_mean(history.get("away_corners_for_first"), history.get("home_corners_against_first"))
                                                projected_home_second = _corner_pair_mean(history.get("home_corners_for_second"), history.get("away_corners_against_second"))
                                                projected_away_second = _corner_pair_mean(history.get("away_corners_for_second"), history.get("home_corners_against_second"))
                                                competition_first_average = projected_home_first + projected_away_first if projected_home_first is not None and projected_away_first is not None else None
                                                competition_second_average = projected_home_second + projected_away_second if projected_home_second is not None and projected_away_second is not None else None
                                                if projected_home_corners is not None and projected_away_corners is not None:
                                                    competition_corner_average = projected_home_corners + projected_away_corners
                                                    st.markdown(
                                                        f"""
                                                        <div class="corner-average-pill" style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;
                                                                    margin:16px 0 18px;padding:7px 10px;
                                                                    border:1px solid #51451D;border-radius:9px;
                                                                    background:linear-gradient(135deg,#17191f,#20232b);
                                                                    width:fit-content;max-width:100%;clear:both;position:relative;">
                                                          <span style="font-size:11px;font-weight:700;color:#FACC15;letter-spacing:.3px;">
                                                            PROMEDIO DE CÓRNERS
                                                          </span>
                                                          <span style="display:inline-block;padding:4px 9px;
                                                                       border:1px solid #FACC15;border-radius:7px;
                                                                       background:#FACC15;color:#111827;
                                                                       font-size:13px;font-weight:800;line-height:1.1;">
                                                            {competition_corner_average:.2f}
                                                          </span>
                                                        </div>
                                                        """,
                                                        unsafe_allow_html=True,
                                                    )
                                                # El diagnóstico se conserva internamente en history para depuración,
                                                # pero no se muestra en la interfaz normal del usuario.

                                                history_title_col, history_button_col = st.columns([1.55, 1], vertical_alignment="center", gap="small")
                                                with history_title_col:
                                                    st.markdown("### ⌁ Histórico de córners")
                                                home_team = (match.get("teams") or {}).get("home") or {}
                                                away_team = (match.get("teams") or {}).get("away") or {}
                                                h2h_key = f"corner-h2h-v6-home-{home_team.get('id')}-{away_team.get('id')}"
                                                if "corner_h2h_cache" not in st.session_state:
                                                    st.session_state.corner_h2h_cache = {}
                                                with history_button_col:
                                                    show_corner_history = st.button(
                                                        "VER HISTÓRICO",
                                                        key=f"corner_h2h_{match_id}",
                                                        help="Pulsa para consultar los últimos enfrentamientos y sus córners.",
                                                        use_container_width=True,
                                                    )
                                                if show_corner_history:
                                                    if not home_team.get("id") or not away_team.get("id"):
                                                        st.warning("No están disponibles los IDs de los dos equipos.")
                                                    else:
                                                        try:
                                                            if h2h_key not in st.session_state.corner_h2h_cache:
                                                                # Pedimos un margen amplio y después tomamos los 10 partidos finalizados más recientes.
                                                                h2h_payload = api_get("fixtures/headtohead", {"h2h": f"{home_team.get('id')}-{away_team.get('id')}", "last": 50})
                                                                past_matches = h2h_payload.get("response") or []
                                                                finished_statuses = {"FT", "AET", "PEN"}
                                                                # Mantener solo enfrentamientos finalizados en los que el equipo local actual también jugó como local.
                                                                # Después de filtrar por localía, tomar los 10 más recientes disponibles.
                                                                current_home_id = home_team.get("id")
                                                                past_matches = [
                                                                    past for past in past_matches
                                                                    if (
                                                                        (((past.get("fixture") or {}).get("status") or {}).get("short") in finished_statuses)
                                                                        and str((((past.get("teams") or {}).get("home") or {}).get("id"))) == str(current_home_id)
                                                                    )
                                                                ]
                                                                past_matches.sort(key=lambda past: ((past.get("fixture") or {}).get("date") or ""), reverse=True)
                                                                past_matches = past_matches[:10]
                                                                past_rows = []
                                                                for past in past_matches:
                                                                    past_id = (past.get("fixture") or {}).get("id")
                                                                    if not past_id:
                                                                        continue
                                                                    # Totales y desglose por tiempos usan consultas independientes.
                                                                    # La falta de half=true nunca debe borrar los córners totales.
                                                                    full_stats_key = f"corner-h2h-stats-full-v3:{past_id}"
                                                                    if full_stats_key not in st.session_state.stats_cache:
                                                                        st.session_state.stats_cache[full_stats_key] = (api_get("fixtures/statistics", {"fixture": past_id}).get("response") or [])
                                                                    past_stats = st.session_state.stats_cache.get(full_stats_key) or []
                                                                    past_home_c, _, _ = safe_corner_parts(past_stats, 0)
                                                                    past_away_c, _, _ = safe_corner_parts(past_stats, 1)

                                                                    half_stats_key = f"corner-h2h-stats-halves-v4:{past_id}"
                                                                    half_retry_key = f"{half_stats_key}:retry_after"
                                                                    half_stats = st.session_state.stats_cache.get(half_stats_key)
                                                                    retry_after = float(st.session_state.stats_cache.get(half_retry_key, 0) or 0)
                                                                    if half_stats is None and time.time() >= retry_after:
                                                                        try:
                                                                            half_stats = api_get("fixtures/statistics", {"fixture": past_id, "half": "true"}).get("response") or []
                                                                            if half_stats:
                                                                                st.session_state.stats_cache[half_stats_key] = half_stats
                                                                            else:
                                                                                st.session_state.stats_cache[half_retry_key] = time.time() + 1800
                                                                        except Exception:
                                                                            st.session_state.stats_cache[half_retry_key] = time.time() + 300
                                                                            half_stats = []
                                                                    half_stats = half_stats or []
                                                                    _, _past_home_first, _past_home_second = safe_corner_parts(half_stats, 0)
                                                                    _, _past_away_first, _past_away_second = safe_corner_parts(half_stats, 1)
                                                                    past_first_half_total = past_second_half_total = None
                                                                    if all(value is not None for value in (_past_home_first, _past_home_second, _past_away_first, _past_away_second, past_home_c, past_away_c)):
                                                                        if abs((_past_home_first + _past_home_second) - past_home_c) < 0.01 and abs((_past_away_first + _past_away_second) - past_away_c) < 0.01:
                                                                            past_first_half_total = _past_home_first + _past_away_first
                                                                            past_second_half_total = _past_home_second + _past_away_second
                                                                    past_fixture = past.get("fixture") or {}
                                                                    past_teams = past.get("teams") or {}
                                                                    past_goals = past.get("goals") or {}
                                                                    past_home = past_teams.get("home") or {}
                                                                    past_away = past_teams.get("away") or {}
                                                                    past_rows.append({
                                                                        "Fecha": (past_fixture.get("date") or "")[:10],
                                                                        "Local": past_home.get("name", "N/D"),
                                                                        "LocalLogo": past_home.get("logo", ""),
                                                                        "Marcador": f"{past_goals.get('home', '—')}–{past_goals.get('away', '—')}",
                                                                        "Visitante": past_away.get("name", "N/D"),
                                                                        "VisitanteLogo": past_away.get("logo", ""),
                                                                        "Córners": f"{past_home_c if past_home_c is not None else 'N/D'}–{past_away_c if past_away_c is not None else 'N/D'}",
                                                                        "Total": (past_home_c + past_away_c) if past_home_c is not None and past_away_c is not None else None,
                                                                        "PrimerTiempo": past_first_half_total,
                                                                        "SegundoTiempo": past_second_half_total,
                                                                    })
                                                                st.session_state.corner_h2h_cache[h2h_key] = past_rows
                                                        except Exception as h2h_exc:
                                                            st.session_state.corner_h2h_cache[h2h_key] = {"error": str(h2h_exc)}
                                                h2h_rows = st.session_state.corner_h2h_cache.get(h2h_key)
                                                h2h_avg = None
                                                if isinstance(h2h_rows, dict) and h2h_rows.get("error"):
                                                    st.caption("No se pudo cargar el histórico de córners: " + str(h2h_rows["error"]))
                                                elif isinstance(h2h_rows, list):
                                                    if h2h_rows:
                                                        corners_html = '<div class="corner-h2h-row corner-history-grid corner-history-header" style="font-weight:800;color:#FACC15;border-bottom:1px solid #51451D;"><span>Fecha</span><span>Local</span><span class="corner-h2h-value">Córners L</span><span>Visitante</span><span class="corner-h2h-value">Córners V</span><span class="corner-h2h-value">PT</span><span class="corner-h2h-value">ST</span><span class="corner-h2h-value">Total córners</span></div>'
                                                        for row in h2h_rows:
                                                            date_label = html.escape(str(row.get("Fecha") or "N/D"))
                                                            home_name = html.escape(str(row.get("Local") or "N/D"))
                                                            away_name = html.escape(str(row.get("Visitante") or "N/D"))
                                                            home_logo = html.escape(str(row.get("LocalLogo") or ""), quote=True)
                                                            away_logo = html.escape(str(row.get("VisitanteLogo") or ""), quote=True)
                                                            home_corner = row.get("Córners", "N/D").split("–")[0]
                                                            away_corner = row.get("Córners", "N/D").split("–")[-1]
                                                            corners_html += (
                                                                f'<div class="corner-h2h-row corner-history-grid"><span>{date_label}</span>'
                                                                f'<span class="h2h-team"><img src="{home_logo}" onerror="this.style.display=\'none\'">{home_name}</span>'
                                                                f'<span class="corner-h2h-value">{html.escape(str(home_corner))}</span>'
                                                                f'<span class="h2h-team"><img src="{away_logo}" onerror="this.style.display=\'none\'">{away_name}</span>'
                                                                f'<span class="corner-h2h-value">{html.escape(str(away_corner))}</span>'
                                                                f'<span class="corner-h2h-value">{html.escape(str(row.get("PrimerTiempo") if row.get("PrimerTiempo") is not None else "N/D"))}</span>'
                                                                f'<span class="corner-h2h-value">{html.escape(str(row.get("SegundoTiempo") if row.get("SegundoTiempo") is not None else "N/D"))}</span>'
                                                                f'<span class="corner-h2h-value corner-h2h-total"><span class="corner-h2h-total-label" style="display:none;">Total córners</span>{html.escape(str(row.get("Total") if row.get("Total") is not None else "N/D"))}</span></div>'
                                                            )
                                                        st.markdown(corners_html, unsafe_allow_html=True)
                                                        valid_totals = [row["Total"] for row in h2h_rows if isinstance(row.get("Total"), (int, float))]
                                                        if valid_totals:
                                                            h2h_avg = sum(valid_totals) / len(valid_totals)
                                                            st.markdown(
                                                                f"""
                                                                <div class="corner-average-pill" style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;
                                                                            margin:16px 0 18px;padding:7px 10px;
                                                                            border:1px solid #51451D;border-radius:9px;
                                                                            background:linear-gradient(135deg,#17191f,#20232b);
                                                                            width:fit-content;max-width:100%;clear:both;position:relative;">
                                                                  <span style="font-size:11px;font-weight:700;color:#FACC15;letter-spacing:.3px;">
                                                                    PROMEDIO DE CÓRNERS
                                                                  </span>
                                                                  <span style="display:inline-block;padding:4px 9px;
                                                                               border:1px solid #FACC15;border-radius:7px;
                                                                               background:#FACC15;color:#111827;
                                                                               font-size:13px;font-weight:800;line-height:1.1;">
                                                                    {h2h_avg:.2f}
                                                                  </span>
                                                                </div>
                                                                """,
                                                                unsafe_allow_html=True,
                                                            )
                                                        else:
                                                            st.caption("No hay estadísticas de córners disponibles para calcular el promedio.")
                                                    elif h2h_key in st.session_state.corner_h2h_cache:
                                                        st.caption("La API no devolvió enfrentamientos finalizados o estadísticas de córners suficientes para estos equipos.")
                                                else:
                                                    st.caption("Consulta los últimos 10 enfrentamientos finalizados; si hay menos, se mostrarán los disponibles. Las estadísticas de córners dependen de los datos que entregue la API.")

                                                if isinstance(competition_corner_average, (int, float)) and isinstance(h2h_avg, (int, float)):
                                                    raw_total_match_average = (competition_corner_average + h2h_avg) / 2
                                                    # Aplicar margen conservador de 1 córner y redondear por umbrales:
                                                    # 9.49 -> 9; 9.50 a 9.59 -> 9.5; desde 9.60 -> 10.
                                                    adjusted_corner_average = max(0.0, raw_total_match_average - 1.0)
                                                    corner_fraction = adjusted_corner_average - int(adjusted_corner_average)
                                                    if corner_fraction < 0.5:
                                                        total_match_average = int(adjusted_corner_average)
                                                    elif corner_fraction < 0.6:
                                                        total_match_average = int(adjusted_corner_average) + 0.5
                                                    else:
                                                        total_match_average = int(adjusted_corner_average) + 1
                                                    match_first_half_corners = None
                                                    match_second_half_corners = None
                                                    period_sources = []
                                                    if isinstance(competition_first_average, (int, float)) and isinstance(competition_second_average, (int, float)):
                                                        period_sources.append((competition_first_average, competition_second_average))
                                                    if period_sources:
                                                        raw_first_period = sum(pair[0] for pair in period_sources) / len(period_sources)
                                                        raw_second_period = sum(pair[1] for pair in period_sources) / len(period_sources)
                                                        raw_period_sum = raw_first_period + raw_second_period
                                                        if raw_period_sum > 0:
                                                            match_first_half_corners = round((total_match_average * raw_first_period / raw_period_sum) * 2) / 2
                                                            match_first_half_corners = min(float(total_match_average), max(0.0, match_first_half_corners))
                                                            match_second_half_corners = float(total_match_average) - match_first_half_corners
                                                    st.markdown(
                                                        f"""
                                                        <div class="corner-total-average">
                                                          <b>PROMEDIO TOTAL DE CÓRNERS PARA ESTE PARTIDO</b>
                                                          <span>{total_match_average:.2f}</span>
                                                        </div>
                                                        """,
                                                        unsafe_allow_html=True,
                                                    )

                                                pace = corner_item.get("pace")
                                                st.markdown("### 📡 Lectura en vivo")
                                                st.write(f"Minuto {current_minute if current_minute is not None else 'N/D'} · ritmo actual {pace:.2f} córners/90'." if isinstance(pace, (int, float)) else f"Minuto {current_minute if current_minute is not None else 'N/D'} · ritmo no disponible con los datos actuales.")
                                                if isinstance(current_total, (int, float)) and isinstance(current_minute, int) and current_minute > 0:
                                                    live_projection = current_total * 90 / max(1, current_minute)
                                                    hist_rate = None
                                                    if isinstance(history.get("home_corners_for"), (int, float)) and isinstance(history.get("away_corners_for"), (int, float)):
                                                        hist_rate = float(history["home_corners_for"]) + float(history["away_corners_for"])
                                                    projected = 0.55 * hist_rate + 0.45 * live_projection if hist_rate is not None else live_projection
                                                    remaining_expected = max(0.0, projected - current_total)
                                                    st.markdown(f'<div class="signal-card"><div class="signal-kicker">Proyección exploratoria</div><div class="signal-title">Córners totales estimados al final</div><div class="signal-pick">{projected:.1f}</div><div class="signal-meta">Actuales: {current_total} · restantes estimados: {remaining_expected:.1f} · no es una probabilidad calibrada.</div></div>', unsafe_allow_html=True)

                                                    live_rows = st.session_state.get("live_odds_by_fixture", {}).get(str(match_id), [])
                                                    corner_options = []
                                                    remaining_mean = max(0.05, remaining_expected * 0.70)
                                                    import re
                                                    for odds_row in live_rows:
                                                        market_label = classify_market(odds_row)
                                                        odd = odds_row.get("odd")
                                                        if not market_label or "córner" not in market_label.casefold() or not isinstance(odd, (int, float)):
                                                            continue
                                                        line_match = re.search(r"(\d+(?:[.,]\d+)?)", market_label)
                                                        if not line_match:
                                                            continue
                                                        line = float(line_match.group(1).replace(",", "."))
                                                        if market_label.startswith("Más de "):
                                                            needed = max(0, int(line - current_total + 0.5))
                                                            probability = poisson_at_least(remaining_mean, needed)
                                                        elif market_label.startswith("Menos de "):
                                                            max_remaining = int(line - current_total)
                                                            probability = sum(poisson_pmf(remaining_mean, n) for n in range(max_remaining + 1)) if max_remaining >= 0 else 0.0
                                                        else:
                                                            continue
                                                        edge = probability - 1.0 / float(odd)
                                                        if 0 < probability < 1 and edge >= 0.02:
                                                            corner_options.append({"market": market_label, "odd": float(odd), "prob": probability, "edge": edge, "bookmaker": odds_row.get("bookmaker", "Casa no identificada")})
                                                    main_options = [option for option in corner_options if 1.25 <= option["odd"] < 1.60]
                                                    risk_options = [option for option in corner_options if option["odd"] >= 1.60]
                                                    st.markdown('<div class="tip-section-heading"><span class="tip-heading-icon">◈</span><span>TIP PRINCIPAL</span></div>', unsafe_allow_html=True)
                                                    if main_options:
                                                        chosen = max(main_options, key=lambda option: option["edge"])
                                                        st.markdown(f'<div class="tip-card"><div class="tip-card-title">{html.escape(chosen["market"])}</div><div class="tip-card-meta">{html.escape(chosen["bookmaker"])} · probabilidad exploratoria {chosen["prob"]:.1%} · ventaja estimada {chosen["edge"]:.1%}</div></div>', unsafe_allow_html=True)
                                                    else:
                                                        st.markdown('<div class="tip-card tip-card-empty"><div class="tip-card-title">Sin oportunidad confirmada por ahora</div><div class="tip-card-meta">Se requiere respaldo estadístico suficiente.</div></div>', unsafe_allow_html=True)
                                                    st.markdown('<div class="tip-section-heading risk-heading"><span class="tip-heading-icon">⌁</span><span>TIP DE ALTO RIESGO</span></div>', unsafe_allow_html=True)
                                                    if risk_options:
                                                        chosen_risk = max(risk_options, key=lambda option: option["edge"])
                                                        st.markdown(f'<div class="tip-card risk-tip-card"><div class="tip-card-title">{html.escape(chosen_risk["market"])}</div><div class="tip-card-meta">{html.escape(chosen_risk["bookmaker"])} · probabilidad exploratoria {chosen_risk["prob"]:.1%} · ventaja estimada {chosen_risk["edge"]:.1%}</div></div>', unsafe_allow_html=True)
                                                    else:
                                                        st.markdown('<div class="tip-card risk-tip-card tip-card-empty"><div class="tip-card-title">Sin oportunidad confirmada por ahora</div><div class="tip-card-meta">Se requiere respaldo estadístico suficiente.</div></div>', unsafe_allow_html=True)
                                                    goals = match.get("goals") or {}
                                                    pattern_stats = st.session_state.stats_cache.get(str(match_id), [])
                                                    pattern_teams = match.get("teams") or {}
                                                    patterns = numerology_context(
                                                        goals.get("home"), goals.get("away"), home_c, away_c,
                                                        safe_stat_for_team(pattern_stats, "Yellow Cards", (pattern_teams.get("home") or {}).get("id")),
                                                        safe_stat_for_team(pattern_stats, "Yellow Cards", (pattern_teams.get("away") or {}).get("id")),
                                                    )
                                            elif corner_item:
                                                st.warning(f"No se pudo cargar el análisis de córners: {corner_item.get('error')}")
                                            else:
                                                st.info("Primero pulsa «Escanear todos los partidos en vivo» para calcular promedios históricos, ritmo en vivo y tip principal de córners.")

            else:
                st.info("No hay partidos activos en las ligas seleccionadas.")

    # Al regresar desde un análisis, recuperar el scroll del encuentro seleccionado.
    _return_fixture_id = st.session_state.pop("return_to_fixture_id", None)
    if _return_fixture_id:
        st.components.v1.html(
            f"""
            <script>
            (() => {{
              const targetId = "st-key-live_match_{_return_fixture_id}";
              let attempts = 0;
              const restore = () => {{
                try {{
                  const doc = window.parent.document;
                  const node = doc.querySelector('[class*="' + targetId + '"]');
                  if (node) {{
                    node.scrollIntoView({{behavior:"instant", block:"center", inline:"nearest"}});
                    node.style.transition = "box-shadow .35s ease";
                    node.style.boxShadow = "0 0 0 2px #FACC15";
                    setTimeout(() => {{ try {{ node.style.boxShadow = ""; }} catch(e) {{}} }}, 1800);
                    return;
                  }}
                }} catch(e) {{}}
                if (++attempts < 12) setTimeout(restore, 180);
              }};
              restore();
            }})();
            </script>
            """,
            height=1,
            scrolling=False,
        )

    # Se retira el resumen de sesión de la pantalla principal.
    stats_limit = 20
    # manual_scan se obtiene del botón principal situado bajo los controles de sonido.
    now_epoch = int(datetime.now().timestamp())
    auto_scan_due = (
        st.session_state.auto_refresh_enabled
        and should_refresh
        and now_epoch - int(st.session_state.last_auto_market_scan_epoch) >= 120
    )
    if manual_scan or auto_scan_due:
        st.session_state.last_auto_market_scan_epoch = now_epoch
        scan_api_calls_start = st.session_state.api_request_count
        # Refresh only live-fixture statistics for a new scan. Preserve historical
        # statistics (for example corner H2H rows) so they are not fetched repeatedly.
        live_fixture_ids_for_refresh = {
            str(((item.get("fixture") or {}).get("id") or ""))
            for item in st.session_state.get("live_fixtures", [])
            if (item.get("fixture") or {}).get("id") is not None
        }
        # Conservar estadísticas válidas entre escaneos, pero permitir reintentar
        # respuestas vacías: pueden deberse a que el proveedor aún no las publicó.
        if not manual_scan:
            for cached_stats_key in list(st.session_state.stats_cache):
                if str(cached_stats_key) in live_fixture_ids_for_refresh:
                    st.session_state.stats_cache.pop(cached_stats_key, None)
        else:
            for cached_stats_key, cached_stats_value in list(st.session_state.stats_cache.items()):
                if str(cached_stats_key).isdigit() and not cached_stats_value:
                    st.session_state.stats_cache.pop(cached_stats_key, None)
        st.session_state.goal_scan_results = []
        st.session_state.corner_scan_results = []
        # Consultar un lote acotado por escaneo. Los partidos fuera del lote quedan
        # pendientes (no se marcan como vacíos) y podrán entrar en escaneos posteriores.
        stats_fetch_progress = st.empty()
        effective_stats_limit = min(stats_limit, 5) if auto_scan_due and not manual_scan else stats_limit
        # Rotar el lote para que los partidos que quedan al final de la lista
        # también reciban estadísticas en escaneos posteriores.
        stats_cursor = int(st.session_state.get("live_stats_batch_cursor", 0) or 0)
        if filtered:
            stats_cursor %= len(filtered)
            rotated_fixtures = filtered[stats_cursor:] + filtered[:stats_cursor]
            stats_fixtures = rotated_fixtures[:effective_stats_limit]
            st.session_state.live_stats_batch_cursor = (stats_cursor + len(stats_fixtures)) % len(filtered)
        else:
            stats_fixtures = []
            st.session_state.live_stats_batch_cursor = 0
        stats_queries_attempted = 0
        stats_rate_limited = False
        for stats_fixture in stats_fixtures:
            stats_fixture_id = (stats_fixture.get("fixture") or {}).get("id")
            if stats_fixture_id is None:
                continue
            stats_cache_key = str(stats_fixture_id)
            if stats_cache_key in st.session_state.stats_cache:
                continue
            try:
                stats_queries_attempted += 1
                stats_payload = api_get("fixtures/statistics", {"fixture": stats_fixture_id})
                stats_response = stats_payload.get("response") or []
                st.session_state.stats_cache[stats_cache_key] = stats_response
            except Exception as stats_exc:
                # Cachear el fallo solo en esta ronda para impedir una segunda llamada
                # desde el análisis de córners; el siguiente escaneo manual lo reintentará.
                st.session_state.stats_cache[stats_cache_key] = []
                if "HTTP 429" in str(stats_exc):
                    stats_rate_limited = True
                    st.warning("Se alcanzó el límite de consultas de la API durante la carga de estadísticas. El resto de partidos queda pendiente para el siguiente escaneo.")
                    break
        stats_fetch_progress.empty()
        st.session_state.last_scan_stats_matches = stats_queries_attempted
        st.session_state.last_scan_stats_pending = max(0, len(filtered) - len(stats_fixtures))
        st.session_state.last_scan_stats_rate_limited = stats_rate_limited

        # Catálogos de referencia propios del mercado EN VIVO (cacheados 24 h).
        catalog_now = datetime.now().timestamp()
        catalog_last = float(st.session_state.get("live_odds_catalog_epoch", 0) or 0)
        if get_api_key() and catalog_now - catalog_last >= 86400:
            try:
                _live_bets_payload = api_get("odds/live/bets")
                _live_bets_items = _live_bets_payload.get("response") or []
                st.session_state.live_odds_bets_catalog_count = len(_live_bets_items)
                st.session_state.live_odds_bets_catalog_sample = [
                    str(_x.get("name") or _x.get("id") or "") for _x in _live_bets_items[:30]
                ]
                st.session_state.live_odds_bets_catalog_errors = _live_bets_payload.get("errors") or {}
            except Exception as _catalog_exc:
                st.session_state.live_odds_bets_catalog_errors = str(_catalog_exc)
            try:
                _bookmakers_payload = api_get("odds/bookmakers")
                _bookmakers_items = _bookmakers_payload.get("response") or []
                st.session_state.live_odds_bookmakers_count = len(_bookmakers_items)
                st.session_state.live_odds_bookmakers_sample = [
                    str(_x.get("name") or _x.get("id") or "") for _x in _bookmakers_items[:30]
                ]
                st.session_state.live_odds_bookmakers_errors = _bookmakers_payload.get("errors") or {}
            except Exception as _bookmakers_exc:
                st.session_state.live_odds_bookmakers_errors = str(_bookmakers_exc)
            st.session_state.live_odds_catalog_epoch = catalog_now

        # Refresh global live odds at most once per 60 seconds.
        odds_now = datetime.now().timestamp()
        last_odds_epoch = float(st.session_state.get("live_odds_last_fetch_epoch", 0) or 0)
        if get_api_key() and odds_now - last_odds_epoch >= 60:
            try:
                odds_payload = api_get("odds/live")
                odds_response_items = odds_payload.get("response") or []
                st.session_state.live_odds_api_response_count = len(odds_response_items)
                st.session_state.live_odds_api_errors = odds_payload.get("errors") or {}
                st.session_state.live_odds_api_fixture_ids = [
                    str(((item.get("fixture") or {}).get("id")))
                    for item in odds_response_items
                    if (item.get("fixture") or {}).get("id") is not None
                ]
                st.session_state.live_odds_by_fixture = extract_live_odds(odds_payload)
                st.session_state.live_odds_last_fetch = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                st.session_state.live_odds_last_fetch_epoch = odds_now
                st.session_state.live_odds_error = ""
            except Exception as odds_exc:
                st.session_state.live_odds_error = str(odds_exc)
                st.session_state.live_odds_api_response_count = 0
                st.session_state.live_odds_api_errors = {}
                st.session_state.live_odds_api_fixture_ids = []
        if "live_odds_by_fixture" not in st.session_state:
            st.session_state.live_odds_by_fixture = {}

        # Verificar cobertura oficial de cuotas por competición/temporada.
        # La presencia de una casa o mercado en los catálogos no garantiza cobertura
        # para cada liga; esta consulta permite distinguirlo sin repetir llamadas.
        _coverage_cache = st.session_state.get("live_odds_league_coverage_cache", {})
        _coverage_now = datetime.now().timestamp()
        _coverage_details = []
        _coverage_keys_seen = set()
        for _coverage_fixture in filtered:
            _coverage_league = _coverage_fixture.get("league") or {}
            _coverage_league_id = _coverage_league.get("id")
            _coverage_season = _coverage_league.get("season")
            if not _coverage_league_id or not _coverage_season:
                continue
            _coverage_key = f"{_coverage_league_id}:{_coverage_season}"
            if _coverage_key in _coverage_keys_seen:
                continue
            _coverage_keys_seen.add(_coverage_key)
            _cached_coverage = _coverage_cache.get(_coverage_key) or {}
            if _coverage_now - float(_cached_coverage.get("checked_epoch", 0) or 0) >= 86400:
                try:
                    _league_payload = api_get("leagues", {"id": _coverage_league_id, "season": _coverage_season})
                    _league_items = _league_payload.get("response") or []
                    _coverage_value = None
                    if _league_items:
                        _coverage_value = (((_league_items[0].get("seasons") or [{}])[0].get("coverage") or {}).get("odds"))
                    _cached_coverage = {
                        "league_id": _coverage_league_id,
                        "season": _coverage_season,
                        "league_name": _coverage_league.get("name"),
                        "country": _coverage_league.get("country"),
                        "odds_coverage": _coverage_value,
                        "api_errors": _league_payload.get("errors") or {},
                        "checked_epoch": _coverage_now,
                    }
                    _coverage_cache[_coverage_key] = _cached_coverage
                except Exception as _coverage_exc:
                    _cached_coverage = {
                        "league_id": _coverage_league_id,
                        "season": _coverage_season,
                        "league_name": _coverage_league.get("name"),
                        "country": _coverage_league.get("country"),
                        "odds_coverage": None,
                        "api_errors": str(_coverage_exc),
                        "checked_epoch": _coverage_now,
                    }
                    _coverage_cache[_coverage_key] = _cached_coverage
            _coverage_details.append(_cached_coverage)
        st.session_state.live_odds_league_coverage_cache = _coverage_cache
        st.session_state.live_odds_league_coverage_details = _coverage_details

        global_odds_index = st.session_state.get("live_odds_by_fixture") or {}
        # Consulta adicional por competición: odds/live admite el filtro league.
        # Se cachea 60 s para evitar repetir llamadas en cada rerun de Streamlit.
        league_odds_cache = st.session_state.get("live_odds_by_league_cache", {}) or {}
        league_odds_details = []
        league_odds_calls = 0
        league_odds_errors = []
        league_odds_now = datetime.now().timestamp()
        league_ids_seen = set()
        for _league_fixture in filtered:
            _league_data = _league_fixture.get("league") or {}
            _league_id = _league_data.get("id")
            if not _league_id or str(_league_id) in league_ids_seen:
                continue
            _league_key = str(_league_id)
            league_ids_seen.add(_league_key)
            _cached_league_odds = league_odds_cache.get(_league_key) or {}
            if league_odds_now - float(_cached_league_odds.get("fetched_epoch", 0) or 0) >= 60:
                try:
                    _league_odds_payload = api_get("odds/live", {"league": _league_id})
                    _league_odds_items = _league_odds_payload.get("response") or []
                    _league_odds_rows = extract_live_odds(_league_odds_payload)
                    _league_bookmakers = sum(
                        len(_item.get("bookmakers") or []) for _item in _league_odds_items
                    )
                    _league_bet_values = sum(
                        len(_bet.get("values") or [])
                        for _item in _league_odds_items
                        for _bookmaker in (_item.get("bookmakers") or [])
                        for _bet in (_bookmaker.get("bets") or [])
                    )
                    _cached_league_odds = {
                        "fetched_epoch": league_odds_now,
                        "response_items": len(_league_odds_items),
                        "bookmakers": _league_bookmakers,
                        "bet_values": _league_bet_values,
                        "rows": _league_odds_rows,
                        "api_errors": _league_odds_payload.get("errors") or {},
                    }
                    league_odds_calls += 1
                except Exception as _league_odds_exc:
                    _cached_league_odds = {
                        "fetched_epoch": league_odds_now,
                        "response_items": 0,
                        "bookmakers": 0,
                        "bet_values": 0,
                        "rows": {},
                        "api_errors": f"{type(_league_odds_exc).__name__}: {_league_odds_exc}",
                    }
                    league_odds_calls += 1
                    league_odds_errors.append(f"{_league_key}: {_cached_league_odds['api_errors']}")
                league_odds_cache[_league_key] = _cached_league_odds
            _league_fixture_ids = {
                str((item.get("fixture") or {}).get("id"))
                for item in filtered
                if str(((item.get("league") or {}).get("id") or "")) == _league_key
            }
            _league_rows = _cached_league_odds.get("rows") or {}
            _matched_fixture_ids = []
            _parsed_league_rows = 0
            for _returned_fixture_id, _returned_rows in _league_rows.items():
                _returned_fixture_key = str(_returned_fixture_id)
                if _returned_fixture_key in _league_fixture_ids and _returned_rows:
                    if not global_odds_index.get(_returned_fixture_key):
                        global_odds_index[_returned_fixture_key] = list(_returned_rows)
                    _matched_fixture_ids.append(_returned_fixture_key)
                    _parsed_league_rows += len(_returned_rows)
            league_odds_details.append({
                "league_id": _league_key,
                "league_name": _league_data.get("name") or "Competición",
                "fixtures_scanned": len(_league_fixture_ids),
                "response_items": int(_cached_league_odds.get("response_items", 0) or 0),
                "matched_fixtures": len(_matched_fixture_ids),
                "matched_fixture_ids": _matched_fixture_ids[:20],
                "bookmakers": int(_cached_league_odds.get("bookmakers", 0) or 0),
                "bet_values": int(_cached_league_odds.get("bet_values", 0) or 0),
                "parsed_rows": _parsed_league_rows,
                "api_errors": _cached_league_odds.get("api_errors") or {},
            })
        st.session_state.live_odds_by_league_cache = league_odds_cache
        st.session_state.live_odds_league_calls = league_odds_calls
        st.session_state.live_odds_league_details = league_odds_details
        st.session_state.live_odds_league_errors = league_odds_errors

        # Fallback individual por partido: se ejecuta en CADA escaneo, incluso si
        # la consulta global fue reutilizada desde el refresco previo del encabezado.
        targeted_calls = 0
        targeted_errors = []
        targeted_response_details = []
        targeted_odds_cache = st.session_state.get("live_odds_targeted_cache", {}) or {}
        targeted_now = datetime.now().timestamp()
        for _live_fixture in filtered:
            _live_fixture_id = str(((_live_fixture.get("fixture") or {}).get("id") or "")).strip()
            _live_teams = _live_fixture.get("teams") or {}
            _live_home = str(((_live_teams.get("home") or {}).get("name")) or "Local N/D")
            _live_away = str(((_live_teams.get("away") or {}).get("name")) or "Visitante N/D")
            if not _live_fixture_id:
                targeted_response_details.append({
                    "fixture_id": "sin ID",
                    "home": _live_home,
                    "away": _live_away,
                    "source": "validación local",
                    "exception": "El partido no contiene fixture_id; no se pudo consultar su cuota.",
                })
                continue
            _existing_global_rows = global_odds_index.get(_live_fixture_id) or []
            if _existing_global_rows:
                targeted_response_details.append({
                    "fixture_id": _live_fixture_id,
                    "home": _live_home,
                    "away": _live_away,
                    "source": "respuesta global/caché",
                    "response_items": 1,
                    "bookmakers": sum(1 for _r in _existing_global_rows if _r.get("bookmaker_verified") is True),
                    "bet_values": len(_existing_global_rows),
                    "parsed_rows": len(_existing_global_rows),
                    "note": "Se omitió la consulta individual porque ya había cuotas asociadas a este partido.",
                })
                continue
            _cached_targeted = targeted_odds_cache.get(_live_fixture_id) or {}
            if targeted_now - float(_cached_targeted.get("fetched_epoch", 0) or 0) < 60:
                _cached_rows = _cached_targeted.get("rows") or []
                if _cached_rows:
                    global_odds_index[_live_fixture_id] = list(_cached_rows)
                if _cached_targeted.get("detail"):
                    targeted_response_details.append(_cached_targeted["detail"])
                continue
            try:
                _targeted_payload = api_get("odds/live", {"fixture": _live_fixture_id})
                targeted_calls += 1
                _targeted_items = _targeted_payload.get("response") or []
                _targeted_rows = extract_live_odds(_targeted_payload)
                _targeted_bookmakers = sum(
                    len(_item.get("bookmakers") or [])
                    for _item in _targeted_items if isinstance(_item, dict)
                )
                # /odds/live devuelve mercados en odds[].values[], no solo bookmakers[].bets[].
                _targeted_bets = sum(
                    len(_market.get("values") or [])
                    for _item in _targeted_items if isinstance(_item, dict)
                    for _market in (_item.get("odds") or [])
                    if isinstance(_market, dict)
                ) + sum(
                    len(_bet.get("values") or [])
                    for _item in _targeted_items if isinstance(_item, dict)
                    for _bookmaker in (_item.get("bookmakers") or [])
                    if isinstance(_bookmaker, dict)
                    for _bet in (_bookmaker.get("bets") or [])
                    if isinstance(_bet, dict)
                )
                # Diagnóstico estructural sin guardar ni mostrar la clave API ni el payload completo.
                _targeted_item_summaries = []
                for _raw_item in _targeted_items[:3]:
                    if not isinstance(_raw_item, dict):
                        _targeted_item_summaries.append({"item_type": type(_raw_item).__name__})
                        continue
                    _raw_fixture = _raw_item.get("fixture") or {}
                    _raw_league = _raw_item.get("league") or {}
                    _raw_teams = _raw_item.get("teams") or {}
                    _raw_status = _raw_item.get("status") or {}
                    _raw_bookmakers = _raw_item.get("bookmakers") or []
                    _targeted_item_summaries.append({
                        "returned_fixture_id": str(_raw_fixture.get("id") or ""),
                        "response_keys": sorted(str(_key) for _key in _raw_item.keys())[:24],
                        "bookmaker_count": len(_raw_bookmakers) if isinstance(_raw_bookmakers, list) else None,
                        "live_market_count": len(_raw_item.get("odds") or []) if isinstance(_raw_item.get("odds"), list) else 0,
                        "live_value_count": sum(
                            len(_market.get("values") or [])
                            for _market in (_raw_item.get("odds") or [])
                            if isinstance(_market, dict)
                        ) if isinstance(_raw_item.get("odds"), list) else 0,
                        "live_market_names": [
                            str(_market.get("name") or "")
                            for _market in (_raw_item.get("odds") or [])[:8]
                            if isinstance(_market, dict)
                        ] if isinstance(_raw_item.get("odds"), list) else [],
                        "bookmaker_names": [
                            str(_book.get("name") or _book.get("id") or "")
                            for _book in _raw_bookmakers[:8] if isinstance(_book, dict)
                        ] if isinstance(_raw_bookmakers, list) else [],
                        "status": {
                            "stopped": _raw_status.get("stopped"),
                            "blocked": _raw_status.get("blocked"),
                            "finished": _raw_status.get("finished"),
                        },
                        "league": str(_raw_league.get("name") or ""),
                        "home": str(((_raw_teams.get("home") or {}).get("name")) or ""),
                        "away": str(((_raw_teams.get("away") or {}).get("name")) or ""),
                    })
                _targeted_detail = {
                    "fixture_id": _live_fixture_id,
                    "home": _live_home,
                    "away": _live_away,
                    "source": "consulta individual /odds/live",
                    "response_items": len(_targeted_items),
                    "bookmakers": _targeted_bookmakers,
                    "bet_values": _targeted_bets,
                    "parsed_rows": len(_targeted_rows.get(_live_fixture_id, [])),
                    "response_item_summaries": _targeted_item_summaries,
                    "api_errors": _targeted_payload.get("errors") or {},
                }
                targeted_response_details.append(_targeted_detail)
                targeted_odds_cache[_live_fixture_id] = {
                    "fetched_epoch": targeted_now,
                    "rows": list(_targeted_rows.get(_live_fixture_id, [])),
                    "detail": _targeted_detail,
                }
                if _targeted_rows.get(_live_fixture_id):
                    global_odds_index.setdefault(_live_fixture_id, []).extend(_targeted_rows[_live_fixture_id])
                _targeted_api_errors = _targeted_payload.get("errors") or {}
                if _targeted_api_errors:
                    targeted_errors.append(f"{_live_fixture_id}: {_targeted_api_errors}")
            except Exception as _targeted_exc:
                targeted_calls += 1
                targeted_errors.append(f"{_live_fixture_id}: {type(_targeted_exc).__name__}: {_targeted_exc}")
                _targeted_detail = {
                    "fixture_id": _live_fixture_id,
                    "home": _live_home,
                    "away": _live_away,
                    "source": "consulta individual /odds/live",
                    "exception": f"{type(_targeted_exc).__name__}: {_targeted_exc}",
                }
                targeted_response_details.append(_targeted_detail)
                targeted_odds_cache[_live_fixture_id] = {
                    "fetched_epoch": targeted_now,
                    "rows": [],
                    "detail": _targeted_detail,
                }
        st.session_state.live_odds_targeted_cache = targeted_odds_cache
        st.session_state.live_odds_by_fixture = global_odds_index
        st.session_state.live_odds_targeted_calls = targeted_calls
        st.session_state.live_odds_targeted_errors = targeted_errors
        st.session_state.live_odds_targeted_details = targeted_response_details

        # Compare current scores with the previous completed scan without extra API calls.
        previous_scores = st.session_state.get("previous_scan_scores", {})
        current_scores = {}
        progress = st.empty()
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
        corner_progress = st.empty()
        for idx, fixture in enumerate(corner_fixtures):
            fixture_id = (fixture.get("fixture") or {}).get("id")
            if fixture_id is None:
                corner_results.append({
                    "fixture": fixture,
                    "error": "El partido no tiene un ID de fixture válido; se omite la consulta de estadísticas.",
                })
                continue
            try:
                cache_key = str(fixture_id)
                # No hacer consultas ocultas fuera del lote priorizado del escáner.
                # Si el partido aún no tiene estadísticas cargadas, queda pendiente.
                if cache_key not in st.session_state.stats_cache:
                    corner_results.append({
                        "fixture": fixture,
                        "error": "Estadísticas pendientes de consulta en el siguiente lote del escáner.",
                    })
                    continue
                stats = st.session_state.stats_cache[cache_key]
                fixture_teams = fixture.get("teams") or {}
                home_team_id = (fixture_teams.get("home") or {}).get("id")
                away_team_id = (fixture_teams.get("away") or {}).get("id")
                home_c = safe_stat_for_team(stats, "Corner Kicks", home_team_id)
                away_c = safe_stat_for_team(stats, "Corner Kicks", away_team_id)
                home_shots = safe_stat_for_team(stats, "Total Shots", home_team_id)
                away_shots = safe_stat_for_team(stats, "Total Shots", away_team_id)
                home_shots_on = safe_stat_for_team(stats, "Shots on Goal", home_team_id)
                away_shots_on = safe_stat_for_team(stats, "Shots on Goal", away_team_id)
                home_possession = safe_stat_for_team(stats, "Ball Possession", home_team_id)
                away_possession = safe_stat_for_team(stats, "Ball Possession", away_team_id)
                home_yellow = safe_stat_for_team(stats, "Yellow Cards", home_team_id)
                away_yellow = safe_stat_for_team(stats, "Yellow Cards", away_team_id)
                home_red = safe_stat_for_team(stats, "Red Cards", home_team_id)
                away_red = safe_stat_for_team(stats, "Red Cards", away_team_id)
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
        # Load historical venue averages during the global scan, as in main.
        # The goals and corners panels both consume this shared result, so they
        # must not remain pending until the user opens a separate history button.
        history_calls_before = st.session_state.api_request_count
        history_cache = st.session_state.setdefault("automatic_history_cache", {})
        history_cache["_automatic_history_stats_calls"] = 0
        history_cache["_automatic_history_team_fixture_calls"] = 0
        history_cache.pop("_automatic_history_rate_limited", None)

        # Give priority to the match currently opened by the user.
        selected_detail_for_history = st.session_state.get("selected_match_detail") or {}
        selected_history_fixture_id = str(selected_detail_for_history.get("fixture_id") or "")
        corner_results.sort(
            key=lambda item: 0 if str(((item.get("fixture") or {}).get("fixture") or {}).get("id") or "") == selected_history_fixture_id else 1
        )

        for corner_item in corner_results:
            try:
                # Give each fixture its own bounded historical-statistics budget.
                # A shared scan-wide counter starved later fixtures of corner samples,
                # leaving competition averages as N/D even when their history existed.
                history_budget = 8 if auto_scan_due and not manual_scan else 20
                corner_item["automatic_history"] = build_automatic_history(
                    corner_item["fixture"],
                    api_get=api_get,
                    cache=history_cache,
                    stats_budget=history_budget,
                    live_corner_finalizer=lambda completed_fixture, final_stats: (
                        finalize_live_corner_fixture(LIVE_CORNER_CAPTURE_DB, completed_fixture, final_stats)
                    ),
                )
            except Exception as history_exc:
                corner_item["automatic_history"] = {
                    "available": False,
                    "pending": True,
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

        # Marcar como completada la actualización solicitada desde los botones de la vista individual.
        if internal_scan_requested:
            _feedback = st.session_state.get("analysis_scan_feedback") or {}
            if _feedback.get("action") == "refresh":
                _feedback["state"] = "done"
                st.session_state["analysis_scan_feedback"] = _feedback
            st.rerun()

        # Las cuotas se actualizan en bloque durante el refresco automático, no por partido.

        st.session_state.previous_scan_scores = current_scores

        # Auditable signal log: avoid duplicate rows when Streamlit reruns the same scan.
        signal_rows = st.session_state.get("signal_rows", [])
        existing_keys = {
            (str(row.get("fixture_id")), str(row.get("market")), str(row.get("minute")),
             str(row.get("score_home")), str(row.get("score_away")))
            for row in signal_rows
        }
        new_signal_rows = []
        # Registro de pronósticos: conserva candidatos del modelo aunque no tengan
        # cuota exacta o no superen los filtros de publicación.
        forecast_rows_to_persist = []
        odds_index_for_scan = st.session_state.get("live_odds_by_fixture", {}) or {}
        odds_rows_total = sum(len(rows or []) for rows in odds_index_for_scan.values())
        fixtures_with_odds = sum(
            1 for fixture in filtered
            if odds_index_for_scan.get(str((fixture.get("fixture") or {}).get("id")), [])
        )
        scan_diagnostics = {
            "fixtures_scanned": len(goal_results_with_context),
            "goal_estimates_available": sum(1 for _, estimate, _, _ in goal_results_with_context if estimate.get("available")),
            "goal_model_candidates": 0,
            "goal_candidates_without_quotes": 0,
            "goal_candidates_without_exact_quote_or_below_filters": 0,
            "goal_candidates_evaluated": 0,
            "goal_candidates_model_not_validated": 0,
            "eligible_goal_signals": 0,
            "corner_stats_ready": 0,
            "corner_stats_pending": 0,
            "corner_probability_candidates": 0,
            "corner_candidates_without_quotes": 0,
            "corner_candidates_without_exact_quote_or_below_filters": 0,
            "corner_candidates_evaluated": 0,
            "eligible_corner_signals": 0,
            "odds_fixtures_returned": len(odds_index_for_scan),
            "odds_rows_returned": odds_rows_total,
            "fixtures_with_odds": fixtures_with_odds,
            "fixtures_without_odds": max(0, len(filtered) - fixtures_with_odds),
            "odds_api_response_count": int(st.session_state.get("live_odds_api_response_count", 0) or 0),
            "odds_api_fixture_ids": st.session_state.get("live_odds_api_fixture_ids", []),
            "odds_api_errors": st.session_state.get("live_odds_api_errors", {}),
            "odds_targeted_calls": int(st.session_state.get("live_odds_targeted_calls", 0) or 0),
            "odds_targeted_errors": st.session_state.get("live_odds_targeted_errors", []),
            "odds_targeted_details": st.session_state.get("live_odds_targeted_details", []),
            "odds_league_calls": int(st.session_state.get("live_odds_league_calls", 0) or 0),
            "odds_league_details": st.session_state.get("live_odds_league_details", []),
            "odds_league_errors": st.session_state.get("live_odds_league_errors", []),
            "odds_league_coverage_details": st.session_state.get("live_odds_league_coverage_details", []),
            "odds_live_bets_catalog_count": int(st.session_state.get("live_odds_bets_catalog_count", 0) or 0),
            "odds_live_bets_catalog_sample": st.session_state.get("live_odds_bets_catalog_sample", []),
            "odds_live_bets_catalog_errors": st.session_state.get("live_odds_bets_catalog_errors", {}),
            "odds_bookmakers_catalog_count": int(st.session_state.get("live_odds_bookmakers_count", 0) or 0),
            "odds_bookmakers_catalog_sample": st.session_state.get("live_odds_bookmakers_sample", []),
            "odds_bookmakers_catalog_errors": st.session_state.get("live_odds_bookmakers_errors", {}),
            "odds_last_fetch": st.session_state.get("live_odds_last_fetch"),
            "odds_error": st.session_state.get("live_odds_error", ""),
            "corner_model_status": "Modelo exploratorio conectado al evaluador central; requiere cuota real del mercado exacto y EV mínimo del 2 %. No equivale a un modelo calibrado.",
        }
        for _corner_item in corner_results:
            if _corner_item.get("error"):
                scan_diagnostics["corner_stats_pending"] += 1
            elif isinstance(_corner_item.get("home_corners"), (int, float)) and isinstance(_corner_item.get("away_corners"), (int, float)):
                scan_diagnostics["corner_stats_ready"] += 1

        # GOLES: contar y evaluar cada candidato en cada escaneo, incluso si su
        # fila ya existe en el historial. Solo se encola una fila nueva una vez.
        for fixture, estimate, tips, context in goal_results_with_context:
            scan_diagnostics["goal_model_candidates"] += len(tips or [])
            for market, probability in tips or []:
                fixture_data = fixture.get("fixture") or {}
                goals_data = fixture.get("goals") or {}
                fixture_id = fixture_data.get("id")
                recorded_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
                row = {
                    "recorded_at": recorded_at,
                    "fixture_id": fixture_id,
                    "league_id": (fixture.get("league") or {}).get("id"),
                    "league": (fixture.get("league") or {}).get("name"),
                    "home": ((fixture.get("teams") or {}).get("home") or {}).get("name"),
                    "away": ((fixture.get("teams") or {}).get("away") or {}).get("name"),
                    "phase": "live",
                    "minute": context.get("elapsed"),
                    "score_home": goals_data.get("home"),
                    "score_away": goals_data.get("away"),
                    "market": market,
                    "market_type": classify_goal_tip_market(market),
                    "selection": str(market),
                    "probability": round(float(probability), 4),
                    "estimated_probability_exploratory": round(float(probability), 4),
                    "model_id": "estimate_live_goal_markets",
                    "model_version": "exploratory-poisson-v1",
                    "source": "football_lab_live_scanner",
                    "snapshot_id": ":".join(str(value) for value in (
                        fixture_id, context.get("elapsed"), goals_data.get("home"), goals_data.get("away"),
                    )),
                    "context_status": context.get("context_status"),
                    "corners_total": context.get("corners_total"),
                    "shots_total": context.get("shots_total"),
                    "shots_on_total": context.get("shots_on_total"),
                    "red_cards_total": context.get("red_cards_total"),
                    "final_score": "",
                    "outcome": "",
                    "outcome_verified": "",
                }
                normalized_row = normalize_prediction_record(row)
                row.update({
                    "schema_version": normalized_row["schema_version"],
                    "prediction_id": normalized_row["prediction_id"],
                    "timestamp_status": normalized_row["timestamp_status"],
                })
                row_key = (str(row["fixture_id"]), str(row["market"]), str(row["minute"]),
                           str(row["score_home"]), str(row["score_away"]))
                odds_rows_for_fixture = odds_index_for_scan.get(str(fixture_id), [])
                scan_diagnostics["goal_candidates_evaluated"] += 1
                forecast_rows_to_persist.append(dict(row))
                # The current league-average Poisson estimator is exploratory,
                # not calibrated. Keep its analysis visible, but never promote it
                # to an automatic betting signal until validation is approved.
                if estimate.get("signal_eligible") is not True:
                    scan_diagnostics["goal_candidates_model_not_validated"] += 1
                    if row_key not in existing_keys:
                        existing_keys.add(row_key)
                    continue
                if not odds_rows_for_fixture:
                    scan_diagnostics["goal_candidates_without_quotes"] += 1
                verified_odds = match_goal_tip_to_live_odds(
                    str(market), float(probability), odds_rows_for_fixture
                )
                if verified_odds:
                    _opportunity = evaluate_opportunity({
                        "market": classify_goal_tip_market(market),
                        "selection": str(market),
                        "probability": float(probability),
                        "odds": float(verified_odds["odd"]),
                        "odds_verified": True,
                        "fixture_id": fixture_id,
                        "fixture": f"{row.get('home') or 'Local'} vs {row.get('away') or 'Visitante'}",
                        "minute": row.get("minute"),
                        "score": f"{row.get('score_home', '?')}-{row.get('score_away', '?')}",
                        "bookmaker": str(verified_odds.get("bookmaker") or "Referencia API-Football LIVE (casa no especificada)"),
                        "source": "api-football-live-odds",
                    }, min_ev=0.02, min_odds=1.35, max_odds=10.0)
                    if _opportunity.get("eligible"):
                        row.update({
                            "verified_live_odd": float(verified_odds["odd"]),
                            "verified_bookmaker": str(verified_odds.get("bookmaker") or "Referencia API-Football LIVE (casa no especificada)"),
                            "bookmaker_verified": verified_odds.get("bookmaker_verified") is True,
                            "odds_source": str(verified_odds.get("odds_source") or "API-Football LIVE"),
                            "verified_odds_market": str(verified_odds.get("market_label") or ""),
                            "odds_decimal": float(verified_odds["odd"]),
                            "odds_verified": True,
                            "odds_bookmaker": str(verified_odds.get("bookmaker") or "Referencia API-Football LIVE (casa no especificada)"),
                            "odds_market": str(verified_odds.get("market_label") or ""),
                            "implied_probability": round(float(_opportunity["implied_probability"]), 4),
                            "estimated_edge": round(float(_opportunity["edge"]), 4),
                            "expected_value": _opportunity["expected_value"],
                            "opportunity_engine": "v1",
                        })
                        scan_diagnostics["eligible_goal_signals"] += 1
                        if row_key not in existing_keys:
                            signal_rows.append(row)
                            new_signal_rows.append(row)
                    else:
                        scan_diagnostics["goal_candidates_without_exact_quote_or_below_filters"] += 1
                elif odds_rows_for_fixture:
                    scan_diagnostics["goal_candidates_without_exact_quote_or_below_filters"] += 1
                if row_key not in existing_keys:
                    existing_keys.add(row_key)

        # CÓRNERS: usar la proyección en vivo + promedio histórico por localía.
        # Solo entra al evaluador si hay muestra histórica mínima, datos en vivo,
        # puerta experimental de actividad y cuota exacta para el mismo fixture.
        import math
        import re
        for corner_item in corner_results:
            fixture = corner_item.get("fixture") or {}
            fixture_data = fixture.get("fixture") or {}
            fixture_id = fixture_data.get("id")
            if not fixture_id or corner_item.get("error"):
                continue
            minute = (fixture_data.get("status") or {}).get("elapsed")
            home_corners = corner_item.get("home_corners")
            away_corners = corner_item.get("away_corners")
            home_shots = corner_item.get("home_shots")
            away_shots = corner_item.get("away_shots")
            total_now = (
                float(home_corners) + float(away_corners)
                if isinstance(home_corners, (int, float)) and isinstance(away_corners, (int, float))
                else None
            )
            pace = corner_item.get("pace")
            history = corner_item.get("automatic_history") or {}
            home_history = history.get("home_corners_for")
            away_history = history.get("away_corners_for")
            home_sample = int(history.get("home_corner_sample", 0) or 0)
            away_sample = int(history.get("away_corner_sample", 0) or 0)
            history_ready = (
                isinstance(home_history, (int, float))
                and isinstance(away_history, (int, float))
                and home_sample >= 3 and away_sample >= 3
            )
            activity_ready = qualifies_as_corner_candidate(
                minute, total_now, pace, home_shots, away_shots
            )
            if not history_ready or not activity_ready:
                continue

            scan_diagnostics["corner_probability_candidates"] += 1
            historical_total_mean = float(home_history) + float(away_history)
            live_projection = float(total_now) * 90.0 / max(1, int(minute))
            projected_total = 0.55 * historical_total_mean + 0.45 * live_projection
            remaining_expected = max(0.0, projected_total - float(total_now))
            remaining_lambda = max(0.05, remaining_expected * 0.70)
            odds_rows_for_fixture = odds_index_for_scan.get(str(fixture_id), [])
            if not odds_rows_for_fixture:
                scan_diagnostics["corner_candidates_without_quotes"] += 1
                continue

            corner_market_rows = [
                row for row in best_live_odds_by_market(odds_rows_for_fixture)
                if "córners" in str(row.get("market_label") or "").casefold()
                and isinstance(row.get("odd"), (int, float))
            ]
            if not corner_market_rows:
                scan_diagnostics["corner_candidates_without_exact_quote_or_below_filters"] += 1
                continue

            goals_data = fixture.get("goals") or {}
            teams = fixture.get("teams") or {}
            home_name = (teams.get("home") or {}).get("name") or "Local"
            away_name = (teams.get("away") or {}).get("name") or "Visitante"
            for odds_row in corner_market_rows:
                market_label = str(odds_row.get("market_label") or "")
                odd = odds_row.get("odd")
                line_match = re.search(r"(\d+(?:[.,]\d+)?)", market_label)
                if not line_match or not isinstance(odd, (int, float)):
                    scan_diagnostics["corner_candidates_without_exact_quote_or_below_filters"] += 1
                    continue
                market_line = float(line_match.group(1).replace(",", "."))
                # Evitar líneas enteras: su liquidación puede incluir push y requiere
                # probabilidades separadas de ganar/devolver; aquí solo modelamos medio gol.
                if abs((market_line % 1.0) - 0.5) > 1e-8:
                    scan_diagnostics["corner_candidates_without_exact_quote_or_below_filters"] += 1
                    continue
                if market_label.startswith("Más de "):
                    required_remaining = math.floor(market_line - float(total_now)) + 1
                    model_probability = poisson_at_least(remaining_lambda, required_remaining)
                elif market_label.startswith("Menos de "):
                    max_remaining = math.ceil(market_line - float(total_now)) - 1
                    model_probability = sum(
                        poisson_pmf(remaining_lambda, count)
                        for count in range(max_remaining + 1)
                    ) if max_remaining >= 0 else 0.0
                else:
                    continue
                if not isinstance(model_probability, (int, float)) or not 0.0 < model_probability < 1.0:
                    scan_diagnostics["corner_candidates_without_exact_quote_or_below_filters"] += 1
                    continue
                row_key = (str(fixture_id), market_label, str(minute),
                           str(goals_data.get("home")), str(goals_data.get("away")))
                row = {
                    "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                    "fixture_id": fixture_id,
                    "league_id": (fixture.get("league") or {}).get("id"),
                    "league": (fixture.get("league") or {}).get("name"),
                    "home": home_name,
                    "away": away_name,
                    "phase": "live",
                    "minute": minute,
                    "score_home": goals_data.get("home"),
                    "score_away": goals_data.get("away"),
                    "market": market_label,
                    "market_type": "corners",
                    "selection": market_label,
                    "probability": round(float(model_probability), 4),
                    "estimated_probability_exploratory": round(float(model_probability), 4),
                    "model_id": "live_corner_poisson_exploratory",
                    "model_version": "live-corner-poisson-exploratory-v1",
                    "source": "football_lab_live_scanner",
                    "snapshot_id": ":".join(str(value) for value in (
                        fixture_id, minute, goals_data.get("home"), goals_data.get("away"),
                        total_now, market_label,
                    )),
                    "corners_total": total_now,
                    "shots_total": float(home_shots) + float(away_shots),
                    "historical_home_corners_for": float(home_history),
                    "historical_away_corners_for": float(away_history),
                    "historical_home_corner_sample": home_sample,
                    "historical_away_corner_sample": away_sample,
                    "projected_total_corners": round(projected_total, 3),
                    "remaining_expected_corners": round(remaining_expected, 3),
                    "final_score": "",
                    "outcome": "",
                    "outcome_verified": "",
                }
                scan_diagnostics["corner_candidates_evaluated"] += 1
                # Guardar la estimación aunque la cuota/EV no permita publicar señal.
                row.update({
                    "verified_live_odd": float(odd),
                    "verified_bookmaker": str(odds_row.get("bookmaker") or "Referencia API-Football LIVE (casa no especificada)"),
                    "bookmaker_verified": odds_row.get("bookmaker_verified") is True,
                    "odds_source": str(odds_row.get("odds_source") or "API-Football LIVE"),
                    "verified_odds_market": market_label,
                    "odds_decimal": float(odd),
                    "odds_verified": True,
                    "odds_bookmaker": str(odds_row.get("bookmaker") or "Referencia API-Football LIVE (casa no especificada)"),
                    "odds_market": market_label,
                })
                forecast_rows_to_persist.append(dict(row))
                _opportunity = evaluate_opportunity({
                    "market": "corners",
                    "selection": market_label,
                    "probability": float(model_probability),
                    "odds": float(odd),
                    "odds_verified": True,
                    "fixture_id": fixture_id,
                    "fixture": f"{home_name} vs {away_name}",
                    "minute": minute,
                    "score": f"{goals_data.get('home', '?')}-{goals_data.get('away', '?')}",
                    "bookmaker": str(odds_row.get("bookmaker") or "Referencia API-Football LIVE (casa no especificada)"),
                    "source": "api-football-live-odds",
                }, min_ev=0.02, min_odds=1.35, max_odds=10.0)
                if not _opportunity.get("eligible"):
                    scan_diagnostics["corner_candidates_without_exact_quote_or_below_filters"] += 1
                    continue
                row.update({
                    "verified_live_odd": float(odd),
                    "verified_bookmaker": str(odds_row.get("bookmaker") or "Referencia API-Football LIVE (casa no especificada)"),
                    "bookmaker_verified": odds_row.get("bookmaker_verified") is True,
                    "odds_source": str(odds_row.get("odds_source") or "API-Football LIVE"),
                    "verified_odds_market": market_label,
                    "odds_decimal": float(odd),
                    "odds_verified": True,
                    "odds_bookmaker": str(odds_row.get("bookmaker") or "Referencia API-Football LIVE (casa no especificada)"),
                    "odds_market": market_label,
                    "implied_probability": round(float(_opportunity["implied_probability"]), 4),
                    "estimated_edge": round(float(_opportunity["edge"]), 4),
                    "expected_value": _opportunity["expected_value"],
                    "opportunity_engine": "v1",
                })
                scan_diagnostics["eligible_corner_signals"] += 1
                if row_key not in existing_keys:
                    signal_rows.append(row)
                    new_signal_rows.append(row)
                    existing_keys.add(row_key)

        if scan_diagnostics["corner_probability_candidates"]:
            scan_diagnostics["corner_model_status"] = (
                "Modelo exploratorio conectado: candidatos calculados con muestra histórica mínima, "
                "ritmo en vivo y actividad. Solo se aprueban cuotas exactas con EV ≥ 2 %; "
                "las probabilidades aún no están calibradas."
            )
        elif scan_diagnostics["corner_stats_ready"]:
            scan_diagnostics["corner_model_status"] = (
                "Datos de córners disponibles, pero ningún partido superó simultáneamente "
                "la muestra histórica mínima y el filtro experimental de actividad."
            )
        scan_diagnostics["telegram_queue_after_scan"] = len(st.session_state.get("telegram_pending_rows", [])) + len(new_signal_rows)
        scan_diagnostics["scan_finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.session_state["last_scan_diagnostics"] = scan_diagnostics
        st.session_state.signal_rows = signal_rows
        # Telegram recibe solo señales nuevas respaldadas por cuota real, mercado coincidente y ventaja mínima.
        telegram_pending = st.session_state.setdefault("telegram_pending_rows", [])
        telegram_pending.extend(new_signal_rows)
        telegram_pending = [
            row for row in telegram_pending
            if isinstance(row, dict)
            and isinstance(row.get("verified_live_odd"), (int, float))
            and row.get("odds_verified") is True
            and row.get("verified_bookmaker")
            and row.get("verified_odds_market")
            and isinstance(row.get("estimated_edge"), (int, float))
            and float(row["estimated_edge"]) >= 0.02
            and (1.35 <= float(row["verified_live_odd"]) <= 1.60 or float(row["verified_live_odd"]) >= 1.70)
        ]
        st.session_state.telegram_pending_rows = telegram_pending
        try:
            telegram_token = str(st.secrets.get("TELEGRAM_BOT_TOKEN", "") or os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
            telegram_chat_id = str(st.secrets.get("TELEGRAM_CHAT_ID", "") or os.getenv("TELEGRAM_CHAT_ID", "-1004668474905")).strip()
            supabase_url = str(st.secrets.get("SUPABASE_URL", "") or os.getenv("SUPABASE_URL", "")).strip()
            supabase_secret_key = str(st.secrets.get("SUPABASE_SECRET_KEY", "") or os.getenv("SUPABASE_SECRET_KEY", "")).strip()
        except Exception:
            telegram_token = str(os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
            telegram_chat_id = str(os.getenv("TELEGRAM_CHAT_ID", "-1004668474905")).strip()
            supabase_url = str(os.getenv("SUPABASE_URL", "")).strip()
            supabase_secret_key = str(os.getenv("SUPABASE_SECRET_KEY", "")).strip()
        # Publicación automática: solo procesa señales nuevas generadas en este escaneo.
        # Supabase reserva cada fixture/mercado de forma atómica antes de contactar Telegram.
        auto_publish_stats = {"sent": 0, "duplicates": 0, "failed": 0, "waiting": 0}
        auto_publish_candidates = []
        _candidate_keys = set()
        for _candidate in telegram_pending:
            _candidate_key = build_alert_key(_candidate)
            if _candidate_key and _candidate_key not in _candidate_keys:
                auto_publish_candidates.append(_candidate)
                _candidate_keys.add(_candidate_key)
        _telegram_status_warning = False
        if auto_publish_candidates:
            if not all((telegram_token, telegram_chat_id, supabase_url, supabase_secret_key)):
                auto_publish_stats["waiting"] = len(auto_publish_candidates)
                st.session_state.telegram_publish_status = (
                    f"{len(auto_publish_candidates)} señal(es) elegible(s) en espera: faltan credenciales de Telegram o Supabase."
                )
            else:
                processed_alert_keys = set()
                for _signal_row in auto_publish_candidates:
                    # Defensa adicional: nunca publicar filas sin cuota/mercado/edge verificados.
                    _odd = _signal_row.get("verified_live_odd")
                    _edge = _signal_row.get("estimated_edge")
                    if (
                        not isinstance(_odd, (int, float))
                        or _signal_row.get("odds_verified") is not True
                        or not _signal_row.get("verified_bookmaker")
                        or not _signal_row.get("verified_odds_market")
                        or not isinstance(_edge, (int, float))
                        or float(_edge) < 0.02
                        or not (1.35 <= float(_odd) <= 1.60 or float(_odd) >= 1.70)
                    ):
                        auto_publish_stats["waiting"] += 1
                        continue
                    _reserved, _alert_key, _reserve_detail = reserve_telegram_alert(
                        _signal_row, supabase_url, supabase_secret_key
                    )
                    if not _reserved:
                        if _alert_key:
                            # Ya enviada o reservada: se retira de la cola para no insistir.
                            auto_publish_stats["duplicates"] += 1
                            processed_alert_keys.add(_alert_key)
                        else:
                            auto_publish_stats["failed"] += 1
                        continue
                    _sent, _send_detail = send_telegram_signal(
                        _signal_row, telegram_token, telegram_chat_id
                    )
                    _updated = update_telegram_alert(
                        _alert_key, "sent" if _sent else "failed",
                        supabase_url, supabase_secret_key,
                        error="" if _sent else _send_detail,
                    )
                    if _sent:
                        processed_alert_keys.add(_alert_key)
                        auto_publish_stats["sent"] += 1
                        if not _updated:
                            # Telegram ya recibió el mensaje; advertir que faltó cerrar el registro.
                            st.session_state.telegram_publish_status = (
                                "Telegram recibió una señal, pero Supabase no confirmó el estado final. "
                                "La reserva evita que se duplique automáticamente."
                            )
                            _telegram_status_warning = True
                    else:
                        auto_publish_stats["failed"] += 1
                if processed_alert_keys:
                    telegram_pending = [
                        _row for _row in telegram_pending
                        if build_alert_key(_row) not in processed_alert_keys
                    ]
                    st.session_state.telegram_pending_rows = telegram_pending
                st.session_state.telegram_auto_publish_last = auto_publish_stats
                if not _telegram_status_warning:
                    st.session_state.telegram_publish_status = (
                        f"Envío automático del escaneo: {auto_publish_stats['sent']} enviada(s), "
                        f"{auto_publish_stats['duplicates']} duplicada(s) bloqueada(s), "
                        f"{auto_publish_stats['failed']} fallida(s), "
                        f"{auto_publish_stats['waiting']} en espera."
                    )
        elif telegram_pending:
            st.session_state.telegram_publish_status = (
                f"{len(telegram_pending)} señal(es) elegible(s) conservada(s) en cola; "
                "se procesarán al generarse una nueva señal verificada."
            )
        try:
            if signal_rows:
                SIGNAL_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
                with SIGNAL_HISTORY_PATH.open("w", encoding="utf-8-sig", newline="") as history_file:
                    # Registros antiguos y nuevos pueden tener columnas distintas.
                    # Unimos las claves para conservar las filas legacy sin perder metadatos nuevos.
                    fieldnames = list(dict.fromkeys(
                        key for saved_row in signal_rows for key in saved_row.keys()
                    ))
                    writer = csv.DictWriter(history_file, fieldnames=fieldnames, extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(signal_rows)
        except OSError as history_exc:
            st.session_state.signal_history_write_error = str(history_exc)
        # Keep a canonical, append-only forecast ledger separate from the legacy CSV.
        # SQLite uniqueness on prediction_id makes repeated Streamlit reruns idempotent.
        # Migra también filas legacy del CSV si contienen los campos mínimos reales.
        # La normalización valida cada fila y nunca inventa mercado, fixture, fecha ni probabilidad.
        _ledger_source_rows = list(signal_rows) + list(forecast_rows_to_persist)
        normalized_ledger_rows = [
            normalize_prediction_record(saved_row)
            for saved_row in _ledger_source_rows
            if isinstance(saved_row, dict)
        ]
        ledger_records_to_sync = [record for record in normalized_ledger_rows if record["valid"]]
        st.session_state.prediction_ledger_sync_diagnostics = {
            "csv_rows": len(signal_rows),
            "forecast_candidates_this_scan": len(forecast_rows_to_persist),
            "ledger_source_rows": len(_ledger_source_rows),
            "valid_rows": len(ledger_records_to_sync),
            "invalid_rows": len(normalized_ledger_rows) - len(ledger_records_to_sync),
        }
        if ledger_records_to_sync:
            try:
                st.session_state.prediction_ledger_last_write = append_prediction_records(
                    PREDICTION_LEDGER_PATH, ledger_records_to_sync
                )
                st.session_state.prediction_ledger_write_error = ""
            except Exception as ledger_exc:
                st.session_state.prediction_ledger_write_error = str(ledger_exc)
            try:
                _sb_url = str(st.secrets.get("SUPABASE_URL", "") or os.getenv("SUPABASE_URL", "")).strip()
                _sb_key = str(st.secrets.get("SUPABASE_SECRET_KEY", "") or os.getenv("SUPABASE_SECRET_KEY", "")).strip()
                if _sb_url and _sb_key:
                    st.session_state.prediction_supabase_last_write = append_supabase_prediction_records(
                        ledger_records_to_sync, _sb_url, _sb_key
                    )
                    st.session_state.prediction_supabase_write_error = ""
            except Exception as supabase_ledger_exc:
                st.session_state.prediction_supabase_write_error = (
                    f"{type(supabase_ledger_exc).__name__}: {supabase_ledger_exc}"
                )

        # Reconcile final results periodically during normal scanning. A strict
        # 30-minute cooldown and 25-fixture cap protect the daily API request budget.
        _outcome_now = datetime.now(timezone.utc).timestamp()
        _last_outcome_sync = float(st.session_state.get("automatic_outcome_sync_at", 0) or 0)
        if _outcome_now - _last_outcome_sync >= 1800:
            try:
                _outcome_url = str(st.secrets.get("SUPABASE_URL", "") or os.getenv("SUPABASE_URL", "")).strip()
                _outcome_key = str(st.secrets.get("SUPABASE_SECRET_KEY", "") or os.getenv("SUPABASE_SECRET_KEY", "")).strip()
                if _outcome_url and _outcome_key:
                    _auto_outcome_result = sync_finished_fixture_outcomes(
                        _outcome_url, _outcome_key, api_get, max_fixtures=25
                    )
                    st.session_state["automatic_outcome_sync_result"] = _auto_outcome_result
                    st.session_state["automatic_outcome_sync_error"] = ""
                    st.session_state["automatic_outcome_sync_at"] = _outcome_now
                else:
                    st.session_state["automatic_outcome_sync_error"] = "Faltan credenciales de Supabase."
            except Exception as _auto_outcome_exc:
                st.session_state["automatic_outcome_sync_error"] = (
                    f"{type(_auto_outcome_exc).__name__}: {_auto_outcome_exc}"
                )
        st.session_state.last_scan_api_calls = st.session_state.api_request_count - scan_api_calls_start

    # Mostrar el diagnóstico del último escaneo también cuando hay un partido seleccionado,
    # para que siempre quede accesible encima de las pestañas principales.
    if not _analysis_page_active or st.session_state.get("last_scan_diagnostics"):
        _scan_diag = st.session_state.get("last_scan_diagnostics") or {}
        if _scan_diag:
            st.markdown("### 🔎 Diagnóstico del último escaneo")
            st.caption(f"Actualizado: {_scan_diag.get('scan_finished_at', '—')} · Los filtros de elegibilidad se mantienen intactos.")
            _ledger_sync = st.session_state.get("prediction_ledger_sync_diagnostics") or {}
            _ledger_write = st.session_state.get("prediction_ledger_last_write") or {}
            if _ledger_sync:
                st.caption(
                    f"Registro independiente: {_ledger_sync.get('forecast_candidates_this_scan', 0)} "
                    f"pronóstico(s) exploratorio(s) detectado(s) en este escaneo · "
                    f"{_ledger_write.get('inserted', 0)} nuevo(s) guardado(s) · "
                    f"{_ledger_write.get('duplicates', 0)} duplicado(s) controlado(s). "
                    "Se guardan aunque no generen señal."
                )
            if st.session_state.get("prediction_ledger_write_error"):
                st.warning(f"No se pudo guardar el registro local de pronósticos: {st.session_state['prediction_ledger_write_error']}")
            if st.session_state.get("prediction_supabase_write_error"):
                st.warning(f"No se pudo sincronizar el registro remoto de pronósticos: {st.session_state['prediction_supabase_write_error']}")
            _auto_outcomes = st.session_state.get("automatic_outcome_sync_result") or {}
            if _auto_outcomes:
                st.caption(
                    f"Verificación automática de resultados (cada 30 min, máximo 25 partidos): "
                    f"{_auto_outcomes.get('checked', 0)} revisados · "
                    f"{_auto_outcomes.get('finished', 0)} finalizados · "
                    f"{_auto_outcomes.get('inserted', 0)} resultados nuevos · "
                    f"{_auto_outcomes.get('unchanged', 0)} sin cambios."
                )
            if st.session_state.get("automatic_outcome_sync_error"):
                st.warning(f"Verificación automática de resultados: {st.session_state['automatic_outcome_sync_error']}")
            _diag_cols = st.columns(4)
            _diag_cols[0].metric("Partidos analizados", int(_scan_diag.get("fixtures_scanned", 0)))
            _diag_cols[1].metric("Modelos de goles disponibles", int(_scan_diag.get("goal_estimates_available", 0)))
            _diag_cols[2].metric("Candidatos de goles", int(_scan_diag.get("goal_model_candidates", 0)))
            _diag_cols[3].metric("Señales elegibles", int(_scan_diag.get("eligible_goal_signals", 0)))
            with st.expander("Ver por qué no se generaron señales", expanded=int(_scan_diag.get("eligible_goal_signals", 0)) == 0):
                _reason_cols = st.columns(4)
                _reason_cols[0].metric("Candidatos sin cuotas", int(_scan_diag.get("goal_candidates_without_quotes", 0)))
                _reason_cols[1].metric("Sin mercado exacto / filtro", int(_scan_diag.get("goal_candidates_without_exact_quote_or_below_filters", 0)))
                _reason_cols[2].metric("Modelo no calibrado", int(_scan_diag.get("goal_candidates_model_not_validated", 0)))
                _reason_cols[3].metric("Candidatos evaluados", int(_scan_diag.get("goal_candidates_evaluated", 0)))
                if int(_scan_diag.get("goal_candidates_model_not_validated", 0)):
                    st.warning("Las estimaciones actuales de goles son exploratorias y aún no están calibradas. Se muestran para análisis, pero no se publican como señales automáticas.")
                st.markdown("**Córners**")
                _corner_cols = st.columns(3)
                _corner_cols[0].metric("Partidos con córners en vivo", int(_scan_diag.get("corner_stats_ready", 0)))
                _corner_cols[1].metric("Candidatos probabilísticos", int(_scan_diag.get("corner_probability_candidates", 0)))
                _corner_cols[2].metric("Señales elegibles", int(_scan_diag.get("eligible_corner_signals", 0)))
                _corner_detail_cols = st.columns(3)
                _corner_detail_cols[0].metric("Candidatos sin cuotas", int(_scan_diag.get("corner_candidates_without_quotes", 0)))
                _corner_detail_cols[1].metric("Sin cuota exacta / EV", int(_scan_diag.get("corner_candidates_without_exact_quote_or_below_filters", 0)))
                _corner_detail_cols[2].metric("Mercados evaluados", int(_scan_diag.get("corner_candidates_evaluated", 0)))
                st.info(str(_scan_diag.get("corner_model_status", "Estado del modelo de córners no disponible.")))
                st.markdown("**Cobertura de cuotas en vivo**")
                # Prueba aislada del fixture de referencia: no genera ni publica señales.
                _probe_selected_fixture_id = str(st.session_state.get("selected_live_fixture_id") or "").strip()
                _probe_selected_fixture = st.session_state.get("selected_live_fixture") or {}
                _probe_selected_teams = _probe_selected_fixture.get("teams") or {}
                _probe_selected_home = str((_probe_selected_teams.get("home") or {}).get("name") or "Local")
                _probe_selected_away = str((_probe_selected_teams.get("away") or {}).get("name") or "Visitante")
                with st.expander("Prueba directa de cuotas del partido seleccionado", expanded=False):
                    if _probe_selected_fixture_id:
                        st.caption(
                            f"Partido seleccionado: {_probe_selected_home} vs {_probe_selected_away} · "
                            f"fixture={_probe_selected_fixture_id}. Consulta individual a API-Football "
                            "/odds/live; diagnóstico solamente, no atribuye cuotas a RushBet."
                        )
                    else:
                        st.info("Primero selecciona un partido en la lista «En vivo ahora» para obtener su fixture ID.")
                    if st.button(
                        f"Consultar cuotas del fixture {_probe_selected_fixture_id or 'seleccionado'}",
                        key="test_live_odds_selected_fixture",
                        disabled=not bool(_probe_selected_fixture_id),
                    ):
                        try:
                            _probe_payload = api_get("odds/live", {"fixture": int(_probe_selected_fixture_id)})
                            _probe_items = _probe_payload.get("response") or []
                            _probe_markets = []
                            for _probe_item in _probe_items:
                                if not isinstance(_probe_item, dict):
                                    continue
                                for _probe_market in (_probe_item.get("odds") or []):
                                    if not isinstance(_probe_market, dict):
                                        continue
                                    _probe_values = []
                                    for _probe_value in (_probe_market.get("values") or []):
                                        if not isinstance(_probe_value, dict):
                                            continue
                                        _probe_values.append({
                                            "selection": str(_probe_value.get("value") or ""),
                                            "odd": str(_probe_value.get("odd") or ""),
                                            "handicap": str(_probe_value.get("handicap") or ""),
                                            "suspended": bool(_probe_value.get("suspended")),
                                            "main": _probe_value.get("main"),
                                        })
                                    _probe_markets.append({
                                        "market_id": _probe_market.get("id"),
                                        "market": str(_probe_market.get("name") or "Mercado sin nombre"),
                                        "values": _probe_values,
                                    })
                            st.session_state["live_odds_selected_fixture_probe"] = {
                                "fixture_id": _probe_selected_fixture_id,
                                "response_count": len(_probe_items),
                                "markets": _probe_markets,
                                "errors": _probe_payload.get("errors") or {},
                                "response_fixtures": [
                                    str((((_x.get("fixture") or {}).get("id")) or ""))
                                    for _x in _probe_items if isinstance(_x, dict)
                                ],
                                "statuses": [
                                    _x.get("status") or {}
                                    for _x in _probe_items if isinstance(_x, dict)
                                ],
                            }
                        except Exception as _probe_exc:
                            st.session_state["live_odds_selected_fixture_probe"] = {
                                "fixture_id": _probe_selected_fixture_id,
                                "error": f"{type(_probe_exc).__name__}: {_probe_exc}"
                            }
                    _probe_result = st.session_state.get("live_odds_selected_fixture_probe")
                    if _probe_result and str(_probe_result.get("fixture_id")) == _probe_selected_fixture_id:
                        if _probe_result.get("error"):
                            st.error(_probe_result["error"])
                        else:
                            st.write(f"Registros devueltos: {_probe_result.get('response_count', 0)}")
                            st.write(f"IDs devueltos: {', '.join(_probe_result.get('response_fixtures', [])) or 'ninguno'}")
                            st.write(f"Mercados recibidos: {len(_probe_result.get('markets', []))}")
                            st.write(f"Estados: {_probe_result.get('statuses', [])}")
                            if _probe_result.get("errors"):
                                st.warning(f"Errores del proveedor: {_probe_result['errors']}")
                            for _probe_market in _probe_result.get("markets", []):
                                st.write(f"{_probe_market.get('market')} (ID {_probe_market.get('market_id')})")
                                if _probe_market.get("values"):
                                    st.dataframe(_probe_market["values"], use_container_width=True, hide_index=True)
                                else:
                                    st.caption("El mercado llegó sin valores.")
                            if not _probe_result.get("markets"):
                                st.info("La API no devolvió mercados para este fixture en esta consulta.")
                _odds_cols = st.columns(3)
                _odds_cols[0].metric("Partidos con cuotas", int(_scan_diag.get("fixtures_with_odds", 0)))
                _odds_cols[1].metric("Partidos sin cuotas", int(_scan_diag.get("fixtures_without_odds", 0)))
                _odds_cols[2].metric("Mercados recibidos", int(_scan_diag.get("odds_rows_returned", 0)))
                st.caption(
                    f"Respuesta de API-Football: {_scan_diag.get('odds_api_response_count', 0)} partidos · "
                    f"IDs recibidos: {', '.join(_scan_diag.get('odds_api_fixture_ids', [])[:12]) or 'ninguno'}"
                )
                st.caption(f"Consultas individuales de respaldo: {_scan_diag.get('odds_targeted_calls', 0)}")
                if _scan_diag.get("odds_error"):
                    st.warning(f"Error de consulta de cuotas: {_scan_diag.get('odds_error')}")
                elif _scan_diag.get("odds_api_errors"):
                    st.warning(f"API-Football reportó: {_scan_diag.get('odds_api_errors')}")
                if _scan_diag.get("odds_targeted_errors"):
                    st.warning("Errores en consultas por partido: " + " | ".join(_scan_diag.get("odds_targeted_errors", [])[:5]))
                st.markdown("### Prueba de cuotas LIVE por competición")
                st.caption(
                    f"Consultas nuevas por liga en este escaneo: {_scan_diag.get('odds_league_calls', 0)} "
                    "· Se reutilizan respuestas durante 60 segundos."
                )
                _league_live_rows = _scan_diag.get("odds_league_details", [])
                if _league_live_rows:
                    for _live_league in _league_live_rows:
                        st.write(
                            f"{_live_league.get('league_name')} (ID {_live_league.get('league_id')}): "
                            f"{_live_league.get('response_items', 0)} respuestas · "
                            f"{_live_league.get('fixtures_scanned', 0)} partidos escaneados · "
                            f"{_live_league.get('matched_fixtures', 0)} coincidencias · "
                            f"{_live_league.get('bookmakers', 0)} casas · "
                            f"{_live_league.get('bet_values', 0)} valores · "
                            f"{_live_league.get('parsed_rows', 0)} cuotas interpretadas"
                        )
                        if _live_league.get("api_errors"):
                            st.caption(f"Respuesta/errores API para liga {_live_league.get('league_id')}: {_live_league.get('api_errors')}")
                else:
                    st.info("La prueba por competición todavía no tiene resultados.")
                if _scan_diag.get("odds_league_errors"):
                    st.warning("Errores en consultas LIVE por competición: " + " | ".join(_scan_diag.get("odds_league_errors", [])[:5]))
                st.markdown("### Cobertura de cuotas por competición")
                _coverage_rows = _scan_diag.get("odds_league_coverage_details", [])
                if _coverage_rows:
                    for _coverage in _coverage_rows:
                        st.write(
                            f"{_coverage.get('country') or ''} · {_coverage.get('league_name') or _coverage.get('league_id')} "
                            f"({_coverage.get('season')}): odds = {_coverage.get('odds_coverage')}"
                        )
                        if _coverage.get("api_errors"):
                            st.caption(f"Respuesta de cobertura: {_coverage.get('api_errors')}")
                else:
                    st.info("Todavía no hay datos de cobertura para las ligas de este escaneo. Ejecuta «Escanear en vivo» para consultarlas.")
                with st.expander("Catálogos de cuotas disponibles"):
                    st.write(f"Tipos de mercado LIVE: {_scan_diag.get('odds_live_bets_catalog_count', 0)}")
                    st.caption(", ".join(_scan_diag.get("odds_live_bets_catalog_sample", [])) or "Sin nombres de mercados recibidos")
                    st.write(f"Casas de apuestas en catálogo: {_scan_diag.get('odds_bookmakers_catalog_count', 0)}")
                    st.caption(", ".join(_scan_diag.get("odds_bookmakers_catalog_sample", [])) or "Sin casas recibidas")
                    if _scan_diag.get("odds_live_bets_catalog_errors"):
                        st.warning(f"Error catálogo LIVE: {_scan_diag.get('odds_live_bets_catalog_errors')}")
                    if _scan_diag.get("odds_bookmakers_catalog_errors"):
                        st.warning(f"Error catálogo casas: {_scan_diag.get('odds_bookmakers_catalog_errors')}")
                with st.expander("Detalle de respuesta por partido"):
                    _party_details = _scan_diag.get("odds_targeted_details", []) or []
                    if not _party_details:
                        st.info(
                            "No hay respuestas individuales registradas para este escaneo. "
                            "Revisa si el proveedor devolvió cuotas globales, si la consulta individual se ejecutó "
                            "o si el escáner no llegó a recorrer los partidos. Vuelve a pulsar «Escanear en vivo»."
                        )
                    for _detail in _party_details:
                        st.write(
                            f"Fixture {_detail.get('fixture_id')}: "
                            f"{_detail.get('response_items', 0)} registros, "
                            f"{_detail.get('bookmakers', 0)} casas, "
                            f"{_detail.get('bet_values', 0)} valores de mercado, "
                            f"{_detail.get('parsed_rows', 0)} cuotas interpretadas"
                        )
                        if _detail.get("home") or _detail.get("away"):
                            st.caption(
                                f"{_detail.get('home') or 'Local N/D'} vs {_detail.get('away') or 'Visitante N/D'}"
                                f" · origen: {_detail.get('source') or 'no informado'}"
                            )
                        if _detail.get("note"):
                            st.caption(_detail.get("note"))
                        for _item_summary in _detail.get("response_item_summaries", []):
                            st.caption(
                                "Respuesta recibida · "
                                f"fixture={_item_summary.get('returned_fixture_id') or 'sin ID'} · "
                                f"claves={', '.join(_item_summary.get('response_keys', [])) or 'ninguna'} · "
                                f"casas={', '.join(_item_summary.get('bookmaker_names', [])) or 'no desglosadas'} · "
                                f"mercados LIVE={_item_summary.get('live_market_count', 0)} · "
                                f"valores LIVE={_item_summary.get('live_value_count', 0)} · "
                                f"nombres={', '.join(_item_summary.get('live_market_names', [])) or 'ninguno'} · "
                                f"estado={_item_summary.get('status', {})}"
                            )
                            if _item_summary.get("league") or _item_summary.get("home") or _item_summary.get("away"):
                                st.caption(
                                    f"Partido devuelto: {_item_summary.get('league') or 'liga N/D'} · "
                                    f"{_item_summary.get('home') or 'local N/D'} vs "
                                    f"{_item_summary.get('away') or 'visitante N/D'}"
                                )
                        if _detail.get("api_errors"):
                            st.caption(f"Errores API: {_detail.get('api_errors')}")
                        if _detail.get("exception"):
                            st.caption(f"Error local: {_detail.get('exception')}")
                if _scan_diag.get("odds_last_fetch"):
                    st.caption(f"Última consulta de cuotas: {_scan_diag.get('odds_last_fetch')}")
                if int(_scan_diag.get("odds_api_response_count", 0) or 0) == 0 and not _scan_diag.get("odds_error"):
                    st.info("La consulta global /odds/live respondió sin partidos. Esto apunta a cobertura/respuesta del proveedor; todavía no significa que los 5 partidos no tengan cuotas en todas las casas.")
                st.caption("Una cuota solo cuenta como válida cuando coincide con el fixture y el mercado exacto. No se generan señales a partir de promedios descriptivos.")
        tab_goals, tab_corners, tab_overview = st.tabs(["⚽ Goles y señales", "🚩 Córners", "📈 Rendimiento del modelo"])

        with tab_goals:
            st.markdown("### ⚽ Goles · lectura del partido en vivo")
            st.caption("El bot combina promedios de localía, marcador, minuto y estadísticas disponibles en vivo. Presenta una sola recomendación principal por partido, no una lista de mercados.")
            goal_results = st.session_state.get("goal_scan_results", [])
            if goal_results:
                corner_history_by_id = {
                    (item.get("fixture", {}).get("fixture") or {}).get("id"): item.get("automatic_history") or {}
                    for item in st.session_state.get("corner_scan_results", [])
                }
                search_matches = str(st.session_state.get("search_goal_matches", "")).strip().casefold()
                cards_shown = 0
                for goal_row in goal_results:
                    # Compatibilidad con resultados guardados en session_state por versiones anteriores:
                    # el formato antiguo tenía 3 elementos y el actual incluye también el contexto.
                    if not isinstance(goal_row, (tuple, list)) or len(goal_row) < 3:
                        continue
                    fixture, estimate, tips = goal_row[:3]
                    context = goal_row[3] if len(goal_row) >= 4 and isinstance(goal_row[3], dict) else {}
                    fixture_id = (fixture.get("fixture") or {}).get("id")
                    if search_matches and search_matches not in fixture_label(fixture).casefold():
                        continue
                    history = corner_history_by_id.get(fixture_id, {})
                    if not estimate.get("available"):
                        continue
                    home = (fixture.get("teams") or {}).get("home") or {}
                    away = (fixture.get("teams") or {}).get("away") or {}
                    home_name = home.get("name", "Local")
                    away_name = away.get("name", "Visitante")
                    goals = fixture.get("goals") or {}
                    home_score = goals.get("home")
                    away_score = goals.get("away")
                    minute = ((fixture.get("fixture") or {}).get("status") or {}).get("elapsed")
                    st.markdown(fixture_hero_html(fixture), unsafe_allow_html=True)
                    st.markdown("**📊 Promedios de goles por localía**")
                    goal_history_rows = [
                        {"Indicador": f"{home_name} · goles a favor en casa", "Promedio": history.get("home_goals_for"), "Muestra": history.get("home_goal_sample", 0)},
                        {"Indicador": f"{home_name} · goles recibidos en casa", "Promedio": history.get("home_goals_against"), "Muestra": history.get("home_goal_sample", 0)},
                        {"Indicador": f"{away_name} · goles a favor fuera", "Promedio": history.get("away_goals_for"), "Muestra": history.get("away_goal_sample", 0)},
                        {"Indicador": f"{away_name} · goles recibidos fuera", "Promedio": history.get("away_goals_against"), "Muestra": history.get("away_goal_sample", 0)},
                    ]
                    goal_table_html = '<table class="history-table"><thead><tr><th>Equipo / indicador</th><th>Promedio</th><th>Muestra</th></tr></thead><tbody>'
                    for row in goal_history_rows:
                        avg = row["Promedio"]
                        avg_text = f"{avg:.2f}".rstrip("0").rstrip(".") if isinstance(avg, (int, float)) else "N/D"
                        goal_table_html += f"<tr><td>{html.escape(str(row['Indicador']))}</td><td>{avg_text}</td><td>{row['Muestra']}</td></tr>"
                    goal_table_html += "</tbody></table>"
                    st.markdown(goal_table_html, unsafe_allow_html=True)

                    # Choose one main tip: favor a team-goal signal when live pressure supports it.
                    candidates = list(tips or [])
                    live_stats = st.session_state.stats_cache.get(str(fixture_id), [])
                    fixture_teams = fixture.get("teams") or {}
                    live_home_id = (fixture_teams.get("home") or {}).get("id")
                    live_away_id = (fixture_teams.get("away") or {}).get("id")
                    home_shots = safe_stat_for_team(live_stats, "Total Shots", live_home_id)
                    away_shots = safe_stat_for_team(live_stats, "Total Shots", live_away_id)
                    home_on = safe_stat_for_team(live_stats, "Shots on Goal", live_home_id)
                    away_on = safe_stat_for_team(live_stats, "Shots on Goal", live_away_id)
                    home_poss = safe_stat_for_team(live_stats, "Ball Possession", live_home_id)
                    away_poss = safe_stat_for_team(live_stats, "Ball Possession", live_away_id)
                    home_corners = safe_stat_for_team(live_stats, "Corner Kicks", live_home_id)
                    away_corners = safe_stat_for_team(live_stats, "Corner Kicks", live_away_id)
                    if isinstance(home_poss, str):
                        try: home_poss = float(home_poss.replace("%", "").strip())
                        except ValueError: home_poss = None
                    if isinstance(away_poss, str):
                        try: away_poss = float(away_poss.replace("%", "").strip())
                        except ValueError: away_poss = None
                    live_values = [v for v in (home_shots, away_shots, home_on, away_on, home_poss, away_poss, home_corners, away_corners) if isinstance(v, (int, float))]
                    pressure_home = (float(home_on or 0) * 2.0 + float(home_shots or 0) * 0.35 + float(home_corners or 0) * 0.7 + (max(0, float(home_poss) - 50) * 0.06 if isinstance(home_poss, (int, float)) else 0))
                    pressure_away = (float(away_on or 0) * 2.0 + float(away_shots or 0) * 0.35 + float(away_corners or 0) * 0.7 + (max(0, float(away_poss) - 50) * 0.06 if isinstance(away_poss, (int, float)) else 0))
                    pressure_gap = pressure_home - pressure_away
                    scored_home = isinstance(home_score, int) and home_score > 0
                    scored_away = isinstance(away_score, int) and away_score > 0
                    # Live probability refresh: show chance of at least one additional goal
                    # alongside the corner split and the pressure reading used by the model.
                    prob_next_goal = estimate.get("probability_next_goal")
                    metric_cols = st.columns(3)
                    metric_cols[0].metric(
                        "Prob. de otro gol",
                        f"{prob_next_goal * 100:.1f}%" if isinstance(prob_next_goal, (int, float)) else "N/D",
                    )
                    metric_cols[1].metric(
                        f"Córners · {home_name}",
                        str(home_corners) if home_corners is not None else "N/D",
                    )
                    metric_cols[2].metric(
                        f"Córners · {away_name}",
                        str(away_corners) if away_corners is not None else "N/D",
                    )
                    pressure_note = (
                        f"Presión estadística: {home_name} {pressure_home:.1f} · "
                        f"{away_name} {pressure_away:.1f}. "
                        "Los córners pesan como una señal más; tiros a puerta y posesión ayudan a distinguir "
                        "presión real de córners sin peligro."
                        if live_values else
                        "No hay estadísticas en vivo suficientes para ajustar la probabilidad por presión."
                    )
                    st.caption(pressure_note)
                    st.caption(
                        "Estimación exploratoria, no probabilidad calibrada. Se actualiza al refrescar el escáner; "
                        "un 8–2 en córners no significa por sí solo que vaya a llegar un gol."
                    )
                    tip_label = None
                    tip_probability = None
                    rationale = []
                    if isinstance(home_score, int) and isinstance(away_score, int):
                        total_goals = home_score + away_score
                        if total_goals == 0 and isinstance(minute, int) and minute < 88:
                            if pressure_gap >= 1.5 and any(isinstance(v, (int, float)) and v > 0 for v in (home_on, home_shots, home_corners)):
                                tip_label = f"{home_name} marcará al menos 1 gol (más de 0.5 goles del local)"
                                tip_probability = estimate.get("home_final_goals_at_least", {}).get("1", {}).get("probability")
                                rationale.append(f"presión ofensiva favorece a {home_name}")
                            elif pressure_gap <= -1.5 and any(isinstance(v, (int, float)) and v > 0 for v in (away_on, away_shots, away_corners)):
                                tip_label = f"{away_name} marcará al menos 1 gol (más de 0.5 goles del visitante)"
                                tip_probability = estimate.get("away_final_goals_at_least", {}).get("1", {}).get("probability")
                                rationale.append(f"presión ofensiva favorece a {away_name}")
                            elif candidates:
                                tip_label, tip_probability = max(candidates, key=lambda x: x[1])
                        elif total_goals == 0 and isinstance(minute, int) and minute < 88 and candidates:
                            tip_label, tip_probability = max(candidates, key=lambda x: x[1])
                        elif total_goals > 0 and isinstance(minute, int) and minute < 88:
                            # With a goal already scored, prefer another-goal or a team-to-score market over full-time unders.
                            future_candidates = [x for x in candidates if ("goles o más" in x[0] or "terminará con" in x[0] or "No habrá más goles" in x[0])]
                            if future_candidates:
                                tip_label, tip_probability = max(future_candidates, key=lambda x: x[1])
                    if tip_label is None and candidates:
                        tip_label, tip_probability = max(candidates, key=lambda x: x[1])

                    st.markdown("**📡 Lectura en vivo**")
                    live_bits = []
                    if isinstance(home_poss, (int, float)) and isinstance(away_poss, (int, float)):
                        live_bits.append(f"Posesión: {home_name} {home_poss:g}% · {away_name} {away_poss:g}%")
                    if isinstance(home_shots, (int, float)) and isinstance(away_shots, (int, float)):
                        live_bits.append(f"Tiros: {home_name} {home_shots:g} · {away_name} {away_shots:g}")
                    if isinstance(home_on, (int, float)) and isinstance(away_on, (int, float)):
                        live_bits.append(f"Tiros a puerta: {home_name} {home_on:g} · {away_name} {away_on:g}")
                    if isinstance(home_corners, (int, float)) and isinstance(away_corners, (int, float)):
                        live_bits.append(f"Córners: {home_name} {home_corners:g} · {away_name} {away_corners:g}")
                    st.write(" · ".join(live_bits) if live_bits else "La API no entregó estadísticas detalladas suficientes para comparar la presión ofensiva.")
                    if tip_label:
                        # This is model context only, not a betting recommendation.
                        # The actual main/risk tips are selected below from verified live bookmaker odds.
                        probability_text = f" · probabilidad exploratoria {float(tip_probability)*100:.1f}%" if isinstance(tip_probability, (int, float)) else ""
                        st.caption(
                            f"Lectura interna del modelo (no es un tip): {tip_label} · "
                            f"marcador {home_score}–{away_score} · minuto {minute if minute is not None else 'N/D'}"
                            f"{probability_text}"
                        )
                        if rationale:
                            st.caption("Contexto observado: " + "; ".join(rationale) + ".")
                    st.caption(f"Referencia usada por el modelo: {estimate.get('baseline_league', 'genérica')} · muestra de liga: {estimate.get('baseline_matches', 0)} partidos · contexto: {context.get('context_status', 'no disponible')}.")

                    # Guardar la captura estadística del análisis de goles.
                    persist_analysis_snapshot(
                        fixture_id, "goals",
                        {"league": (fixture.get("league") or {}).get("name"), "home": home_name, "away": away_name,
                         "minute": minute, "home_score": home_score, "away_score": away_score,
                         "status": (match_fixture.get("status") or {}).get("short")},
                        {"home_shots": home_shots, "away_shots": away_shots,
                         "home_shots_on_target": home_on, "away_shots_on_target": away_on,
                         "home_possession": home_poss, "away_possession": away_poss,
                         "home_corners": home_corners, "away_corners": away_corners,
                         "baseline_league": estimate.get("baseline_league"),
                         "baseline_matches": estimate.get("baseline_matches"),
                         "context_status": context.get("context_status")},
                        {"available": estimate.get("available"),
                         "expected_total_goals_remaining": estimate.get("expected_total_goals_remaining"),
                         "draw_final": estimate.get("draw_final"), "btts_final": estimate.get("btts_final"),
                         "probability_next_goal": estimate.get("probability_next_goal"),
                         "over_total_goals": estimate.get("over_total_goals"),
                         "under_total_goals": estimate.get("under_total_goals"),
                         "internal_reading": tip_label, "internal_reading_probability": tip_probability},
                    )
                    odds_by_fixture = st.session_state.get("live_odds_by_fixture", {})
                    match_odds = best_live_odds_by_market(odds_by_fixture.get(str(fixture_id), []))
                    main_options = []
                    risk_options = []
                    draw_prob = estimate.get("draw_final") if isinstance(estimate, dict) else None
                    btts_prob = estimate.get("btts_final") if isinstance(estimate, dict) else None

                    for odds_row in match_odds:
                        market_label = classify_market(odds_row)
                        if not market_label:
                            continue
                        odd = odds_row.get("odd")
                        if not isinstance(odd, (int, float)) or odd <= 1:
                            continue

                        model_prob = None
                        if market_label == "Empate final":
                            model_prob = draw_prob
                        elif market_label == "Ambos equipos marcan: Sí":
                            model_prob = btts_prob
                        elif market_label == "Ambos equipos marcan: No" and isinstance(btts_prob, (int, float)):
                            model_prob = 1.0 - btts_prob
                        elif market_label.startswith(("Más de ", "Menos de ")):
                            # Match real odds to a modelled goal or corner line. Corner
                            # probability is a rough Poisson projection from the observed
                            # live pace, so it remains exploratory and requires live stats.
                            import re
                            line_match = re.search(r"(\d+(?:[.,]\d+)?)", market_label)
                            if line_match:
                                line = float(line_match.group(1).replace(",", "."))
                                is_corner_market = "córner" in market_label.casefold()
                                if is_corner_market:
                                    corner_stats = st.session_state.stats_cache.get(str(fixture_id), [])
                                    fixture_teams = fixture.get("teams") or {}
                                    current_home_corners = safe_stat_for_team(corner_stats, "Corner Kicks", (fixture_teams.get("home") or {}).get("id"))
                                    current_away_corners = safe_stat_for_team(corner_stats, "Corner Kicks", (fixture_teams.get("away") or {}).get("id"))
                                    corner_minute = (match_fixture.get("status") or {}).get("elapsed")
                                    if (isinstance(current_home_corners, (int, float))
                                        and isinstance(current_away_corners, (int, float))
                                        and isinstance(corner_minute, int) and 1 <= corner_minute < 90):
                                        current_corners = float(current_home_corners) + float(current_away_corners)
                                        remaining_mean = max(0.05, current_corners / corner_minute * (90 - corner_minute) * 0.70)
                                        if market_label.startswith("Más de "):
                                            needed = max(0, int(line - current_corners + 0.5))
                                            model_prob = poisson_at_least(remaining_mean, needed)
                                        else:
                                            max_remaining = int(line - current_corners)
                                            model_prob = (
                                                sum(poisson_pmf(remaining_mean, n) for n in range(max_remaining + 1))
                                                if max_remaining >= 0 else 0.0
                                            )
                                elif market_label.startswith("Más de "):
                                    target = str(int(line + 0.5))
                                    model_prob = estimate.get("over_total_goals", {}).get(target)
                                else:
                                    model_prob = estimate.get("under_total_goals", {}).get(str(line))
                        # Do not promote a market just because its price fits the range:
                        # require a mapped model probability and a provisional edge over
                        # the odds-implied probability. The model is not calibrated yet.
                        if not isinstance(model_prob, (int, float)) or not 0.0 < model_prob < 1.0:
                            continue
                        implied_probability = 1.0 / float(odd)
                        estimated_edge = float(model_prob) - implied_probability
                        if estimated_edge < 0.02:
                            continue
                        option = {
                            "market": market_label,
                            "odd": float(odd),
                            "model_prob": float(model_prob),
                            "implied_probability": implied_probability,
                            "estimated_edge": estimated_edge,
                            "bookmaker": odds_row.get("bookmaker", "Casa no identificada"),
                        }
                        if 1.35 <= odd <= 1.60:
                            main_options.append(option)
                        if odd >= 1.70:
                            # High-risk candidates may include goals, draw, and BTTS;
                            # numeric score patterns only add context to this slot.
                            risk_options.append(option)

                    # Keep one stable high-risk slot in the UI, whether or not a suitable
                    # live market exists. This slot is also the only place for numerology.
                    if main_options:
                        chosen_main = max(
                            main_options,
                            key=lambda item: item["model_prob"] if item["model_prob"] is not None else -1,
                        )
                        st.markdown('<div class="tip-section-heading"><span class="tip-heading-icon">◈</span><span>TIP PRINCIPAL</span><span class="tip-heading-status">EN VIVO</span></div>', unsafe_allow_html=True)
                        st.markdown(
                            f'<div class="tip-card">'
                            f'<div class="tip-card-title">{html.escape(chosen_main["market"])}</div>'
                            f'<div class="tip-card-meta">{html.escape(chosen_main["bookmaker"])} · Probabilidad estimada {chosen_main["model_prob"]:.1%} · Implícita {chosen_main["implied_probability"]:.1%} · Ventaja estimada {chosen_main["estimated_edge"]:.1%}</div></div>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.info("Sin oportunidades por ahora.")

                    if risk_options:
                        risk_options.sort(
                            key=lambda item: item["model_prob"] if item["model_prob"] is not None else -1,
                            reverse=True,
                        )
                        selected_risk = risk_options[:2]
                        st.markdown('<div class="tip-section-heading risk-heading"><span class="tip-heading-icon">⌁</span><span>TIP DE ALTO RIESGO</span><span class="tip-heading-status">RIESGO ALTO</span></div>', unsafe_allow_html=True)
                        for risk_item in selected_risk:
                            st.markdown(
                                f'<div class="tip-card risk-tip-card">'
                                f'<div class="tip-card-title">{html.escape(risk_item["market"])}</div>'
                                f'<div class="tip-card-meta">{html.escape(risk_item["bookmaker"])} · Probabilidad estimada {risk_item["model_prob"]:.1%} · Implícita {risk_item["implied_probability"]:.1%} · Ventaja estimada {risk_item["estimated_edge"]:.1%}</div></div>',
                                unsafe_allow_html=True,
                            )
                        risk_stats = st.session_state.stats_cache.get(str(fixture_id), [])
                        fixture_teams = fixture.get("teams") or {}
                        risk_home_id = (fixture_teams.get("home") or {}).get("id")
                        risk_away_id = (fixture_teams.get("away") or {}).get("id")
                        risk_home_corners = safe_stat_for_team(risk_stats, "Corner Kicks", risk_home_id)
                        risk_away_corners = safe_stat_for_team(risk_stats, "Corner Kicks", risk_away_id)
                        risk_home_yellow = safe_stat_for_team(risk_stats, "Yellow Cards", risk_home_id)
                        risk_away_yellow = safe_stat_for_team(risk_stats, "Yellow Cards", risk_away_id)
                        risk_context_bits = [score_pattern_context(home_score, away_score)]
                        if isinstance(risk_home_corners, (int, float)) and isinstance(risk_away_corners, (int, float)):
                            if abs(risk_home_corners - risk_away_corners) >= 3:
                                leader = home_name if risk_home_corners > risk_away_corners else away_name
                                risk_context_bits.append(f"desequilibrio de córners a favor de {leader} ({risk_home_corners:.0f}–{risk_away_corners:.0f})")
                            else:
                                risk_context_bits.append(f"córners relativamente equilibrados ({risk_home_corners:.0f}–{risk_away_corners:.0f})")
                        if isinstance(risk_home_yellow, (int, float)) and isinstance(risk_away_yellow, (int, float)):
                            risk_context_bits.append(f"tarjetas amarillas {risk_home_yellow:.0f}–{risk_away_yellow:.0f}")
                        pattern_matches = numerology_context(
                            home_score, away_score,
                            risk_home_corners, risk_away_corners,
                            risk_home_yellow, risk_away_yellow,
                        )
                        if pattern_matches:
                            risk_context_bits.extend(pattern_matches)
                        else:
                            risk_context_bits.append("sin coincidencia numérica clara entre marcador y córners/tarjetas")
                        st.caption(
                            "Numerología/contexto del alto riesgo: " + "; ".join(risk_context_bits)
                            + ". Es solo una coincidencia descriptiva para contextualizar el tip de riesgo; no predice un marcador ni genera apuestas por sí sola. No se inventan estadísticas faltantes."
                        )
                    else:
                        st.markdown('<div class="tip-section-heading risk-heading"><span class="tip-heading-icon">⌁</span><span>TIP DE ALTO RIESGO</span><span class="tip-heading-status">RIESGO ALTO</span></div>', unsafe_allow_html=True)
                        st.info("Sin oportunidad de alto riesgo por ahora.")

                    if not match_odds:
                        odds_error = st.session_state.get("live_odds_error", "")
                        if odds_error:
                            st.warning("No se pudieron actualizar las cuotas en vivo. No se inventan mercados. " + str(odds_error))
                        else:
                            st.caption("La API no devolvió cuotas en vivo para este partido. Puede faltar cobertura de la casa o del mercado.")
                    odds_stamp = st.session_state.get("live_odds_last_fetch")
                    if odds_stamp:
                        st.caption(f"Cuotas verificadas por última vez: {odds_stamp}. Las cuotas pueden cambiar o suspenderse.")
                    st.caption("Las cuotas reales filtran los mercados disponibles; las probabilidades del modelo son exploratorias y aún no están calibradas. La numerología solo aporta contexto al tip de alto riesgo.")
                    action_cols = st.columns(4)
                    action_specs = [
                        ("⚽ Goles", "goals"),
                        ("🚩 Córners", "corners"),
                        ("🤝 Empate", "draw"),
                        ("🥅 Ambos marcan", "btts"),
                    ]
                    for action_col, (action_label, action_key) in zip(action_cols, action_specs):
                        with action_col:
                            if st.button(action_label, key=f"match_action_{fixture_id}_{action_key}"):
                                st.session_state["selected_match_detail"] = {
                                    "fixture_id": fixture_id,
                                    "market": action_key,
                                }
                    selected_detail = st.session_state.get("selected_match_detail") or {}
                    if str(selected_detail.get("fixture_id")) == str(fixture_id):
                        market_names = {
                            "goals": "Goles",
                            "corners": "Córners",
                            "draw": "Empate",
                            "btts": "Ambos equipos marcan",
                        }
                        selected_market = selected_detail.get("market")
                        st.markdown(f"**Vista seleccionada: {market_names.get(selected_market, 'Mercado')}**")
                        if selected_market == "goals":
                            remaining = estimate.get("expected_total_goals_remaining")
                            if estimate.get("available") and isinstance(remaining, (int, float)):
                                st.write(f"Marcador actual: {home_score}–{away_score}. Media exploratoria de goles restantes: {remaining:.2f}.")
                            else:
                                st.info(estimate.get("reason") or "No hay datos suficientes para estimar goles restantes.")
                        elif selected_market == "draw":
                            probability = estimate.get("draw_final")
                            if estimate.get("available") and isinstance(probability, (int, float)):
                                st.write(f"Probabilidad exploratoria de empate final: {probability:.1%}.")
                            else:
                                st.info(estimate.get("reason") or "No hay datos suficientes para estimar empate.")
                        elif selected_market == "btts":
                            probability = estimate.get("btts_final")
                            if estimate.get("available") and isinstance(probability, (int, float)):
                                if estimate.get("btts_already_settled"):
                                    st.write("Ambos equipos ya marcaron: el mercado «ambos marcan» ya se cumplió.")
                                else:
                                    st.write(f"Probabilidad exploratoria de que ambos equipos marquen al final: {probability:.1%}.")
                            else:
                                st.info(estimate.get("reason") or "No hay datos suficientes para estimar ambos marcan.")
                        elif selected_market == "corners":
                            st.write("Consulta la pestaña Córners para ver el ritmo en vivo y la referencia histórica disponible.")

                        # Visualización esquemática del campo; no representa posiciones reales de jugadores.
                        st.markdown(
                            f"""
                            <div style="background:linear-gradient(90deg,#16452f,#1b5839);border:1px solid #4d8b63;border-radius:12px;padding:12px;margin:10px 0">
                              <div style="text-align:center;color:#d7f5df;font-weight:800;margin-bottom:8px">VISTA DEL PARTIDO · {html.escape(str(minute if minute is not None else 'N/D'))}'</div>
                              <svg viewBox="0 0 320 150" role="img" aria-label="Campo de fútbol esquemático" style="width:100%;max-height:180px">
                                <rect x="3" y="3" width="314" height="144" rx="4" fill="none" stroke="#b6e2c2" stroke-width="1.5"/>
                                <line x1="160" y1="3" x2="160" y2="147" stroke="#b6e2c2" stroke-width="1.2"/>
                                <circle cx="160" cy="75" r="24" fill="none" stroke="#b6e2c2" stroke-width="1.2"/>
                                <circle cx="160" cy="75" r="2.5" fill="#b6e2c2"/>
                                <rect x="3" y="40" width="38" height="70" fill="none" stroke="#b6e2c2" stroke-width="1.2"/>
                                <rect x="279" y="40" width="38" height="70" fill="none" stroke="#b6e2c2" stroke-width="1.2"/>
                                <circle cx="64" cy="75" r="5" fill="#FACC15"/><circle cx="256" cy="75" r="5" fill="#F4F4F5"/>
                                <text x="64" y="64" text-anchor="middle" font-size="9" fill="#ffffff">LOCAL</text>
                                <text x="256" y="64" text-anchor="middle" font-size="9" fill="#ffffff">VISITANTE</text>
                              </svg>
                              <div style="display:flex;justify-content:space-between;gap:8px;color:#f4f4f5;font-size:12px;font-weight:700">
                                <span>{html.escape(str(home_name))} · {home_score}</span>
                                <span>{away_score} · {html.escape(str(away_name))}</span>
                              </div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                        # H2H solo bajo demanda y cacheado para respetar la cuota de API.
                        home_id = ((fixture.get("teams") or {}).get("home") or {}).get("id")
                        away_id = ((fixture.get("teams") or {}).get("away") or {}).get("id")
                        h2h_key = f"{home_id}-{away_id}"
                        if "h2h_cache" not in st.session_state:
                            st.session_state.h2h_cache = {}
                        if st.button("📚 Consultar últimos enfrentamientos directos", key=f"h2h_{fixture_id}"):
                            if not home_id or not away_id:
                                st.warning("La API no entregó los identificadores de ambos equipos.")
                            elif h2h_key not in st.session_state.h2h_cache:
                                try:
                                    h2h_payload = api_get("fixtures/headtohead", {"h2h": h2h_key, "last": 5})
                                    st.session_state.h2h_cache[h2h_key] = h2h_payload.get("response") or []
                                except Exception as h2h_exc:
                                    st.session_state.h2h_cache[h2h_key] = {"error": str(h2h_exc)}
                        h2h_data = st.session_state.get("h2h_cache", {}).get(h2h_key)
                        if isinstance(h2h_data, dict) and h2h_data.get("error"):
                            st.warning(f"No se pudieron consultar los enfrentamientos: {h2h_data['error']}")
                        elif isinstance(h2h_data, list):
                            if h2h_data:
                                h2h_rows = []
                                for past in h2h_data:
                                    past_fixture = past.get("fixture") or {}
                                    past_teams = past.get("teams") or {}
                                    past_goals = past.get("goals") or {}
                                    past_home = past_teams.get("home") or {}
                                    past_away = past_teams.get("away") or {}
                                    h2h_rows.append({
                                        "Fecha": (past_fixture.get("date") or "")[:10],
                                        "Local": past_home.get("name", "N/D"),
                                        "Marcador": f"{past_goals.get('home', '—')} – {past_goals.get('away', '—')}",
                                        "Visitante": past_away.get("name", "N/D"),
                                    })
                                st.dataframe(h2h_rows, use_container_width=True, hide_index=True)
                            else:
                                st.info("La API no devolvió enfrentamientos directos anteriores para esta pareja.")

                if cards_shown == 0:
                    st.info("No hay partidos con una señal principal en esta ronda. Los partidos sin estadísticas o con señal débil se omiten.")
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
                        if (history.get("pending") or history.get("corners_pending")) and st.button("📚 Consultar historial de este partido", key=f"load_history_global_{((item.get('fixture') or {}).get('fixture') or {}).get('id')}"):
                            try:
                                history_cache = st.session_state.setdefault("automatic_history_cache", {})
                                history_cache["_automatic_history_stats_calls"] = 0
                                history_cache["_automatic_history_team_fixture_calls"] = 0
                                item["automatic_history"] = build_automatic_history(
                                    item["fixture"],
                                    api_get=api_get,
                                    cache=history_cache,
                                    stats_budget=8,
                                    live_corner_finalizer=lambda completed_fixture, final_stats: (
                                        finalize_live_corner_fixture(LIVE_CORNER_CAPTURE_DB, completed_fixture, final_stats)
                                    ),
                                )
                            except Exception as history_exc:
                                item["automatic_history"] = {"available": False, "pending": True, "note": f"No se pudo consultar el historial: {history_exc}"}
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
                            # Live-first fallback: if history is unavailable, estimate remaining
                            # corner pace from the observed match, using shots as a weak context cue.
                            history_used = hist_rate is not None
                            if hist_rate is None:
                                hist_rate = 9.6
                            live_projection = total_now * 90 / max(1, minute)
                            projected = (0.55 * hist_rate + 0.45 * live_projection) if history_used else max(total_now, 0.70 * hist_rate + 0.30 * live_projection)
                            shots_total = (item.get("home_shots") or 0) + (item.get("away_shots") or 0)
                            if isinstance(shots_total, (int, float)) and shots_total >= 10 and minute >= 20:
                                projected *= 1.05
                            # Round projected total to a sensible half-corner line.
                            import math
                            suggested_line = max(0.5, math.floor(projected * 2) / 2)
                            line_text = str(int(suggested_line)) if suggested_line.is_integer() else f"{suggested_line:.1f}"
                            remaining_expected = max(0.0, projected - total_now)
                            fixture_id = ((item.get("fixture") or {}).get("fixture") or {}).get("id")
                            persist_analysis_snapshot(
                                fixture_id, "corners",
                                {"league": (((item.get("fixture") or {}).get("league") or {}).get("name")),
                                 "home": ((((item.get("fixture") or {}).get("teams") or {}).get("home") or {}).get("name")),
                                 "away": ((((item.get("fixture") or {}).get("teams") or {}).get("away") or {}).get("name")),
                                 "minute": minute,
                                 "home_score": (((item.get("fixture") or {}).get("goals") or {}).get("home")),
                                 "away_score": (((item.get("fixture") or {}).get("goals") or {}).get("away"))},
                                {"home_corners": item.get("home_corners"), "away_corners": item.get("away_corners"),
                                 "total_corners_now": total_now, "historical_home_for": history.get("home_corners_for"),
                                 "historical_away_for": history.get("away_corners_for"), "history_used": history_used,
                                 "shots_total": shots_total},
                                {"projected_total_corners": projected, "remaining_expected_corners": remaining_expected,
                                 "suggested_line": suggested_line, "history_note": history.get("note")},
                            )
                            # Match live corner markets to real odds from API-Football.
                            # A price alone is never enough: require a provisional model edge.
                            fixture_id = ((item.get("fixture") or {}).get("fixture") or {}).get("id")
                            live_rows = best_live_odds_by_market(st.session_state.get("live_odds_by_fixture", {}).get(str(fixture_id), []))
                            corner_options = []
                            remaining_mean = max(0.05, remaining_expected * 0.70)
                            for odds_row in live_rows:
                                market_label = classify_market(odds_row)
                                odd = odds_row.get("odd")
                                if not market_label or "córner" not in market_label.casefold() or not isinstance(odd, (int, float)):
                                    continue
                                import re
                                line_match = re.search(r"(\d+(?:[.,]\d+)?)", market_label)
                                if not line_match:
                                    continue
                                market_line = float(line_match.group(1).replace(",", "."))
                                if market_label.startswith("Más de "):
                                    needed = max(0, int(market_line - total_now + 0.5))
                                    model_prob = poisson_at_least(remaining_mean, needed)
                                elif market_label.startswith("Menos de "):
                                    max_remaining = int(market_line - total_now)
                                    model_prob = sum(poisson_pmf(remaining_mean, n) for n in range(max_remaining + 1)) if max_remaining >= 0 else 0.0
                                else:
                                    continue
                                if not isinstance(model_prob, (int, float)) or not 0 < model_prob < 1:
                                    continue
                                implied = 1.0 / float(odd)
                                edge = float(model_prob) - implied
                                if edge < 0.02:
                                    continue
                                corner_options.append({
                                    "market": market_label, "odd": float(odd),
                                    "probability": float(model_prob), "edge": edge,
                                    "bookmaker": odds_row.get("bookmaker", "Casa no identificada"),
                                })
                            main_options = [option for option in corner_options if 1.25 <= option["odd"] < 1.60]
                            risk_options = [option for option in corner_options if option["odd"] >= 1.60]
                            st.markdown('<div class="tip-section-heading"><span class="tip-heading-icon">◈</span><span>TIP PRINCIPAL · CÓRNERS</span></div>', unsafe_allow_html=True)
                            if main_options:
                                chosen = max(main_options, key=lambda option: option["edge"])
                                st.markdown(
                                    f'<div class="tip-card">'
                                    f'<div class="tip-card-title">{html.escape(chosen["market"])}</div>'
                                    f'<div class="tip-card-meta">Cuota {chosen["odd"]:.2f} · {html.escape(chosen["bookmaker"])} · probabilidad exploratoria {chosen["probability"]:.1%}</div></div>',
                                    unsafe_allow_html=True,
                                )
                            else:
                                st.info("Sin oportunidad confirmada por ahora.")
                            st.markdown('<div class="tip-section-heading risk-heading"><span class="tip-heading-icon">⌁</span><span>TIP DE ALTO RIESGO · CÓRNERS</span></div>', unsafe_allow_html=True)
                            if risk_options:
                                chosen_risk = max(risk_options, key=lambda option: option["edge"])
                                st.markdown(
                                    f'<div class="tip-card risk-tip-card">'
                                    f'<div class="tip-card-title">{html.escape(chosen_risk["market"])}</div>'
                                    f'<div class="tip-card-meta">Cuota {chosen_risk["odd"]:.2f} · {html.escape(chosen_risk["bookmaker"])} · probabilidad exploratoria {chosen_risk["probability"]:.1%}</div></div>',
                                    unsafe_allow_html=True,
                                )
                            else:
                                st.info("Sin oportunidad confirmada por ahora.")
                            corner_patterns = numerology_context(
                                (item.get("fixture", {}).get("goals") or {}).get("home"),
                                (item.get("fixture", {}).get("goals") or {}).get("away"),
                                item.get("home_corners"), item.get("away_corners"),
                                item.get("home_yellow"), item.get("away_yellow"),
                            )
                            st.caption(
                                f"Proyección exploratoria: {projected:.1f} córners totales · actuales {total_now} · minuto {minute} · restantes estimados {remaining_expected:.1f}. "
                                + ("Se combina historial con ritmo en vivo." if history_used else "Falta historial específico; se usa una referencia genérica.")
                                + " La estimación no está calibrada y no garantiza valor real."
                            )
                            if minute <= 5:
                                st.caption("Partido muy reciente: el ritmo en vivo todavía tiene poca muestra.")
                    st.divider()
            else:
                st.info("Pulsa «Escanear todos los partidos en vivo» para obtener el análisis automático.")

        with tab_overview:
            st.subheader("Rendimiento del modelo")
            st.caption("Historial de señales, verificación retrospectiva y evaluación de calidad del pronóstico.")

            st.markdown("#### Resultados finales · Supabase")
            st.caption("Verifica en API-Football los últimos 100 partidos referenciados tanto por el registro central de pronósticos como por las capturas históricas. Registra marcadores, córners y tarjetas amarillas confirmados; los resultados idénticos no se vuelven a insertar. El escaneo está limitado para proteger el cupo diario de API-Football.")
            if st.button("Verificar y sincronizar resultados finales", key="sync_finished_outcomes"):
                try:
                    _outcome_url = str(st.secrets.get("SUPABASE_URL", "") or os.getenv("SUPABASE_URL", "")).strip()
                    _outcome_key = str(st.secrets.get("SUPABASE_SECRET_KEY", "") or os.getenv("SUPABASE_SECRET_KEY", "")).strip()
                    _outcome_result = sync_finished_fixture_outcomes(
                        _outcome_url, _outcome_key, api_get
                    )
                    st.session_state["outcome_sync_result"] = _outcome_result
                    st.session_state["outcome_sync_error"] = ""
                except Exception as _outcome_exc:
                    st.session_state["outcome_sync_error"] = f"{type(_outcome_exc).__name__}: {_outcome_exc}"
            _outcome_result = st.session_state.get("outcome_sync_result")
            if _outcome_result:
                _outcome_cols = st.columns(4)
                _outcome_cols[0].metric("Partidos revisados", _outcome_result.get("checked", 0))
                _outcome_cols[1].metric("Finalizados", _outcome_result.get("finished", 0))
                _outcome_cols[2].metric("Resultados nuevos", _outcome_result.get("inserted", 0))
                _outcome_cols[3].metric("Sin cambios", _outcome_result.get("unchanged", 0))
                st.caption(f"Partidos en histórico: {_outcome_result.get('fixtures_found', 0)} · Sin finalizar/sin datos: {_outcome_result.get('skipped', 0)}")
                for _outcome_error in (_outcome_result.get("errors") or [])[:5]:
                    st.warning(_outcome_error)
                if len(_outcome_result.get("errors") or []) > 5:
                    st.caption(f"Y {len(_outcome_result['errors']) - 5} errores adicionales.")
            if st.session_state.get("outcome_sync_error"):
                st.error(f"No se pudo sincronizar los resultados: {st.session_state['outcome_sync_error']}")

            st.markdown("#### Evaluación histórica · Supabase")
            st.caption("Métricas calculadas desde la vista analysis_snapshot_evaluation. Solo cuenta pronósticos con resultado final verificado.")
            if st.button("Actualizar evaluación del modelo", key="refresh_supabase_evaluation"):
                try:
                    _eval_url = str(st.secrets.get("SUPABASE_URL", "") or os.getenv("SUPABASE_URL", "")).strip()
                    _eval_key = str(st.secrets.get("SUPABASE_SECRET_KEY", "") or os.getenv("SUPABASE_SECRET_KEY", "")).strip()
                    _eval_rows = load_supabase_evaluations(_eval_url, _eval_key)
                    st.session_state["supabase_evaluation_rows"] = _eval_rows
                    st.session_state["supabase_evaluation_summary"] = summarize_supabase_evaluations(_eval_rows)
                    st.session_state["supabase_evaluation_error"] = ""
                except Exception as _eval_exc:
                    st.session_state["supabase_evaluation_error"] = f"{type(_eval_exc).__name__}: {_eval_exc}"
            _eval_summary = st.session_state.get("supabase_evaluation_summary")
            if _eval_summary:
                _eval_cols = st.columns(4)
                _eval_cols[0].metric("Análisis guardados", _eval_summary["total"])
                _eval_cols[1].metric("Con resultado verificado", _eval_summary["verified"])
                _eval_cols[2].metric("Pendientes", _eval_summary["pending"])
                _eval_cols[3].metric("Partidos distintos", _eval_summary["fixtures"])
                st.markdown("**Precisión de goles**")
                _goal_cols = st.columns(3)
                _goal_cols[0].metric("Capturas evaluadas", _eval_summary["goals_count"])
                _goal_cols[1].metric("Error medio absoluto", f'{_eval_summary["goals_mae"]:.2f}' if _eval_summary["goals_mae"] is not None else "N/D")
                _goal_cols[2].metric("Sesgo (proyección − real)", f'{_eval_summary["goals_bias"]:+.2f}' if _eval_summary["goals_bias"] is not None else "N/D")
                st.caption(
                    f"Partidos independientes: {_eval_summary['goals_fixtures']} · "
                    f"Clasificación: {_eval_summary['goals_reliability']}. "
                    "La clasificación mide volumen de evidencia, no garantiza aciertos."
                )
                st.markdown("**Precisión de córners**")
                _corner_cols = st.columns(3)
                _corner_cols[0].metric("Capturas evaluadas", _eval_summary["corners_count"])
                _corner_cols[1].metric("Error medio absoluto", f'{_eval_summary["corners_mae"]:.2f}' if _eval_summary["corners_mae"] is not None else "N/D")
                _corner_cols[2].metric("Sesgo (proyección − real)", f'{_eval_summary["corners_bias"]:+.2f}' if _eval_summary["corners_bias"] is not None else "N/D")
                st.caption(
                    f"Partidos independientes: {_eval_summary['corners_fixtures']} · "
                    f"Clasificación: {_eval_summary['corners_reliability']}. "
                    "La clasificación mide volumen de evidencia, no garantiza aciertos."
                )
                st.markdown("**Precisión según el minuto de captura**")
                st.caption("La clasificación de cada tramo se calcula por partidos distintos, no por cantidad de capturas repetidas: menos de 10 = muestra insuficiente; 10–29 = en observación; 30 o más = base amplia en seguimiento.")
                _minute_rows = summarize_evaluations_by_minute(st.session_state.get("supabase_evaluation_rows", []))
                if _minute_rows:
                    st.dataframe(_minute_rows, use_container_width=True, hide_index=True)
                else:
                    st.info("Todavía no hay suficientes muestras verificadas para comparar por minuto.")
            if st.session_state.get("supabase_evaluation_error"):
                st.error(f"No se pudo cargar la evaluación: {st.session_state['supabase_evaluation_error']}")

            st.markdown("#### Registro central de pronósticos · SQLite")
            st.caption("Consulta de solo lectura del historial persistido. No modifica pronósticos ni completa resultados automáticamente.")
            if st.button("Consultar registro central", key="load_prediction_ledger_summary"):
                try:
                    # Reconcile the central ledger from the durable legacy CSV at read time too.
                    # This recovers valid historical rows even if no new scan has run in this session.
                    csv_rows_for_recovery = []
                    if SIGNAL_HISTORY_PATH.exists():
                        with SIGNAL_HISTORY_PATH.open("r", encoding="utf-8-sig", newline="") as history_file:
                            csv_rows_for_recovery = list(csv.DictReader(history_file))
                    recovery_rows = [
                        normalize_prediction_record(row)
                        for row in csv_rows_for_recovery
                        if isinstance(row, dict)
                    ]
                    recovery_valid = [row for row in recovery_rows if row["valid"]]
                    recovery_result = append_prediction_records(
                        PREDICTION_LEDGER_PATH, recovery_valid
                    ) if recovery_valid else {
                        "received": 0, "valid": 0, "invalid": 0, "inserted": 0, "duplicates": 0
                    }
                    _sb_url = str(st.secrets.get("SUPABASE_URL", "") or os.getenv("SUPABASE_URL", "")).strip()
                    _sb_key = str(st.secrets.get("SUPABASE_SECRET_KEY", "") or os.getenv("SUPABASE_SECRET_KEY", "")).strip()
                    supabase_result = None
                    supabase_read_error = ""
                    remote_ledger_rows = None
                    if _sb_url and _sb_key:
                        try:
                            if recovery_valid:
                                supabase_result = append_supabase_prediction_records(
                                    recovery_valid, _sb_url, _sb_key
                                )
                            remote_ledger_rows = load_supabase_prediction_records(_sb_url, _sb_key)
                        except Exception as supabase_exc:
                            supabase_read_error = f"{type(supabase_exc).__name__}: {supabase_exc}"
                    try:
                        csv_size_bytes = SIGNAL_HISTORY_PATH.stat().st_size if SIGNAL_HISTORY_PATH.exists() else 0
                    except OSError:
                        csv_size_bytes = None
                    st.session_state.prediction_ledger_recovery_diagnostics = {
                        "csv_rows": len(csv_rows_for_recovery),
                        "valid_rows": len(recovery_valid),
                        "invalid_rows": len(recovery_rows) - len(recovery_valid),
                        "csv_exists": SIGNAL_HISTORY_PATH.exists(),
                        "csv_path": str(SIGNAL_HISTORY_PATH),
                        "csv_size_bytes": csv_size_bytes,
                        "sqlite_exists": PREDICTION_LEDGER_PATH.exists(),
                        "sqlite_path": str(PREDICTION_LEDGER_PATH),
                        "paths_are_absolute": SIGNAL_HISTORY_PATH.is_absolute() and PREDICTION_LEDGER_PATH.is_absolute(),
                        "supabase_configured": bool(_sb_url and _sb_key),
                        "supabase_rows": len(remote_ledger_rows) if remote_ledger_rows is not None else None,
                        "supabase_error": supabase_read_error,
                        **recovery_result,
                    }
                    ledger_rows = (
                        remote_ledger_rows if remote_ledger_rows is not None
                        else load_prediction_records(PREDICTION_LEDGER_PATH)
                    )
                    verified_outcomes = load_verified_outcomes(PREDICTION_LEDGER_PATH)
                    st.session_state.prediction_ledger_snapshot = ledger_rows
                    st.session_state.prediction_outcome_snapshot = verified_outcomes
                    # Read-only projection from canonical forecasts to verified final results.
                    settlement_outcomes = load_latest_match_outcomes(_sb_url, _sb_key) if _sb_url and _sb_key else {}
                    st.session_state.prediction_settlement_projection = settle_prediction_rows(
                        ledger_rows, settlement_outcomes
                    )
                    st.session_state.prediction_settlement_error = ""
                    st.session_state.prediction_ledger_read_error = ""
                except (OSError, ValueError, TypeError, KeyError) as ledger_read_exc:
                    st.session_state.prediction_ledger_read_error = str(ledger_read_exc)
            recovery_diagnostics = st.session_state.get("prediction_ledger_recovery_diagnostics")
            if recovery_diagnostics:
                st.markdown("##### Diagnóstico de recuperación del histórico")
                recovery_cols = st.columns(5)
                recovery_cols[0].metric("Filas CSV", recovery_diagnostics.get("csv_rows", 0))
                recovery_cols[1].metric("Filas válidas", recovery_diagnostics.get("valid_rows", 0))
                recovery_cols[2].metric("Filas inválidas", recovery_diagnostics.get("invalid_rows", 0))
                recovery_cols[3].metric("Insertadas ahora", recovery_diagnostics.get("inserted", 0))
                recovery_cols[4].metric("Duplicadas", recovery_diagnostics.get("duplicates", 0))
                st.caption(
                    f"CSV: {'encontrado' if recovery_diagnostics.get('csv_exists') else 'no encontrado'} · "
                    f"{recovery_diagnostics.get('csv_path', str(SIGNAL_HISTORY_PATH))} · "
                    f"{recovery_diagnostics.get('csv_size_bytes') if recovery_diagnostics.get('csv_size_bytes') is not None else 'tamaño no disponible'} bytes"
                )
                st.caption(
                    f"SQLite: {'existente' if recovery_diagnostics.get('sqlite_exists') else 'se creó al recuperar'} · "
                    f"{recovery_diagnostics.get('sqlite_path', str(PREDICTION_LEDGER_PATH))}"
                )
                if not recovery_diagnostics.get("csv_exists"):
                    st.warning("No se encontró el CSV histórico en la ruta configurada. La base central no puede recuperar filas desde ese archivo.")
                elif recovery_diagnostics.get("csv_rows", 0) and not recovery_diagnostics.get("valid_rows", 0):
                    st.warning("El CSV contiene filas, pero ninguna cumple el esquema mínimo del registro central. Revisa los campos requeridos antes de migrar; no se descartó ni modificó el CSV.")
                if recovery_diagnostics.get("supabase_configured"):
                    if recovery_diagnostics.get("supabase_error"):
                        st.error(f"Almacenamiento remoto Supabase no disponible: {recovery_diagnostics['supabase_error']}")
                    else:
                        st.success(f"Supabase conectado: {recovery_diagnostics.get('supabase_rows', 0)} pronóstico(s) persistidos remotamente.")
                else:
                    st.warning("Supabase no está configurado para el registro de pronósticos. SQLite local puede perderse si el alojamiento reinicia su disco.")
                if not recovery_diagnostics.get("paths_are_absolute"):
                    st.info("Al menos una ruta de almacenamiento es relativa. La persistencia local después de reinicios depende de la plataforma; Supabase evita depender de ese disco.")
            if st.session_state.get("prediction_ledger_read_error"):
                st.warning(f"No se pudo consultar el registro central: {st.session_state.prediction_ledger_read_error}")
            elif "prediction_ledger_snapshot" in st.session_state:
                ledger_rows = st.session_state.prediction_ledger_snapshot
                verified_outcomes = st.session_state.get("prediction_outcome_snapshot", {})
                settlement_projection = st.session_state.get("prediction_settlement_projection")
                if settlement_projection:
                    st.markdown("##### Liquidación automática proyectada · resultados verificados")
                    st.caption("Cruce de solo lectura entre el registro central y latest_match_outcomes. No modifica pronósticos ni representa rentabilidad real; solo clasifica aciertos/fallos cuando mercado, selección y datos finales son inequívocos.")
                    settlement_cols = st.columns(4)
                    settlement_cols[0].metric("Pronósticos liquidados", settlement_projection["settled_count"])
                    settlement_cols[1].metric("Aciertos", settlement_projection["hit_count"])
                    settlement_cols[2].metric("Fallos", settlement_projection["miss_count"])
                    settlement_cols[3].metric("Pendientes de revisión", settlement_projection["pending_count"])
                    settled_rows = settlement_projection.get("settled", [])
                    if settled_rows:
                        recent_settled = sorted(settled_rows, key=lambda row: str(row.get("recorded_at") or ""), reverse=True)[:25]
                        st.dataframe([{
                            "Partido": f"{row.get('home') or 'Local'} vs {row.get('away') or 'Visitante'}",
                            "Mercado": row.get("market_type") or row.get("market") or "N/D",
                            "Selección": row.get("selection") or "N/D",
                            "Resultado": "ACIERTO" if row.get("outcome") == 1 else "FALLO",
                            "Fuente": row.get("outcome_source") or "resultado verificado",
                        } for row in recent_settled], use_container_width=True, hide_index=True)
                    if settlement_projection["settled_count"] == 0:
                        st.info("Aún no hay pronósticos que puedan liquidarse automáticamente con los resultados finales disponibles.")
                # Join only in memory for reporting; the original prediction rows remain immutable.
                # Join only in memory for reporting; the original prediction rows remain immutable.
                ledger_report_rows = []
                settlement_by_prediction = {
                    str(item.get("prediction_id") or ""): item
                    for item in (settlement_projection or {}).get("settled", [])
                    if str(item.get("prediction_id") or "").strip()
                }
                settlement_conflicts = []
                settlement_applied = 0
                for item in ledger_rows:
                    report_item = dict(item)
                    prediction_id = str(item.get("prediction_id") or "")
                    verified_result = verified_outcomes.get(prediction_id)
                    projected_result = settlement_by_prediction.get(prediction_id)
                    if verified_result:
                        report_item.update({
                            "outcome": verified_result["outcome"],
                            "outcome_verified": True,
                            "outcome_source": verified_result["outcome_source"],
                            "outcome_verified_at": verified_result["outcome_verified_at"],
                        })
                        if (
                            projected_result
                            and projected_result.get("outcome") in (0, 1)
                            and verified_result.get("outcome") in (0, 1)
                            and projected_result["outcome"] != verified_result["outcome"]
                        ):
                            settlement_conflicts.append({
                                "prediction_id": prediction_id,
                                "fixture_id": item.get("fixture_id"),
                                "market": item.get("market_type") or item.get("market"),
                                "selection": item.get("selection"),
                                "outcome_ledger": verified_result["outcome"],
                                "final_result_projection": projected_result["outcome"],
                            })
                            # Conflicting verified sources are preserved for audit but
                            # excluded from statistical scoring until manually reconciled.
                            report_item["outcome_ledger_verified"] = True
                            report_item["outcome_verified"] = False
                            report_item["evaluation_excluded_reason"] = "conflicting_verified_outcome_sources"
                    elif projected_result and projected_result.get("outcome") in (0, 1):
                        report_item.update({
                            "outcome": projected_result["outcome"],
                            "outcome_verified": True,
                            "outcome_source": projected_result.get("outcome_source") or "latest_match_outcomes",
                            "outcome_verified_at": projected_result.get("outcome_verified_at"),
                        })
                        settlement_applied += 1
                    ledger_report_rows.append(report_item)

                if settlement_applied:
                    st.info(
                        f"Se incorporaron {settlement_applied} resultados finales liquidados "
                        "a la evaluación estadística en esta consulta. El registro original permanece intacto."
                    )
                if settlement_conflicts:
                    st.error(
                        f"Se detectaron {len(settlement_conflicts)} discrepancias entre verificaciones previas "
                        "y la proyección del resultado final. Se conservaron las verificaciones previas y "
                        "se excluyen de cualquier corrección automática."
                    )
                    st.dataframe(settlement_conflicts, use_container_width=True, hide_index=True)

                # Exportar una copia portable del registro consultado, incluyendo
                # únicamente la última verificación disponible por pronóstico.
                if ledger_report_rows:
                    export_fields = list(dict.fromkeys(
                        field for row in ledger_report_rows for field in row.keys()
                    ))
                    export_buffer = io.StringIO()
                    export_writer = csv.DictWriter(
                        export_buffer,
                        fieldnames=export_fields,
                        extrasaction="ignore",
                    )
                    export_writer.writeheader()
                    export_writer.writerows(ledger_report_rows)
                    st.download_button(
                        "⬇️ Descargar registro central completo (CSV)",
                        data=export_buffer.getvalue().encode("utf-8-sig"),
                        file_name="football_lab_registro_pronosticos_verificados.csv",
                        mime="text/csv",
                        key="download_central_prediction_ledger",
                        help=(
                            "Exporta los pronósticos consultados junto con su última verificación disponible. "
                            "No modifica la base SQLite ni inventa resultados."
                        ),
                    )
                    st.caption(
                        "Guarda este CSV fuera del alojamiento de la aplicación. Incluye los pronósticos "
                        "y el estado de verificación disponible al momento de la consulta."
                    )
                else:
                    st.info("El registro central está vacío; no hay filas para exportar.")

                ledger_verified = sum(
                    1 for item in ledger_report_rows
                    if item.get("outcome_verified") and item.get("outcome") in (0, 1)
                )
                ledger_odds_verified = sum(1 for item in ledger_rows if item.get("odds_verified"))
                ledger_metrics = evaluate_binary_forecasts(ledger_report_rows, probability_key="probability")
                history_integrity = audit_prediction_history(ledger_report_rows)
                st.markdown("##### Integridad del histórico (solo lectura)")
                integrity_cols = st.columns(4)
                integrity_cols[0].metric("Duplicados exactos", history_integrity["exact_duplicate_rows"])
                integrity_cols[1].metric("Conflictos de resultado", history_integrity["contradictory_verified_outcome_groups"])
                integrity_cols[2].metric("Probabilidades inválidas", history_integrity["invalid_probability_rows"])
                integrity_cols[3].metric("Resultados verificados inválidos", history_integrity["verified_invalid_outcomes"])
                missing_integrity = [
                    {"Campo": field, "Registros sin dato": count}
                    for field, count in history_integrity["missing_metadata"].items()
                    if count
                ]
                if missing_integrity:
                    with st.expander("Ver metadatos faltantes"):
                        st.dataframe(missing_integrity, use_container_width=True, hide_index=True)
                if history_integrity["contradictory_event_samples"]:
                    st.warning("Hay eventos con resultados verificados contradictorios para la misma definición de mercado. Requieren revisión manual.")
                    st.dataframe(history_integrity["contradictory_event_samples"], use_container_width=True, hide_index=True)
                st.caption("La auditoría distingue duplicados exactos de snapshots legítimos tomados en distintos momentos. No modifica ni elimina el historial; todos los hallazgos requieren revisión manual.")

                # Auditar completitud de metadatos antes de comparar modelos o mercados.
                metadata_fields = [
                    ("Tipo de mercado", "market_type"),
                    ("Selección", "selection"),
                    ("Línea", "line"),
                    ("Liga", "league"),
                    ("Identificador de modelo", "model_id"),
                    ("Versión de modelo", "model_version"),
                ]
                metadata_quality_rows = [
                    {
                        "Campo": label,
                        "Registros sin dato": sum(
                            1 for item in ledger_rows
                            if item.get(field) in (None, "") or not str(item.get(field)).strip()
                        ),
                    }
                    for label, field in metadata_fields
                ]
                missing_model_versions = next(
                    item["Registros sin dato"] for item in metadata_quality_rows
                    if item["Campo"] == "Versión de modelo"
                )
                st.markdown("##### Integridad de metadatos")
                st.dataframe(metadata_quality_rows, use_container_width=True, hide_index=True)
                if missing_model_versions:
                    st.warning(
                        f"{missing_model_versions} de {len(ledger_rows)} pronósticos no tienen versión de modelo "
                        "registrada. Se agrupan como «unknown» y no deben compararse como si fueran versiones identificadas."
                    )
                ledger_cols = st.columns(4)
                ledger_cols[0].metric("Pronósticos guardados", len(ledger_rows))
                ledger_cols[1].metric("Resultados verificados", ledger_verified)
                ledger_cols[2].metric("Cuotas verificadas", ledger_odds_verified)
                ledger_cols[3].metric("Muestra evaluable", ledger_metrics["sample_size"])
                st.caption(
                    f"Registros verificados válidos: {ledger_metrics['raw_verified_sample_size']} · "
                    f"Snapshots repetidos excluidos del cálculo: {ledger_metrics['deduplicated_snapshots']}."
                )
                if ledger_metrics["sample_size"]:
                    st.caption(
                        f"Brier: {ledger_metrics['brier_score']:.3f} · "
                        f"Log loss: {ledger_metrics['log_loss']:.3f} · "
                        f"Brecha de calibración: {ledger_metrics['calibration_gap']:.1%}. "
                        "Son métricas descriptivas; no demuestran rentabilidad."
                    )
                    if not ledger_metrics["minimum_sample_reached"]:
                        st.warning(
                            f"Muestra pequeña: {ledger_metrics['sample_size']} eventos independientes evaluables. "
                            f"Se recomiendan al menos {ledger_metrics['minimum_sample']} para empezar a interpretar la calibración."
                        )
                else:
                    st.info("El registro aún no contiene resultados binarios verificados suficientes para calcular métricas.")

                # La lectura cronológica evita presentar métricas del histórico completo
                # como si fueran una prueba independiente. Solo el bloque posterior se puntúa.
                st.markdown("#### Auditoría de calidad por mercado y versión")
                ledger_temporal = evaluate_chronological_holdout(
                    ledger_report_rows,
                    probability_key="probability",
                )
                if ledger_temporal["available"]:
                    temporal_metrics = ledger_temporal["test_metrics"]
                    st.caption(
                        f"Prueba cronológica independiente: {ledger_temporal['train_fixture_count']} "
                        f"partidos anteriores para desarrollo y {ledger_temporal['test_fixture_count']} "
                        f"partidos posteriores para evaluación. Los snapshots de un mismo partido "
                        "permanecen en una sola partición."
                    )
                    temporal_cols = st.columns(4)
                    temporal_cols[0].metric("Partidos de prueba", ledger_temporal["test_fixture_count"])
                    temporal_cols[1].metric("Eventos independientes", temporal_metrics["sample_size"])
                    temporal_cols[2].metric(
                        "Brier de prueba",
                        f"{temporal_metrics['brier_score']:.3f}" if temporal_metrics["brier_score"] is not None else "N/D",
                    )
                    temporal_cols[3].metric(
                        "Brecha de calibración",
                        f"{temporal_metrics['calibration_gap']:.1%}" if temporal_metrics["calibration_gap"] is not None else "N/D",
                    )

                    st.markdown("##### Resultados posteriores por mercado")
                    if ledger_temporal["test_metrics_by_market"]:
                        st.dataframe(
                            [{
                                "Mercado": item["group"],
                                "Muestra independiente": item["sample_size"],
                                "Tasa observada": (
                                    f"{item['observed_rate']:.1%}"
                                    if item["observed_rate"] is not None else "N/D"
                                ),
                                "IC 95% tasa observada": (
                                    f"{item['observed_rate_ci_95'][0]:.1%} – {item['observed_rate_ci_95'][1]:.1%}"
                                    if item.get("observed_rate_ci_95") else "N/D"
                                ),
                                "Brier": item["brier_score"],
                                "Log loss": item["log_loss"],
                                "Brecha calibración": item["calibration_gap"],
                                "Diagnóstico": (
                                    "Muestra insuficiente" if not item["minimum_sample_reached"]
                                    else "Revisar calibración" if item["calibration_gap"] is not None and item["calibration_gap"] >= 0.10
                                    else "Descriptivo; no habilita apuestas"
                                ),
                            } for item in ledger_temporal["test_metrics_by_market"]],
                            use_container_width=True,
                            hide_index=True,
                        )
                    else:
                        st.caption("No hay mercados identificables en el bloque de prueba.")

                    st.markdown("##### Resultados posteriores por liga")
                    if ledger_temporal["test_metrics_by_league"]:
                        st.dataframe(
                            [{
                                "Liga": item["group"],
                                "Muestra independiente": item["sample_size"],
                                "Brier": item["brier_score"],
                                "Log loss": item["log_loss"],
                                "Brecha calibración": item["calibration_gap"],
                                "Diagnóstico": (
                                    "Muestra insuficiente" if not item["minimum_sample_reached"]
                                    else "Revisar calibración" if item["calibration_gap"] is not None and item["calibration_gap"] >= 0.10
                                    else "Sin alerta de muestra"
                                ),
                            } for item in ledger_temporal["test_metrics_by_league"]],
                            use_container_width=True,
                            hide_index=True,
                        )
                    else:
                        st.caption("No hay ligas identificables en el bloque de prueba.")

                    st.markdown("##### Resultados posteriores por mercado, línea y versión del modelo")
                    model_breakdown = ledger_temporal.get("test_metrics_by_market_line", [])
                    if model_breakdown:
                        st.dataframe(
                            [{
                                "Liga": item.get("league", "unknown"),
                                "Mercado": item["market"],
                                "Selección": item["selection"],
                                "Línea": item["line"],
                                "Fase": item["phase"],
                                "Modelo": item["model_id"],
                                "Versión": item["model_version"],
                                "Muestra independiente": item["sample_size"],
                                "Brier": item["brier_score"],
                                "Log loss": item["log_loss"],
                                "Brecha calibración": item["calibration_gap"],
                                "Elegibilidad": item["readiness_status"],
                                "Motivo / control": " | ".join(item["readiness_reasons"]) or "Solo seguimiento controlado; no habilita apuestas",
                            } for item in model_breakdown],
                            use_container_width=True,
                            hide_index=True,
                        )
                    else:
                        st.info(
                            "No hay suficientes metadatos de mercado y línea en la prueba posterior "
                            "para separar versiones de modelo. Los campos ausentes no se infieren."
                        )
                    st.markdown("##### Comparabilidad entre versiones (mismos partidos)")
                    version_comparisons = ledger_temporal.get("test_model_version_comparability", [])
                    if version_comparisons:
                        st.dataframe(
                            [{
                                "Liga": item.get("league", "unknown"),
                                "Mercado": item["market"],
                                "Selección": item["selection"],
                                "Línea": item["line"],
                                "Fase": item["phase"],
                                "Modelo": item["model_id"],
                                "Versión A": item["version_a"],
                                "Versión B": item["version_b"],
                                "Partidos comunes verificados": item["common_fixture_count"],
                                "Resultados coincidentes": item["matching_outcome_fixture_count"],
                                "Partidos puntuables": item["paired_metric_fixture_count"],
                                "Métricas pareadas disponibles": "Sí" if item["paired_metrics_available"] else "No",
                                "Brier A": round(item["brier_a"], 4) if item["brier_a"] is not None else "N/D",
                                "Brier B": round(item["brier_b"], 4) if item["brier_b"] is not None else "N/D",
                                "Delta Brier (B−A)": round(item["brier_delta_b_minus_a"], 4) if item["brier_delta_b_minus_a"] is not None else "N/D",
                                "Log loss A": round(item["log_loss_a"], 4) if item["log_loss_a"] is not None else "N/D",
                                "Log loss B": round(item["log_loss_b"], 4) if item["log_loss_b"] is not None else "N/D",
                                "Delta log loss (B−A)": round(item["log_loss_delta_b_minus_a"], 4) if item["log_loss_delta_b_minus_a"] is not None else "N/D",
                                "Comparabilidad": item["status"],
                            } for item in version_comparisons],
                            use_container_width=True,
                            hide_index=True,
                        )
                    else:
                        st.caption("No hay dos versiones del mismo modelo con una definición de mercado idéntica para comparar.")
                    st.caption(
                        "Solo se considera comparable una pareja de versiones cuando comparte al menos 30 partidos "
                        "con resultado verificado y la misma definición de mercado, selección, línea y fase. "
                        "Los deltas son B menos A: un valor negativo indica menor pérdida para B en esa métrica; "
                        "son métricas descriptivas del mismo grupo de partidos, no prueban superioridad estadística "
                        "ni rentabilidad."
                    )
                    st.caption(
                        "La elegibilidad exige al menos 30 eventos independientes en la prueba cronológica, "
                        "brecha de calibración inferior al 10% e identificación completa de modelo y versión. "
                        "«Apto» significa únicamente seguimiento controlado: no autoriza picks ni demuestra rentabilidad."
                    )
                else:
                    st.warning(
                        "La auditoría cronológica aún no está disponible: se requieren al menos 5 partidos "
                        "anteriores y 5 posteriores con fecha y zona horaria válidas (con la partición 80/20 "
                        "actual, el mínimo práctico es 21 partidos). No se sustituye esta "
                        "prueba por métricas del histórico completo."
                    )
                    if ledger_temporal.get("excluded_temporal_rows"):
                        st.caption(
                            f"Registros excluidos por identificador o fecha inválida/sin zona horaria: "
                            f"{ledger_temporal['excluded_temporal_rows']}."
                        )

                if verified_outcomes or settlement_applied:
                    st.markdown("##### Últimos resultados verificados")
                    result_rows = []
                    for item in reversed(ledger_report_rows):
                        if not item.get("outcome_verified"):
                            continue
                        result_rows.append({
                            "Partido": item.get("match") or item.get("fixture_id") or "N/D",
                            "Mercado": item.get("market") or "N/D",
                            "Selección": item.get("selection") or "N/D",
                            "Resultado": "Acertado" if item.get("outcome") == 1 else "No acertado",
                            "Fuente": item.get("outcome_source") or "N/D",
                            "Verificado": item.get("outcome_verified_at") or "N/D",
                        })
                    st.dataframe(result_rows[:30], use_container_width=True, hide_index=True)
                else:
                    st.info("Aún no hay resultados verificados en la tabla de auditoría.")
                st.caption("Los resultados se unen al pronóstico solo para consulta. La tabla original de pronósticos y el historial de correcciones permanecen intactos.")
            st.markdown("#### Verificación manual de resultados")
            st.caption(
                "Selecciona un pronóstico, introduce los datos finales comprobados y revisa la resolución. "
                "Nada se guarda hasta pulsar Confirmar y registrar resultado."
            )
            if "prediction_ledger_snapshot" not in st.session_state:
                st.info("Primero consulta el registro central para cargar los pronósticos disponibles.")
            else:
                existing_outcomes = st.session_state.get("prediction_outcome_snapshot", {})
                pending_predictions = [
                    item for item in st.session_state.prediction_ledger_snapshot
                    if item.get("prediction_id")
                    and str(item.get("prediction_id")) not in existing_outcomes
                ]
                supported_predictions = [
                    item for item in pending_predictions
                    if str(item.get("market_type") or "").strip().casefold()
                    in {"goals", "draw", "btts", "corners", "yellow_cards"}
                    and item.get("selection")
                ]
                st.caption(
                    f"Pendientes: {len(pending_predictions)} · "
                    f"Con mercado y selección compatibles: {len(supported_predictions)}."
                )
                if not supported_predictions:
                    st.info("No hay pronósticos pendientes con mercado y selección reconocidos. Los casos ambiguos se mantienen fuera de la verificación.")
                else:
                    prediction_options = {}
                    for item in supported_predictions:
                        match_label = item.get("match") or " vs ".join(
                            str(item.get(team_key) or "").strip()
                            for team_key in ("home", "away")
                        ).strip(" vs") or f"Partido {item.get('fixture_id') or 'sin nombre'}"
                        market_label = item.get("market") or item.get("market_type") or "Mercado"
                        selection_label = item.get("selection") or "Selección"
                        timestamp_label = item.get("recorded_at") or "Fecha N/D"
                        label = f"{match_label} · {market_label}: {selection_label} · {timestamp_label} · ID {item['prediction_id'][:8]}"
                        prediction_options[label] = item
                    selected_label = st.selectbox(
                        "Pronóstico pendiente",
                        list(prediction_options.keys()),
                        key="manual_outcome_prediction_select",
                    )
                    selected_prediction = prediction_options[selected_label]
                    selected_market_type = str(selected_prediction.get("market_type") or "").strip().casefold()
                    st.write(
                        f"**Selección:** {selected_prediction.get('selection')}  "
                        f"· **Mercado:** {selected_prediction.get('market') or selected_market_type}"
                    )
                    final_data = {}
                    if selected_market_type in {"goals", "draw", "btts"}:
                        score_cols = st.columns(2)
                        final_data["final_home_score"] = score_cols[0].number_input(
                            "Goles del local (final)", min_value=0, max_value=30, value=0,
                            step=1, key="manual_outcome_home_score"
                        )
                        final_data["final_away_score"] = score_cols[1].number_input(
                            "Goles del visitante (final)", min_value=0, max_value=30, value=0,
                            step=1, key="manual_outcome_away_score"
                        )
                    elif selected_market_type == "corners":
                        final_data["final_total_corners"] = st.number_input(
                            "Córners totales finales", min_value=0, max_value=100, value=0,
                            step=1, key="manual_outcome_total_corners"
                        )
                    elif selected_market_type == "yellow_cards":
                        final_data["final_total_yellow_cards"] = st.number_input(
                            "Tarjetas amarillas totales finales", min_value=0, max_value=30, value=0,
                            step=1, key="manual_outcome_total_yellow_cards"
                        )
                    resolution = resolve_binary_outcome(
                        market_type=selected_market_type,
                        selection=str(selected_prediction.get("selection") or ""),
                        home_team_name=str(selected_prediction.get("home") or ""),
                        away_team_name=str(selected_prediction.get("away") or ""),
                        **final_data,
                    )
                    if resolution.get("resolved"):
                        st.success(
                            "Resultado calculado para revisión: "
                            + ("ACERTADO" if resolution["outcome"] == 1 else "NO ACERTADO")
                        )
                        st.caption("Comprueba que los datos finales corresponden al partido y al mercado seleccionados antes de confirmar.")
                    else:
                        st.warning(
                            "No se puede resolver automáticamente este caso: "
                            + str(resolution.get("reason") or "datos no compatibles")
                            + ". No se registrará ningún resultado."
                        )
                    source_value = st.text_input(
                        "Fuente de comprobación",
                        value="Marcador/estadística final comprobada manualmente",
                        key="manual_outcome_source",
                    )
                    verifier_value = st.text_input(
                        "Verificado por",
                        placeholder="Escribe tu identificador o iniciales",
                        key="manual_outcome_verifier",
                    )
                    final_data_confirmed = st.checkbox(
                        "Confirmo que los datos finales corresponden a este partido y fueron comprobados.",
                        value=False,
                        key="manual_outcome_data_confirmed",
                    )
                    if st.button(
                        "Confirmar y registrar resultado",
                        key="confirm_manual_outcome",
                        type="primary",
                        disabled=not resolution.get("resolved") or not source_value.strip() or not verifier_value.strip() or not final_data_confirmed,
                    ):
                        try:
                            saved = record_verified_outcome(
                                PREDICTION_LEDGER_PATH,
                                str(selected_prediction["prediction_id"]),
                                int(resolution["outcome"]),
                                source=source_value.strip(),
                                verified_by=verifier_value.strip(),
                            )
                            if saved.get("inserted"):
                                st.success("Resultado verificado y guardado en el registro de auditoría.")
                            elif saved.get("duplicate"):
                                st.info("Ese resultado ya estaba registrado; no se creó un duplicado.")
                            st.session_state.prediction_ledger_snapshot = load_prediction_records(PREDICTION_LEDGER_PATH)
                            st.session_state.prediction_outcome_snapshot = load_verified_outcomes(PREDICTION_LEDGER_PATH)
                            st.rerun()
                        except (OSError, ValueError, TypeError, KeyError) as save_exc:
                            st.error(f"No se pudo registrar el resultado: {save_exc}")

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
                    audit = audit_forecast_dataset(uploaded_rows)
                    st.markdown("#### Auditoría de calidad del CSV")
                    audit_cols = st.columns(5)
                    audit_cols[0].metric("Filas del CSV", audit["row_count"])
                    audit_cols[1].metric("Pronósticos válidos", audit["distinct_valid_forecasts"])
                    audit_cols[2].metric("Duplicados", audit["duplicate_forecasts"])
                    audit_cols[3].metric("Metadatos inválidos", audit["invalid_metadata_rows"])
                    audit_cols[4].metric("Resultados verificados", audit["verified_valid_outcomes"])
                    if audit["verified_invalid_outcomes"]:
                        st.warning(f"{audit['verified_invalid_outcomes']} filas marcadas como verificadas tienen probabilidad o resultado inválido.")
                    st.caption(
                        f"Mercados identificados: {audit['market_count']} · "
                        f"Ligas identificadas: {audit['league_count']} · "
                        f"Probabilidades inválidas: {audit['invalid_probability_rows']}. "
                        "La auditoría no modifica el archivo ni completa resultados."
                    )
                    metrics = evaluate_binary_forecasts(uploaded_rows)
                    metric_cols = st.columns(6)
                    metric_cols[0].metric("Eventos evaluables", metrics["sample_size"])
                    metric_cols[1].metric("Brier score", f"{metrics['brier_score']:.3f}" if metrics["brier_score"] is not None else "N/D")
                    metric_cols[2].metric("Log loss", f"{metrics['log_loss']:.3f}" if metrics["log_loss"] is not None else "N/D")
                    metric_cols[3].metric("Brecha calibración", f"{metrics['calibration_gap']:.1%}" if metrics["calibration_gap"] is not None else "N/D")
                    metric_cols[4].metric("Snapshots repetidos", metrics["deduplicated_snapshots"])
                    metric_cols[5].metric("Filas excluidas", metrics["excluded"])
                    st.caption(
                        f"Registros verificados válidos antes de deduplicar: {metrics['raw_verified_sample_size']}. "
                        "La muestra evaluable cuenta como máximo un snapshot por partido, evento y versión del modelo."
                    )
                    if metrics["sample_size"]:
                        st.caption(
                            f"Probabilidad media pronosticada: {metrics['mean_probability']:.1%} frente a "
                            f"frecuencia real: {metrics['observed_rate']:.1%}. "
                            "Brier y Log loss: cuanto más bajos, mejor. La brecha de calibración pondera la diferencia entre probabilidad y frecuencia observada por intervalos."
                        )
                        if not metrics["minimum_sample_reached"]:
                            st.warning(
                                f"Muestra todavía pequeña: {metrics['sample_size']} eventos independientes evaluables; "
                                f"se recomienda reunir al menos {metrics['minimum_sample']} antes de interpretar la calibración."
                            )
                    else:
                        st.info("Todavía no hay filas con probabilidad válida y resultado binario marcado como verificado.")

                    if metrics["sample_size"]:
                        st.markdown("#### Validación cronológica por partido")
                        temporal = evaluate_chronological_holdout(uploaded_rows)
                        if temporal["available"]:
                            temporal_metrics = temporal["test_metrics"]
                            st.caption(
                                f"Separación temporal: {temporal['train_fixture_count']} partidos anteriores "
                                f"para desarrollo y {temporal['test_fixture_count']} partidos posteriores para prueba. "
                                "Los registros del mismo partido permanecen juntos."
                            )
                            temporal_cols = st.columns(3)
                            temporal_cols[0].metric("Muestra futura verificada", temporal_metrics["sample_size"])
                            temporal_cols[1].metric("Brier de prueba", f"{temporal_metrics['brier_score']:.3f}" if temporal_metrics["brier_score"] is not None else "N/D")
                            temporal_cols[2].metric("Log loss de prueba", f"{temporal_metrics['log_loss']:.3f}" if temporal_metrics["log_loss"] is not None else "N/D")

                            st.markdown("##### Prueba posterior por mercado")
                            holdout_markets = temporal["test_metrics_by_market"]
                            if holdout_markets:
                                st.dataframe(
                                    [{
                                        "Mercado": item["group"],
                                        "Muestra": item["sample_size"],
                                        "Brier": item["brier_score"],
                                        "Log loss": item["log_loss"],
                                        "Brecha calibración": item["calibration_gap"],
                                        "Estado": "Muestra suficiente" if item["minimum_sample_reached"] else "Muestra pequeña",
                                    } for item in holdout_markets],
                                    hide_index=True,
                                    use_container_width=True,
                                )
                            else:
                                st.caption("El bloque de prueba todavía no contiene resultados verificados agrupables por mercado.")

                            st.markdown("##### Prueba posterior por liga")
                            holdout_leagues = temporal["test_metrics_by_league"]
                            if holdout_leagues:
                                st.dataframe(
                                    [{
                                        "Liga": item["group"],
                                        "Muestra": item["sample_size"],
                                        "Brier": item["brier_score"],
                                        "Log loss": item["log_loss"],
                                        "Brecha calibración": item["calibration_gap"],
                                        "Estado": "Muestra suficiente" if item["minimum_sample_reached"] else "Muestra pequeña",
                                    } for item in holdout_leagues],
                                    hide_index=True,
                                    use_container_width=True,
                                )
                            else:
                                st.caption("El bloque de prueba todavía no contiene resultados verificados agrupables por liga.")
                        else:
                            st.info("Aún no hay suficientes partidos con fecha válida para la prueba cronológica. Se requieren al menos 5 partidos anteriores y 5 posteriores.")

                        st.markdown("#### Rendimiento por mercado")
                        market_groups = evaluate_forecasts_by_market(uploaded_rows)
                        if market_groups:
                            st.dataframe(
                                [{
                                    "Mercado": item["group"],
                                    "Muestra": item["sample_size"],
                                    "Brier": item["brier_score"],
                                    "Log loss": item["log_loss"],
                                    "Brecha calibración": item["calibration_gap"],
                                    "Estado": "Muestra suficiente" if item["minimum_sample_reached"] else "Muestra pequeña",
                                } for item in market_groups],
                                hide_index=True,
                                use_container_width=True,
                            )
                        else:
                            st.caption("El CSV no contiene etiquetas de mercado utilizables.")

                        st.markdown("#### Rendimiento por liga")
                        league_groups = evaluate_forecasts_by_group(uploaded_rows, group_key="league")
                        if league_groups:
                            st.dataframe(
                                [{
                                    "Liga": item["group"],
                                    "Muestra": item["sample_size"],
                                    "Brier": item["brier_score"],
                                    "Log loss": item["log_loss"],
                                    "Brecha calibración": item["calibration_gap"],
                                    "Estado": "Muestra suficiente" if item["minimum_sample_reached"] else "Muestra pequeña",
                                } for item in league_groups],
                                hide_index=True,
                                use_container_width=True,
                            )
                        else:
                            st.caption("El CSV no contiene etiquetas de liga utilizables.")
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
                st.caption(f"Registro guardado en el archivo local {SIGNAL_HISTORY_PATH}. En servicios de alojamiento con disco efímero, descarga el CSV para conservarlo fuera de la sesión.")
                if st.session_state.get("signal_history_write_error"):
                    st.warning(f"No se pudo guardar el registro en disco: {st.session_state.signal_history_write_error}")

        if not goal_results and not corner_results:
            st.info("Pulsa «Escanear todos los partidos en vivo» para generar el primer informe.")
        elif not goal_results:
            st.info("En esta ronda no hubo señales de goles que superaran el umbral experimental del 65%. Esto no significa que todos los partidos carezcan de datos ni que no existan candidatos de córners.")
            st.caption("El modelo necesita una referencia histórica compatible para estimar goles. Si no la encuentra, la señal se marca como no disponible; las estadísticas en vivo no sustituyen por sí solas una base histórica fiable.")


