import csv
import html
import io
import json
import os
from pathlib import Path
from datetime import datetime, timezone
import time
from typing import Any

import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from models.live_context import qualifies_as_corner_candidate, summarize_live_context
from models.backtest import evaluate_binary_predictions
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
    classify_market,
    extract_live_odds,
    numerology_context,
    score_pattern_context,
)

API_BASE = "https://v3.football.api-sports.io"
TIMEOUT_SECONDS = 15

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
  .fl-scan-progress-title { color:#FDE68A; font-size:11px; line-height:1.25; font-weight:850; letter-spacing:.12em; text-transform:uppercase; }
  .fl-scan-progress-percent { color:#FACC15; font-size:12px; line-height:1.25; font-weight:900; font-variant-numeric:tabular-nums; text-shadow:0 0 10px rgba(250,204,21,.24); }
  .fl-scan-progress-caption { display:flex; align-items:center; gap:6px; color:#8E929B; font-size:10px; line-height:1.35; margin:4px 0 0; }
  .fl-scan-progress-caption .fl-live-dot { width:5px; height:5px; flex:0 0 5px; border-radius:50%; background:#FACC15; box-shadow:0 0 8px #FACC15; animation:fl-live-pulse 1.2s ease-in-out infinite; }
  .fl-scan-progress-caption.is-done { color:#D6D3B8; }
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
     align-items:stretch !important; gap:12px !important;
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
      margin-top:0 !important;
    }
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
  .scan-running-status { position:relative; display:flex; align-items:center; gap:12px; overflow:hidden; color:#FACC15; margin:8px 2px 0; padding:12px 14px; border:1px solid rgba(250,204,21,.35); border-radius:14px; background:linear-gradient(110deg,#17191F,#0B0D10); font-size:.92rem; font-weight:700; }
  .scan-code-icon { display:inline-block; flex:0 0 auto; font-size:2rem; transform-origin:center; animation:scanner-spiral-spin .8s linear infinite; text-shadow:0 0 12px rgba(250,204,21,.8); }
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
    [class*="st-key-live_now_section"] > div > [data-testid="stExpander"] > details > summary { min-height:62px !important; padding:9px 10px 9px 14px !important; }
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
    border-bottom:1px solid rgba(250,204,21,.62) !important;
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
    .brand-header { top:44px !important; min-height:68px !important; padding:7px 10px !important; }
    .brand-header-main { min-height:54px !important; gap:8px !important; }
    .brand-mark { width:42px !important; height:42px !important; flex:0 0 42px !important; border-radius:12px !important; }
    .brand-mark svg { width:25px !important; height:25px !important; }
    .brand-title { font-size:clamp(1.05rem,4.8vw,1.45rem) !important; letter-spacing:0 !important; }
    .brand-subtitle { font-size:.62rem !important; letter-spacing:.7px !important; margin-top:2px !important; }
    .brand-pill { padding:4px 7px !important; font-size:.62rem !important; }
    [data-testid="stSidebar"] { z-index:1000 !important; }\n    [data-testid="stSidebar"] > div:first-child { padding-top:96px !important; }
    section.main > div.block-container { padding-top:112px !important; }
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
  .brand-pill { margin-left:auto; white-space:nowrap; color:#22C55E; border:1px solid #103B25; background:#062719; border-radius:999px; padding:6px 11px; font-size:.78rem; font-weight:700; }
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
  .h2h-match-row { display:grid; grid-template-columns:82px minmax(0,1fr) 70px minmax(0,1fr); gap:8px; align-items:center; padding:9px 4px; border-bottom:1px solid #34302A; font-size:.8rem; }
  .h2h-team { display:flex; align-items:center; gap:6px; min-width:0; overflow-wrap:anywhere; }
  .h2h-team img { width:22px; height:22px; object-fit:contain; flex:0 0 22px; }
  .h2h-match-row, .corner-h2h-row { animation:matchFlipIn .32s ease both; }
  .corner-h2h-row { display:grid; grid-template-columns:82px minmax(0,1fr) 70px minmax(0,1fr) 88px; gap:8px; align-items:center; padding:9px 4px; border-bottom:1px solid #34302A; font-size:.8rem; }
  .corner-history-grid {grid-template-columns:82px minmax(0,1fr) 74px minmax(0,1fr) 74px 85px;}
  .corner-h2h-value { color:#FACC15; font-weight:850; text-align:center; white-space:nowrap; }
  .h2h-score { text-align:center; color:#FACC15; font-weight:900; white-space:nowrap; }
  @keyframes matchFlipIn { from {opacity:0; transform:perspective(900px) rotateX(-8deg) translateY(-7px)} to {opacity:1; transform:perspective(900px) rotateX(0) translateY(0)} }
  @media(max-width:620px) {
    .match-action-grid {grid-template-columns:repeat(2,minmax(0,1fr));}
    .h2h-match-row {grid-template-columns:65px minmax(0,1fr) 48px minmax(0,1fr);font-size:.7rem;gap:4px;}
    /* Mantener cada partido histórico en una sola fila, compactando las seis columnas para móvil. */
    .corner-h2h-row.corner-history-grid {grid-template-columns:52px minmax(0,1fr) 22px minmax(0,1fr) 22px 30px;column-gap:3px;row-gap:0;padding:7px 4px;font-size:.62rem;line-height:1.25;min-width:0;width:100%;box-sizing:border-box;}
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
    .corner-h2h-row.corner-history-grid.corner-history-header > span:nth-child(6) {font-size:0;}
    .corner-h2h-row.corner-history-grid.corner-history-header > span:nth-child(6)::after {content:"Total";font-size:.56rem;}
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
  .goal-form-match { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:5px 9px; align-items:center; padding:9px 0; border-top:1px solid #34302A; color:#E4E4E7; font-size:.7rem; line-height:1.35; }
  .goal-form-match-meta { color:#FACC15; font-size:.63rem; font-weight:800; letter-spacing:.25px; margin-bottom:3px; }
  .goal-form-match-opponent { min-width:0; overflow-wrap:anywhere; word-break:normal; }
  .goal-form-match-teams { color:#E4E4E7; font-weight:650; }
  .goal-form-match-outcome { display:flex; align-items:center; justify-content:flex-end; gap:6px; white-space:nowrap; }
  .goal-form-match-score { color:#F4F4F5; font-size:.8rem; font-weight:950; white-space:nowrap; }
  .goal-form-match .goal-form-result { min-width:20px; }
  @media (max-width: 700px) { .goal-form-match { grid-template-columns:minmax(0,1fr) auto; gap:4px 6px; padding:8px 0; } .goal-form-match-teams { font-size:.66rem; } }
  .goal-form-result { display:inline-flex; justify-content:center; min-width:22px; padding:2px 5px; border-radius:5px; font-size:.65rem; font-weight:900; }
  .goal-form-result-v { color:#FFFFFF; background:#16A34A; }
  .goal-form-result-e { color:#FFFFFF; background:#6B7280; }
  .goal-form-result-d { color:#FFFFFF; background:#DC2626; }
  .goal-form-header { display:flex; align-items:center; gap:8px; margin-bottom:4px; min-width:0; }
  .goal-form-logo { width:34px; height:34px; object-fit:contain; flex:0 0 34px; }
  .goal-form-team { color:#E4E4E7; font-size:.78rem; font-weight:800; line-height:1.25; overflow-wrap:anywhere; }
  .goal-form-record { color:#FACC15; font-size:1.15rem; font-weight:900; margin:4px 0; }
  .goal-form-line { color:#BFC2CA; font-size:.68rem; line-height:1.45; }
  .goal-h2h-summary { margin:.5rem 0; border:1px solid #393326; border-radius:10px; padding:9px 11px; color:#D4D4D8; background:#15191F; font-size:.78rem; line-height:1.5; }
  .goal-last-goal { display:flex; align-items:center; flex-wrap:wrap; gap:8px; margin:.8rem 0 1rem; padding:12px 14px; border:2px solid #FACC15; border-radius:12px; background:linear-gradient(135deg,rgba(250,204,21,.16),#191C22 52%,#101216); box-shadow:0 0 0 1px rgba(250,204,21,.22),0 0 16px rgba(250,204,21,.16); color:#F4F4F5; font-size:.84rem; line-height:1.5; }
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
    border:1px solid #655522; border-radius:12px; background:linear-gradient(145deg,#201E16,#111419);
    padding:5px 3px; box-sizing:border-box;
  }
  .fl-match-minute { display:flex; align-items:baseline; justify-content:center; gap:1px; color:#FFE566; font-size:1.22rem; line-height:1.1; font-weight:850; font-variant-numeric:tabular-nums; letter-spacing:.1px; text-shadow:0 0 12px rgba(250,204,21,.12); }
  .fl-match-minute-main { font-size:1.22rem; font-weight:950; }
  .fl-match-clock-separator { color:#FACC15; opacity:.9; font-size:1rem; font-weight:850; }
  .fl-match-seconds { color:#FFF0A3; font-size:.96rem; font-weight:800; }
  .fl-match-live { display:inline-flex; align-items:center; justify-content:center; gap:5px; color:#FFE9E7; background:rgba(226,61,50,.13); border:1px solid rgba(226,61,50,.55); border-radius:999px; padding:3px 7px; font-size:.54rem; line-height:1; font-weight:900; letter-spacing:.65px; white-space:nowrap; }
  .fl-match-live::before { content:""; width:5px; height:5px; flex:0 0 5px; border-radius:50%; background:#F04438; box-shadow:0 0 6px rgba(240,68,56,.45); }
  .fl-match-teams { min-width:0; display:flex; flex-direction:column; gap:9px; }
  .fl-match-team {
    display:grid; grid-template-columns:34px 26px minmax(0,1fr); align-items:center; gap:8px;
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
    .fl-match-team { grid-template-columns:29px 21px minmax(0,1fr); gap:5px; min-height:30px; font-size:.77rem; }
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
    width:100% !important; min-width:100% !important; min-height:160px !important; height:160px !important;
    box-sizing:border-box !important; padding:20px 18px 20px 49% !important;
    border-radius:22px !important; border:2px solid #FACC15 !important;
    background-color:#090A0D !important;
    background-image:radial-gradient(ellipse at 20% 50%,rgba(250,204,21,.14),transparent 42%),linear-gradient(135deg,#090A0D,#17191F) !important;
    color:#F4F4F5 !important; font-size:clamp(1rem,3.8vw,1.35rem) !important;
    line-height:1.5 !important; font-weight:850 !important; white-space:pre-line !important;
    text-align:left !important; box-shadow:inset 0 0 24px rgba(250,204,21,.08),0 0 0 1px rgba(250,204,21,.12) !important;
  }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button::before {
    content:"" !important; position:absolute !important; left:4% !important; top:50% !important;
    width:min(38%,170px) !important; aspect-ratio:1 !important; height:auto !important;
    transform:translateY(-50%); border-radius:50% !important; border:3px solid #FACC15 !important;
    background-color:#090A0D !important;
    background-image:radial-gradient(circle at center,#FACC15 0 6%,#14151A 7% 14%,transparent 15%),repeating-radial-gradient(circle at center,transparent 0 10px,rgba(250,204,21,.55) 11px 13px,transparent 14px 20px),conic-gradient(from 0deg,transparent 0 12%,rgba(250,204,21,.95) 16%,transparent 28% 48%,rgba(250,204,21,.45) 53%,transparent 68%) !important;
    box-shadow:0 0 20px rgba(250,204,21,.45),inset 0 0 18px rgba(250,204,21,.25) !important;
    animation:scanner-radar-spin 3s linear infinite !important;
  }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] > button::after {
    content:"⚽" !important; position:absolute !important; left:23% !important; top:50% !important;
    transform:translate(-50%,-50%); width:40px !important; height:40px !important;
    display:flex !important; align-items:center !important; justify-content:center !important;
    font-size:clamp(1.8rem,6vw,2.7rem) !important; filter:drop-shadow(0 0 10px rgba(250,204,21,.75)) !important;
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
  .h2h-page-kicker, .h2h-page-kicker * {
    caret-color:transparent !important;
    user-select:none !important;
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
  .h2h-page-kicker + div { margin-top:0 !important; }
  section.main > div.block-container:has(.h2h-page-kicker) {
    padding-top:22px !important;
  }
  @media(max-width:640px) {
    section.main > div.block-container:has(.h2h-page-kicker) {
      padding-top:14px !important; padding-left:10px !important; padding-right:10px !important;
      max-width:100vw !important; overflow-x:hidden !important;
    }
    .h2h-page-kicker {
      margin-top:-65px !important; font-size:.94rem !important; letter-spacing:.045em !important;
      line-height:1.35 !important; margin-bottom:12px !important; padding:11px 10px !important;
      gap:7px !important; border-radius:9px !important;
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
    .h2h-history-list { width:100% !important; max-width:100% !important; overflow:hidden !important; }
    .h2h-match-row { grid-template-columns:64px minmax(0,1fr) 52px minmax(0,1fr) !important; gap:4px !important; padding:9px 5px !important; max-width:100% !important; overflow:hidden !important; }
    .h2h-match-row .h2h-date { font-size:.62rem !important; }
    .h2h-match-row .h2h-team { min-width:0 !important; gap:3px !important; font-size:.65rem !important; }
    .h2h-match-row .h2h-team img { width:16px !important; height:16px !important; flex-basis:16px !important; }
    .h2h-match-row .h2h-score { min-width:48px !important; padding:5px 3px !important; font-size:.78rem !important; border-radius:7px !important; }
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
/* Selector directo de la fila que contiene los cuatro botones */
div[data-testid="stHorizontalBlock"]:has([class*="st-key-home_nav_stats"]) {
 display:grid !important; grid-template-columns:repeat(4,minmax(0,1fr)) !important;
 grid-auto-flow:column !important; align-items:stretch !important; gap:5px !important;
 width:100% !important; max-width:100% !important; min-width:0 !important;
 overflow:hidden !important; flex-wrap:nowrap !important;
}
div[data-testid="stHorizontalBlock"]:has([class*="st-key-home_nav_stats"]) > div[data-testid="column"] {
 display:block !important; grid-column:auto !important; grid-row:1 !important;
 width:auto !important; max-width:none !important; min-width:0 !important;
 flex:none !important; padding:0 !important; margin:0 !important;
}
div[data-testid="stHorizontalBlock"]:has([class*="st-key-home_nav_stats"]) [class*="st-key-home_nav_stats"],
div[data-testid="stHorizontalBlock"]:has([class*="st-key-home_nav_stats"]) [class*="st-key-home_nav_goals"],
div[data-testid="stHorizontalBlock"]:has([class*="st-key-home_nav_stats"]) [class*="st-key-home_nav_corners"],
div[data-testid="stHorizontalBlock"]:has([class*="st-key-home_nav_stats"]) [class*="st-key-home_nav_h2h"] {
 display:block !important; width:100% !important; max-width:100% !important; min-width:0 !important;
}
div[data-testid="stHorizontalBlock"]:has([class*="st-key-home_nav_stats"]) button {
 box-sizing:border-box !important; display:flex !important; align-items:center !important;
 justify-content:center !important; width:100% !important; max-width:100% !important;
 min-width:0 !important; height:56px !important; min-height:56px !important;
 padding:4px 2px !important; margin:0 !important; overflow:hidden !important;
 border:1px solid rgba(213,169,30,.52) !important; border-radius:9px !important;
 background:linear-gradient(145deg,#1B1D22,#111317) !important; color:#E8E8EA !important;
 font-size:clamp(.58rem,.9vw,.82rem) !important; font-weight:750 !important;
 line-height:1.1 !important; white-space:normal !important; box-shadow:none !important;
}
div[data-testid="stHorizontalBlock"]:has([class*="st-key-home_nav_stats"]) button p {
 margin:0 !important; padding:0 !important; width:100% !important; text-align:center !important;
 white-space:normal !important; overflow-wrap:anywhere !important;
 font-size:inherit !important; line-height:inherit !important;
}
div[data-testid="stHorizontalBlock"]:has([class*="st-key-home_nav_stats"]) button[kind="primary"] {
 border:2px solid #FACC15 !important; background:linear-gradient(145deg,#342B15,#17140D) !important;
 color:#FFD52A !important; box-shadow:0 0 12px rgba(250,204,21,.14) !important;
}
@media(max-width:640px) {
 div[data-testid="stHorizontalBlock"]:has([class*="st-key-home_nav_stats"]) {
  grid-template-columns:repeat(4,minmax(0,1fr)) !important; gap:3px !important;
 }
 div[data-testid="stHorizontalBlock"]:has([class*="st-key-home_nav_stats"]) > div[data-testid="column"] {
  min-width:0 !important; width:auto !important; max-width:none !important;
 }
 div[data-testid="stHorizontalBlock"]:has([class*="st-key-home_nav_stats"]) button {
  height:48px !important; min-height:48px !important; padding:3px 1px !important;
  border-radius:7px !important; font-size:clamp(.48rem,1.8vw,.60rem) !important;
  line-height:1.02 !important; letter-spacing:-.04em !important;
 }
}
</style>
""", unsafe_allow_html=True)