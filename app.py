import csv
import html
import io
import json
import os
from pathlib import Path
from datetime import datetime
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
  /* Tres controles compactos, completos y con acabado dorado uniforme */
  [class*="st-key-top_status_controls"] { margin-top:0 !important; margin-bottom:10px !important; overflow:visible !important; }
  [class*="st-key-top_status_controls"] [data-testid="stHorizontalBlock"] { align-items:stretch !important; gap:.45rem !important; flex-wrap:nowrap !important; overflow:visible !important; }
  [class*="st-key-top_status_controls"] [data-testid="stColumn"] { min-width:0 !important; padding:0 !important; overflow:visible !important; }
  [class*="st-key-auto_refresh_control_card"], [class*="st-key-sound_control_card"] { box-sizing:border-box !important; width:100% !important; min-height:48px !important; display:flex !important; align-items:center !important; justify-content:center !important; padding:4px 5px !important; border:1px solid #D4A72C !important; border-radius:11px !important; background:linear-gradient(145deg,#201D14,#111419) !important; overflow:visible !important; }
  [class*="st-key-auto_refresh_control_card"] [data-testid="stToggle"], [class*="st-key-sound_control_card"] [data-testid="stToggle"] { box-sizing:border-box !important; display:flex !important; align-items:center !important; justify-content:center !important; width:100% !important; min-height:38px !important; padding:2px 0 !important; border:0 !important; border-radius:0 !important; background:transparent !important; overflow:visible !important; }
  [class*="st-key-auto_refresh_control_card"] [data-testid="stToggle"] > label, [class*="st-key-sound_control_card"] [data-testid="stToggle"] > label { display:flex !important; align-items:center !important; justify-content:center !important; gap:5px !important; width:100% !important; margin:0 !important; white-space:nowrap !important; overflow:visible !important; }
  [class*="st-key-auto_refresh_control_card"] [data-testid="stToggle"] label p, [class*="st-key-sound_control_card"] [data-testid="stToggle"] label p { color:#F4D778 !important; font-size:.76rem !important; line-height:1.1 !important; white-space:nowrap !important; margin:0 !important; }
  [class*="st-key-auto_refresh_control_card"] [data-testid="stTooltipIcon"], [class*="st-key-auto_refresh_control_card"] [data-testid="stTooltipHoverTarget"], [class*="st-key-sound_control_card"] [data-testid="stTooltipIcon"], [class*="st-key-sound_control_card"] [data-testid="stTooltipHoverTarget"] { display:none !important; }
  [class*="st-key-auto_refresh_control_card"] [role="switch"], [class*="st-key-sound_control_card"] [role="switch"] { flex:0 0 auto !important; transform:scale(.74) !important; transform-origin:center !important; }
  [class*="st-key-top_status_controls"] iframe { display:block !important; box-sizing:border-box !important; width:100% !important; height:56px !important; min-height:56px !important; margin:0 !important; padding:0 !important; border:0 !important; overflow:visible !important; }
  @media(max-width:640px) {
    [class*="st-key-top_status_controls"] [data-testid="stHorizontalBlock"] { gap:.35rem !important; }
    [class*="st-key-auto_refresh_control_card"], [class*="st-key-sound_control_card"] { min-height:48px !important; padding:4px 2px !important; }
    [class*="st-key-auto_refresh_control_card"] [data-testid="stToggle"] label p, [class*="st-key-sound_control_card"] [data-testid="stToggle"] label p { font-size:.69rem !important; letter-spacing:-.25px !important; }
    [class*="st-key-top_status_controls"] [role="switch"] { transform:scale(.68) !important; }
  }
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
  [class*="st-key-scan-progress"] [data-testid="stProgress"] { margin:2px 0 0 !important; height:7px !important; }
  [class*="st-key-scan-progress"] [data-testid="stProgress"] > div { height:7px !important; border-radius:8px !important; background:#25231B !important; }
  [class*="st-key-scan-progress"] [data-testid="stProgress"] > div > div { background:repeating-linear-gradient(90deg,#FACC15 0 5px,#8A6A0A 5px 7px) !important; border-radius:8px !important; }
  [class*="st-key-scan-progress"] [data-testid="stCaptionContainer"] p { font-size:10px !important; line-height:1.1 !important; color:#A1A1AA !important; margin:2px 0 0 !important; }
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
    /* Tarjeta compacta de acción principal del escáner */
  [class*="st-key-scan_cta_card"] { margin-top:10px !important; margin-bottom:0 !important; }
  [class*="st-key-analysis_scan_cta"] { margin:.35rem 0 .65rem !important; }
  [class*="st-key-analysis_scan_cta"] [data-testid="stButton"] > button {
     width:100% !important; min-height:2.55rem !important; padding:.45rem .55rem !important;
     border-radius:12px !important; border:1px solid #FACC15 !important;
     background:linear-gradient(135deg,#FFE36A,#FACC15) !important; color:#171717 !important;
     font-size:.82rem !important; font-weight:750 !important; box-shadow:0 3px 12px #FACC1533 !important;
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
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] button:hover, [class*="st-key-scan_cta_card"] button[kind="primary"]:hover { border-color:#FFE36A !important; background-color:#090A0D !important; background-image:radial-gradient(ellipse at 20% 50%,rgba(250,204,21,.13),transparent 42%),linear-gradient(135deg,#14151A,#1A180F) !important; color:#FFE36A !important; }
  [class*="st-key-scan_cta_card"] [data-testid="stButton"] button:active { transform:scale(.99); }
  .scan-running-status { position:relative; display:flex; align-items:center; gap:12px; overflow:hidden; color:#FACC15; margin:8px 2px 0; padding:12px 14px; border:1px solid rgba(250,204,21,.35); border-radius:14px; background:linear-gradient(110deg,#17191F,#0B0D10); font-size:.92rem; font-weight:700; }
  .scan-code-icon { display:inline-block; flex:0 0 auto; font-size:2rem; transform-origin:center; animation:scanner-spiral-spin .8s linear infinite; text-shadow:0 0 12px rgba(250,204,21,.8); }
  .scan-running-subtitle { color:#A1A1AA; font-size:.82rem; font-weight:500; margin-top:3px; }
  .scan-sweep { position:absolute; left:0; right:0; bottom:0; height:2px; background:linear-gradient(90deg,transparent,#FACC15,transparent); animation:scanner-sweep 1.4s ease-in-out infinite; }
  /* Bienvenida cinematográfica: remate, gol, marca dorada y salida elegante */
  .football-splash { position:fixed; inset:0; z-index:999999; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:0; overflow:hidden; background:radial-gradient(ellipse at 50% 42%,#18251b 0%,#080b09 72%); color:#fff; pointer-events:none; transform-origin:center; animation:splash-dismiss 5.8s cubic-bezier(.65,0,.35,1) forwards; }
  .splash-pitch { position:relative; width:min(82vw,520px); height:min(48vh,300px); border:2px solid rgba(255,255,255,.8); border-radius:4px; background:repeating-linear-gradient(90deg,rgba(255,255,255,.035) 0 10%,transparent 10% 20%),linear-gradient(180deg,#176b35,#0b4825); box-shadow:0 0 42px rgba(34,197,94,.18); }
  .splash-pitch:before { content:""; position:absolute; inset:0 25%; border-left:2px solid rgba(255,255,255,.75); border-right:2px solid rgba(255,255,255,.75); }
  .splash-pitch:after { content:""; position:absolute; width:28%; aspect-ratio:1; left:36%; top:36%; border:2px solid rgba(255,255,255,.75); border-radius:50%; }
  .splash-goal { position:absolute; right:-2px; top:31%; width:14%; height:38%; border:4px solid #f8fafc; border-right:0; background:repeating-linear-gradient(0deg,transparent 0 13px,rgba(255,255,255,.45) 14px 15px),repeating-linear-gradient(90deg,transparent 0 13px,rgba(255,255,255,.45) 14px 15px); box-shadow:0 0 0 rgba(250,204,21,0); animation:splash-goal-hit .55s ease 1.85s both; }
  .splash-ball { position:absolute; left:9%; top:66%; z-index:2; font-size:clamp(2.2rem,7vw,3.8rem); filter:drop-shadow(0 8px 4px #0008); animation:splash-shot 2.15s cubic-bezier(.2,.72,.25,1) .25s forwards; }
  .splash-brand { margin-top:28px; font-size:clamp(1.8rem,6vw,3.5rem); font-weight:950; letter-spacing:.16em; text-align:center; opacity:0; transform:translateY(18px) scale(.86); background:linear-gradient(105deg,#8a5a10 0%,#f9df82 18%,#fff3b0 32%,#c58a19 48%,#fff0a0 62%,#a66c0c 80%,#ffe7a0 100%); background-size:220% auto; -webkit-background-clip:text; background-clip:text; color:transparent; -webkit-text-fill-color:transparent; text-shadow:0 0 28px rgba(250,204,21,.18); filter:drop-shadow(0 4px 18px rgba(250,204,21,.25)); animation:splash-brand-in .95s cubic-bezier(.16,1,.3,1) 2.05s both, splash-gold-shine 2.2s linear 2.8s infinite; }
  .splash-tagline { margin-top:9px; color:#e5dfcb; font-size:.76rem; letter-spacing:.24em; opacity:0; transform:translateY(8px); animation:splash-tag-in .65s ease 2.45s both; }
  @keyframes splash-shot { 0%{left:9%;top:66%;transform:rotate(0) scale(1);opacity:1} 38%{left:48%;top:28%;transform:rotate(330deg) scale(.82);opacity:1} 62%{left:77%;top:40%;transform:rotate(600deg) scale(.62);opacity:1} 76%{left:88%;top:44%;transform:rotate(780deg) scale(.48);opacity:1} 86%{left:94%;top:45%;transform:rotate(900deg) scale(.3);opacity:.95} 100%{left:96%;top:45%;transform:rotate(980deg) scale(.18);opacity:0} }
  @keyframes splash-goal-hit { 0%,65%{box-shadow:0 0 0 rgba(250,204,21,0)} 72%{box-shadow:0 0 34px rgba(250,204,21,.95),0 0 70px rgba(250,204,21,.45)} 100%{box-shadow:0 0 12px rgba(250,204,21,.28)} }
  @keyframes splash-brand-in { 0%{opacity:0;transform:translateY(18px) scale(.86);filter:blur(8px) drop-shadow(0 4px 18px rgba(250,204,21,.25))} 70%{opacity:1;transform:translateY(-2px) scale(1.035);filter:blur(0) drop-shadow(0 4px 24px rgba(250,204,21,.48))} 100%{opacity:1;transform:translateY(0) scale(1);filter:blur(0) drop-shadow(0 4px 18px rgba(250,204,21,.25))} }
  @keyframes splash-tag-in { to{opacity:1;transform:translateY(0)} }
  @keyframes splash-gold-shine { to{background-position:-220% center} }
  @keyframes splash-dismiss { 0%,79%{opacity:1;visibility:visible;transform:scale(1);filter:blur(0)} 88%{opacity:1;visibility:visible;transform:scale(1.015);filter:blur(0)} 100%{opacity:0;visibility:hidden;transform:scale(1.07);filter:blur(12px)} }
  @media(prefers-reduced-motion:reduce) { .football-splash,.splash-ball,.splash-goal,.splash-brand,.splash-tagline { animation-duration:.01ms !important; animation-delay:0s !important; } }

  @keyframes scanner-radar-spin { to { rotate:360deg; } }
  @keyframes scanner-ball-orbit { 0%,100% { transform:translate(-50%,-50%) scale(.9); } 50% { transform:translate(-50%,-50%) scale(1.1); } }
  @keyframes scanner-spiral-spin { to { transform:rotate(360deg); } }
  @keyframes scanner-sweep { 0% { transform:translateX(-100%); } 100% { transform:translateX(100%); } }
  @media(max-width:640px) { [class*="st-key-scan_cta_card"] [data-testid="stButton"] button { min-height:145px; padding:16px 12px 16px 49%; font-size:.95rem; } [class*="st-key-scan_cta_card"] [data-testid="stButton"] button::before { left:3%; width:40%; } [class*="st-key-scan_cta_card"] [data-testid="stButton"] button::after { left:23%; } }
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
  /* Filas de ligas y partidos alineadas al borde izquierdo, sin huecos de los contenedores Streamlit */
  [class*="st-key-live_now_section"] [data-testid="stExpander"] details[open] > div,
  [class*="st-key-live_now_section"] [data-testid="stExpander"] details[open] > div > [data-testid="stVerticalBlock"] { padding:0 !important; margin:0 !important; gap:0 !important; row-gap:0 !important; }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stVerticalBlock"] { gap:0 !important; row-gap:0 !important; }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stElementContainer"] { margin:0 !important; padding:0 !important; }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] { width:100% !important; max-width:100% !important; margin:0 !important; padding:0 !important; }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] summary { min-height:38px !important; padding:4px 12px !important; border:1px solid #34363D !important; border-radius:5px !important; background:#0B0D10 !important; }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] details { margin:0 !important; padding:0 !important; }
  [class*="st-key-live_now_section"] [data-testid="stExpander"] [data-testid="stExpander"] + [data-testid="stExpander"] { margin-top:-7px !important; }
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
  @media(max-width:620px) { .match-action-grid {grid-template-columns:repeat(2,minmax(0,1fr));} .h2h-match-row {grid-template-columns:65px minmax(0,1fr) 48px minmax(0,1fr);font-size:.7rem;gap:4px;} .corner-h2h-row {grid-template-columns:56px minmax(0,1fr) 42px minmax(0,1fr) 58px;font-size:.64rem;gap:3px;padding:8px 2px;} .h2h-team img {width:18px;height:18px;flex-basis:18px;} }

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
  .goal-deep-heading { color:#FACC15; font-size:.78rem; letter-spacing:1.1px; font-weight:900; margin:.85rem 0 .45rem; }
  .goal-form-card { border:1px solid #393326; border-radius:11px; padding:10px; background:linear-gradient(145deg,#191D24,#101216); min-height:132px; }
  .goal-form-team { color:#E4E4E7; font-size:.78rem; font-weight:800; line-height:1.25; overflow-wrap:anywhere; }
  .goal-form-record { color:#FACC15; font-size:1.15rem; font-weight:900; margin:4px 0; }
  .goal-form-line { color:#BFC2CA; font-size:.68rem; line-height:1.45; }
  .goal-h2h-summary { margin:.5rem 0; border:1px solid #393326; border-radius:10px; padding:9px 11px; color:#D4D4D8; background:#15191F; font-size:.78rem; line-height:1.5; }
  .goal-h2h-summary b { color:#FACC15; }
  .goal-comeback-card { display:flex; flex-direction:column; gap:5px; border:1px solid #393326; border-radius:10px; padding:9px; background:#12151A; margin:.2rem 0 .45rem; }
  .goal-comeback-card b { color:#FACC15; font-size:.75rem; }
  .goal-comeback-card span { color:#E4E4E7; font-size:.72rem; line-height:1.4; }
  .goal-comeback-card small { color:#9CA3AF; font-size:.62rem; line-height:1.35; }
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
</style>
""", unsafe_allow_html=True)

show_splash_intro = not st.session_state.get("football_splash_shown", False)
if show_splash_intro:
    st.markdown("""
    <div class="football-splash" aria-label="Bienvenido a Football Lab">
      <div class="splash-pitch">
        <div class="splash-goal"></div>
        <div class="splash-ball">⚽</div>
      </div>
      <div class="splash-brand">FOOTBALL LAB</div>
      <div class="splash-tagline">DETECTA · COMPARA · ANALIZA</div>
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
  applyLocalTime();
  setTimeout(applyLocalTime, 250);
})();
</script>
""", height=0, width=0, scrolling=False)
# Cabecera limpia; los detalles del modelo aparecen en Rendimiento del modelo.

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
                    '<div style="height:46px;display:flex;align-items:center;justify-content:flex-start;color:#F4D778;-webkit-text-fill-color:#F4D778;font-family:system-ui,-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;font-size:11px;font-weight:600;line-height:1.1;letter-spacing:0;white-space:nowrap">⟳ Auto 60s</div>',
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
                    '<div style="height:46px;display:flex;align-items:center;justify-content:flex-start;color:#F4D778;-webkit-text-fill-color:#F4D778;font-family:system-ui,-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;font-size:11px;font-weight:600;line-height:1.1;letter-spacing:0;white-space:nowrap">♫ Sonido</div>',
                    unsafe_allow_html=True,
                )
    with status_cols[2]:
        st.components.v1.html("""
<style>html,body{margin:0!important;padding:0!important;width:100%!important;background:transparent!important;overflow:hidden!important;}</style>
<div style="box-sizing:border-box;display:flex;align-items:center;justify-content:center;width:100%;height:48px;min-height:48px;margin:0;padding:0">
  <button id="scanner-test-sound" type="button" title="Activar y probar las alertas sonoras" style="box-sizing:border-box;display:block;width:100%;height:48px;min-height:48px;margin:0;padding:6px 3px;border-radius:11px;border:1px solid #D4A72C;background:linear-gradient(145deg,#201D14,#111419);color:#F4D778;font:600 11px system-ui;white-space:nowrap;cursor:pointer">🔔 Alertas</button>
</div>
<script>
(() => {
 const b=document.getElementById('scanner-test-sound');
 if(!b || b.dataset.bound) return;
 b.dataset.bound='1';
 b.addEventListener('click', () => {
   try {
     localStorage.setItem('football-lab-audio-activated', 'true');
     if ('speechSynthesis' in window && 'SpeechSynthesisUtterance' in window) {
       window.speechSynthesis.cancel();
       const u = new SpeechSynthesisUtterance('¡Gol!');
       u.lang = 'es-CO'; u.rate = 0.95;
       window.speechSynthesis.speak(u);
     }
     const C=window.AudioContext||window.webkitAudioContext;
     if(!C) { b.textContent='✓ Alertas'; return; }
     const c=new C(), o=c.createOscillator(), g=c.createGain();
     o.type='sine'; o.frequency.value=880; g.gain.value=0.08;
     o.connect(g); g.connect(c.destination);
     Promise.resolve(c.resume()).then(()=>{o.start();setTimeout(()=>{try{o.stop();}catch(e){} c.close();},220);});
     b.textContent='✓ Alertas';
   } catch(e) { b.textContent='⚠ Sin audio'; }
 });
})();
</script>
""", height=56, scrolling=False)

with st.container(key="control_row"):
    refresh = st.button(
        "Actualizar scan",
        type="primary",
        help="Actualiza el listado de partidos y ejecuta el escaneo disponible."
    )
with st.container(key="scan-progress"):
    scan_progress = st.empty()
    scan_progress_caption = st.empty()
    if refresh:
        scan_progress.progress(0)
        scan_progress_caption.caption("Actualizando scan")

with st.container(key="scan_cta_card"):
    manual_scan = st.button(
        "FOOTBALL LAB\nESCÁNER EN VIVO\nPulsa para escanear oportunidades en directo",
        type="primary",
        key="scan_all_live",
    )
    if manual_scan:
        st.markdown('<div class="scan-running-status"><span class="scan-code-icon">⟳</span><div><strong>ESCANEANDO…</strong><div class="scan-running-subtitle">Analizando partidos y mercados</div></div><span class="scan-sweep"></span></div>', unsafe_allow_html=True)

internal_scan_requested = False
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
        if refresh:
            scan_progress.progress(12)
            scan_progress_caption.caption("Actualizando scan")
        data = api_get("fixtures", {"live": "all"})
        new_fixtures = data.get("response", [])
        if refresh:
            scan_progress.progress(28)
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

        # Consultar cuotas en bloque, de forma independiente al escaneo estadístico.
        # Una sola llamada cubre todos los fixtures disponibles; intervalo de 120 s
        # para vigilar cambios sin generar una llamada por partido.
        if refresh:
            scan_progress.progress(40)
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

        # Rotate through at most 5 fixtures per minute for corner stats. This keeps
        # the Pro daily quota safe; it deliberately does not query every match every minute.
        live_for_corners = [
            match for match in new_fixtures
            if (match.get("fixture") or {}).get("id") is not None
            and (((match.get("fixture") or {}).get("status") or {}).get("short") not in {"HT", "FT", "AET", "PEN", "NS"})
        ]
        corner_events = []
        if live_for_corners:
            batch_size = min(5, len(live_for_corners))
            offset = st.session_state.corner_rotation_index % len(live_for_corners)
            rotated = live_for_corners[offset:] + live_for_corners[:offset]
            for corner_idx, match in enumerate(rotated[:batch_size]):
                if refresh:
                    scan_progress.progress(45 + int(45 * (corner_idx / max(1, batch_size))))
                fixture_data = match.get("fixture") or {}
                fixture_id = str(fixture_data.get("id"))
                try:
                    stat_payload = api_get("fixtures/statistics", {"fixture": fixture_id})
                    stat_rows = stat_payload.get("response") or []
                    # Reuse live stats in the selected-match panel and corners tab.
                    st.session_state.stats_cache[fixture_id] = stat_rows
                    home_c = safe_stat(stat_rows, "Corner Kicks", 0)
                    away_c = safe_stat(stat_rows, "Corner Kicks", 1)
                    if home_c is None or away_c is None:
                        continue
                    now_total = home_c + away_c
                    previous_total = st.session_state.corner_snapshot.get(fixture_id)
                    st.session_state.corner_snapshot[fixture_id] = now_total
                    if previous_total is not None and now_total > previous_total:
                        teams = match.get("teams") or {}
                        corner_events.append({
                            "id": f"corner:{fixture_id}:{now_total}",
                            "title": "🚩 ¡NUEVO CÓRNER!",
                            "message": f"{(teams.get('home') or {}).get('name', 'Local')} vs {(teams.get('away') or {}).get('name', 'Visitante')} · total {now_total}"
                        })
                except Exception as stats_exc:
                    if "HTTP 429" in str(stats_exc):
                        st.session_state.last_auto_refresh_error = "Se alcanzó el límite de la API; se pausaron las consultas de córners en este ciclo."
                        break
            st.session_state.corner_rotation_index = (offset + batch_size) % max(1, len(live_for_corners))

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
            scan_progress.progress(100)
            scan_progress_caption.caption("Actualización completada")
    except Exception as exc:
        st.session_state.last_auto_refresh_error = str(exc)
        if refresh:
            scan_progress_caption.caption("No se pudo completar la actualización")

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
          const goalEvents = fresh.filter(e => String(e.title || '').toLowerCase().includes('gol'));
          if (goalEvents.length && 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window) {{
            window.speechSynthesis.cancel();
            const utterance = new SpeechSynthesisUtterance('¡Gol!');
            utterance.lang = 'es-CO';
            utterance.rate = 0.95;
            window.speechSynthesis.speak(utterance);
          }}
          const AudioCtx = window.AudioContext || window.webkitAudioContext;
          if (AudioCtx) {{
            const ctx = new AudioCtx();
            const playChime = () => {{
              [880, 1175].forEach((freq, i) => {{
                const osc = ctx.createOscillator(), gain = ctx.createGain(), t = ctx.currentTime + i * 0.14;
                osc.type = 'sine'; osc.frequency.value = freq;
                gain.gain.setValueAtTime(0.0001, t);
                gain.gain.exponentialRampToValueAtTime(0.12, t + 0.025);
                gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.18);
                osc.connect(gain); gain.connect(ctx.destination); osc.start(t); osc.stop(t + 0.2);
              }});
              setTimeout(() => ctx.close(), 700);
            }};
            Promise.resolve(ctx.resume()).then(playChime).catch(() => {{ try {{ ctx.close(); }} catch (e) {{}} }});
          }}
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
        /* Pantalla dedicada: dejar únicamente el botón de regreso y el contenido del análisis elegido. */
        [class*="st-key-control_row"], [class*="st-key-scan_cta_card"],
        [class*="st-key-scan-progress"], .brand-header, .match-analysis-panel {{ display:none !important; }}
        /* Ocultar cabecera general, cabeceras de ligas y la cabecera del partido seleccionado. */
        [class*="st-key-live_now_expander"] summary,
        [class*="st-key-live_league_"] summary,
        [class*="st-key-live_match_{_analysis_page_id}"] summary {{ display:none !important; }}
        [class*="st-key-live_league_"]:not(:has([class*="st-key-live_match_{_analysis_page_id}"])) {{ display:none !important; }}
        [class*="st-key-live_league_"] [class*="st-key-live_match_"]:not([class*="st-key-live_match_{_analysis_page_id}"]) {{ display:none !important; }}
        /* La lista de ligas y su contenedor no deben añadir marco, relleno ni huecos a la vista de análisis. */
        [class*="st-key-live_now_section"] {{ margin:0 !important; padding:0 !important; }}
        [class*="st-key-live_now_expander"] {{ border:0 !important; margin:0 !important; padding:0 !important; }}
        [class*="st-key-live_league_"]:has([class*="st-key-live_match_{_analysis_page_id}"]) {{ border:0 !important; margin:0 !important; padding:0 !important; }}
        [class*="st-key-live_match_{_analysis_page_id}"] {{ display:block !important; width:100% !important; max-width:100% !important; margin:0 !important; padding:0 !important; border:0 !important; }}
        [class*="st-key-live_match_{_analysis_page_id}"] [data-testid="stExpander"] {{ border:0 !important; margin:0 !important; padding:0 !important; }}
        [class*="st-key-live_match_{_analysis_page_id}"] [data-testid="stExpander"] > details > div {{ padding:0 !important; margin:0 !important; }}
        /* Ocultar los cuatro botones de navegación del partido: queda solo el panel correspondiente al botón pulsado. */
        [class*="st-key-main_stats_{_analysis_page_id}"],
        [class*="st-key-main_market_{_analysis_page_id}_goals"],
        [class*="st-key-main_market_{_analysis_page_id}_corners"],
        [class*="st-key-main_h2h_{_analysis_page_id}"] {{ display:none !important; }}
        /* El contenido del análisis debe ocupar todo el ancho y no heredar espaciados del listado. */
        [class*="st-key-live_match_{_analysis_page_id}"] [data-testid="stVerticalBlock"] {{ gap:.35rem !important; row-gap:.35rem !important; }}
        [class*="st-key-analysis_page_nav"] {{ margin-bottom:.5rem !important; display:flex !important; justify-content:flex-start !important; }}
        [class*="st-key-analysis_page_nav"] [data-testid="stButton"] {{ width:auto !important; max-width:230px !important; }}
        [class*="st-key-analysis_page_nav"] [data-testid="stButton"] > button {{
            width:auto !important; min-height:2.35rem !important; padding:.35rem .85rem !important;
            border-radius:12px !important; border:1px solid #5B512A !important;
            background:linear-gradient(135deg,#20242B,#111419) !important;
            color:#FACC15 !important; font-size:.9rem !important; font-weight:650 !important;
            box-shadow:0 3px 10px #0004 !important;
        }}
        [class*="st-key-analysis_page_nav"] [data-testid="stButton"] > button:hover {{
            border-color:#FACC15 !important; background:#2A2618 !important; color:#FFE566 !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="analysis_page_nav"):
        if st.button("← Volver al partido", key="analysis_page_back", use_container_width=True):
            # Mantener abierta la liga y el encuentro que originaron esta vista.
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
            st.session_state["main_fixture_tool"] = {}
            st.session_state["return_to_fixture_id"] = _analysis_page_id
            st.rerun()
    st.markdown(
        '<div class="match-analysis-panel"><div class="match-analysis-kicker">FOOTBALL LAB · ANÁLISIS INDIVIDUAL</div><div class="match-analysis-title">Vista ampliada del partido</div><div class="signal-meta">Consulta el análisis seleccionado y vuelve a los partidos cuando termines.</div></div>',
        unsafe_allow_html=True,
    )

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
    # Mostrar todos los partidos en vivo; se oculta el filtro de ligas para simplificar la pantalla.
    filtered = list(fixtures)
    with st.container(key="live_now_section"):
        with st.expander(f"En vivo ahora ({len(filtered)})", expanded=st.session_state.get("live_now_expander", False), key="live_now_expander", on_change="rerun"):
            if filtered:
                grouped = {}
                for match in filtered:
                    league_data = match.get("league") or {}
                    country = league_data.get("country") or "Otros países"
                    league_name = league_data.get("name") or "Liga sin nombre"
                    grouped.setdefault((country, league_name), []).append(match)
                for (country, league_name), league_matches in sorted(grouped.items()):
                    with st.expander(f"{country} · {league_name} ({len(league_matches)})", expanded=st.session_state.get(f"live_league_{country}_{league_name}", False), key=f"live_league_{country}_{league_name}", on_change="rerun"):
                        # Cada partido tiene una sola tarjeta principal; evitamos duplicar el marcador
                        # en una cuadrícula y otra vez dentro del expander de análisis.
                        # Match tools are available from the main live scanner, before a full market scan.
                        for match in league_matches:
                            match_fixture = match.get("fixture") or {}
                            match_id = match_fixture.get("id")
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
                            home_md = f"![{match_home_name}]({match_home_logo}) " if match_home_logo else "⚽ "
                            away_md = f" ![{match_away_name}]({match_away_logo})" if match_away_logo else ""
                            match_row_label = f"{home_md}**{match_home_name}**  **{score_label}**  **{match_away_name}**{away_md} · {match_minute if match_minute is not None else 'EN VIVO'}′"
                            if not match_id:
                                continue
                            with st.expander(match_row_label, expanded=st.session_state.get(f"live_match_{match_id}", False), key=f"live_match_{match_id}", on_change="rerun"):
                                current_tool = st.session_state.get("main_fixture_tool") or {}
                                active_market = current_tool.get("market") if str(current_tool.get("fixture_id")) == str(match_id) else None
                                active_tool = current_tool.get("tool") if str(current_tool.get("fixture_id")) == str(match_id) else None
                                # Acciones en el mismo orden visual del diseño aprobado:
                                # Estadísticas, Goles, Córners y H2H.
                                action_cols = st.columns(4, gap="small")
                                with action_cols[0]:
                                    show_stats = st.button("▥", help="Estadísticas en vivo", key=f"main_stats_{match_id}", type="primary" if active_tool == "stats" else "secondary", use_container_width=True)
                                with action_cols[1]:
                                    show_goals = st.button("⚽︎⚡", help="Goles y señales", key=f"main_market_{match_id}_goals", type="primary" if active_market == "goals" else "secondary", use_container_width=True)
                                with action_cols[2]:
                                    show_corners = st.button("⚑", help="Córners", key=f"main_market_{match_id}_corners", type="primary" if active_market == "corners" else "secondary", use_container_width=True)
                                with action_cols[3]:
                                    show_h2h = st.button("H2H", help="Historial H2H", key=f"main_h2h_{match_id}", type="primary" if active_tool == "h2h" else "secondary", use_container_width=True)
                                if show_stats:
                                    stats_key = str(match_id)
                                    if stats_key not in st.session_state.stats_cache or stats_key in st.session_state.get("stats_errors", {}):
                                        try:
                                            stats_payload = api_get("fixtures/statistics", {"fixture": match_id})
                                            st.session_state.stats_cache[stats_key] = stats_payload.get("response") or []
                                            st.session_state.setdefault("stats_errors", {}).pop(stats_key, None)
                                        except Exception as stats_exc:
                                            st.session_state.stats_cache[stats_key] = []
                                            st.session_state.setdefault("stats_errors", {})[stats_key] = str(stats_exc)
                                    st.session_state["main_fixture_tool"] = {"fixture_id": match_id, "tool": "stats"}
                                    st.rerun()
                                if show_h2h:
                                    if "h2h_cache" not in st.session_state:
                                        st.session_state.h2h_cache = {}
                                    _match_league = match.get("league") or {}
                                    league_id = _match_league.get("id")
                                    # v3: el historial respeta la localía del equipo que juega como local en el partido actual.
                                    h2h_key = f"h2h-v3-home-{match_home_id}-{match_away_id}-{league_id or 'all'}"
                                    if not match_home_id or not match_away_id:
                                        st.warning("La API no entregó los identificadores de ambos equipos.")
                                    elif h2h_key not in st.session_state.h2h_cache:
                                        try:
                                            # Consultar suficientes enfrentamientos históricos y filtrar por localía antes de limitar a 10.
                                            h2h_payload = api_get("fixtures/headtohead", {"h2h": f"{match_home_id}-{match_away_id}", "last": 50})
                                            all_h2h_matches = h2h_payload.get("response") or []
                                            finished_h2h = [
                                                past for past in all_h2h_matches
                                                if ((past.get("fixture") or {}).get("status") or {}).get("short") in {"FT", "AET", "PEN"}
                                            ]
                                            # Solo enfrentamientos en los que el equipo local del partido actual también fue local.
                                            same_home_h2h = [
                                                past for past in finished_h2h
                                                if str((((past.get("teams") or {}).get("home") or {}).get("id"))) == str(match_home_id)
                                            ]
                                            # Preferir la misma competición; si hay menos de 10, completar con otras competiciones
                                            # manteniendo siempre la condición de que el equipo actual sea local.
                                            same_home_h2h.sort(
                                                key=lambda past: ((past.get("fixture") or {}).get("date") or ""),
                                                reverse=True,
                                            )
                                            same_league_home_h2h = [
                                                past for past in same_home_h2h
                                                if (past.get("league") or {}).get("id") == league_id
                                            ] if league_id else same_home_h2h
                                            selected_h2h = same_league_home_h2h[:10]
                                            if len(selected_h2h) < 10:
                                                selected_ids = {
                                                    (past.get("fixture") or {}).get("id")
                                                    for past in selected_h2h
                                                }
                                                extras = [
                                                    past for past in same_home_h2h
                                                    if (past.get("fixture") or {}).get("id") not in selected_ids
                                                ]
                                                selected_h2h.extend(extras[:10 - len(selected_h2h)])
                                            st.session_state.h2h_cache[h2h_key] = {
                                                "matches": selected_h2h[:10],
                                                "scope": "league" if selected_h2h and all(
                                                    (past.get("league") or {}).get("id") == league_id
                                                    for past in selected_h2h
                                                ) else "home_all",
                                            }
                                        except Exception as h2h_exc:
                                            st.session_state.h2h_cache[h2h_key] = {"error": str(h2h_exc)}
                                    st.session_state["main_fixture_tool"] = {"fixture_id": match_id, "tool": "h2h"}
                                    st.rerun()
                                if show_goals:
                                    st.session_state["main_fixture_tool"] = {"fixture_id": match_id, "tool": "market", "market": "goals"}
                                    st.rerun()
                                if show_corners:
                                    st.session_state["main_fixture_tool"] = {"fixture_id": match_id, "tool": "market", "market": "corners"}
                                    st.rerun()
                                selected_tool = st.session_state.get("main_fixture_tool") or {}
                                if str(selected_tool.get("fixture_id")) == str(match_id):
                                    tool_name = selected_tool.get("tool")
                                    if tool_name != "stats" and not _analysis_page_active:
                                        st.markdown('<div class="match-analysis-kicker">PARTIDO SELECCIONADO</div>', unsafe_allow_html=True)
                                    if tool_name == "stats":
                                        stat_data = st.session_state.stats_cache.get(str(match_id), [])
                                        stats_error = st.session_state.get("stats_errors", {}).get(str(match_id))
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
                                            st.info("La API no entregó estadísticas para este partido.")
                                    elif tool_name == "h2h":
                                        _match_league = match.get("league") or {}
                                        h2h_key = f"h2h-v3-home-{match_home_id}-{match_away_id}-{_match_league.get('id') or 'all'}"
                                        h2h_data = st.session_state.get("h2h_cache", {}).get(h2h_key)
                                        st.markdown('<div class="match-analysis-kicker">Historial · enfrentamientos directos</div><div class="match-analysis-title">Enfrentamientos directos</div>', unsafe_allow_html=True)
                                        if isinstance(h2h_data, dict) and h2h_data.get("error"):
                                            st.warning(f"No se pudieron consultar los enfrentamientos: {h2h_data['error']}")
                                        elif isinstance(h2h_data, dict) and h2h_data.get("matches"):
                                            h2h_matches = h2h_data["matches"]
                                            if h2h_data.get("scope") == "league":
                                                league_name_safe = html.escape(str(_match_league.get("name") or "la competición actual"))
                                                st.caption(f"Últimos {len(h2h_matches)} enfrentamientos finalizados de {league_name_safe}, con el equipo local actual jugando en casa.")
                                            else:
                                                st.caption(f"Últimos {len(h2h_matches)} enfrentamientos finalizados con el equipo local actual jugando en casa; se prioriza la misma competición y se completa con otras si hace falta.")
                                            h2h_html = ""
                                            for past in h2h_matches:
                                                pf, pt, pg = past.get("fixture") or {}, past.get("teams") or {}, past.get("goals") or {}
                                                ph, pa = pt.get("home") or {}, pt.get("away") or {}
                                                date_label = html.escape((pf.get("date") or "")[:10])
                                                ph_name, pa_name = html.escape(str(ph.get("name") or "Local")), html.escape(str(pa.get("name") or "Visitante"))
                                                ph_logo, pa_logo = html.escape(str(ph.get("logo") or ""), quote=True), html.escape(str(pa.get("logo") or ""), quote=True)
                                                h2h_html += f'<div class="h2h-match-row"><span>{date_label}</span><span class="h2h-team"><img src="{ph_logo}" onerror="this.style.display=\'none\'">{ph_name}</span><span class="h2h-score">{pg.get("home", "—")} – {pg.get("away", "—")}</span><span class="h2h-team"><img src="{pa_logo}" onerror="this.style.display=\'none\'">{pa_name}</span></div>'
                                            st.markdown(h2h_html, unsafe_allow_html=True)
                                        elif isinstance(h2h_data, list) and h2h_data:
                                            # Compatibilidad con entradas de caché creadas antes de h2h-v2.
                                            st.info("Se encontraron datos H2H antiguos en caché. Vuelve a abrir H2H para cargar el historial actualizado.")
                                        elif h2h_data is not None:
                                            st.info("La API no devolvió enfrentamientos directos finalizados para estos equipos en los resultados consultados.")
                                    elif tool_name == "market":
                                        market_key = selected_tool.get("market")
                                        if market_key == "goals":
                                            with st.container(key=f"analysis_scan_cta_goals_{match_id}"):
                                                _goal_scan_cols = st.columns(2, gap="small")
                                                with _goal_scan_cols[0]:
                                                    _goal_radar_clicked = st.button("⚽ Escanear en vivo", key=f"analysis_scan_radar_goals_{match_id}")
                                                with _goal_scan_cols[1]:
                                                    _goal_refresh_clicked = st.button("⟳ Actualizar scan", key=f"analysis_scan_goals_{match_id}")
                                                if _goal_radar_clicked or _goal_refresh_clicked:
                                                    manual_scan = True
                                                    internal_scan_requested = True
                                                    st.markdown('<div class="scan-running-status"><span class="scan-code-icon">⟳</span><div><strong>ESCANEANDO…</strong><div class="scan-running-subtitle">Actualizando señales de goles y datos en vivo</div></div><span class="scan-sweep"></span></div>', unsafe_allow_html=True)
                                            st.markdown('<div class="match-analysis-kicker">Mercado seleccionado · goles</div><div class="match-analysis-title">Goles y señales</div>', unsafe_allow_html=True)
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
                                                home_shots = safe_stat(live_stats, "Total Shots", 0)
                                                away_shots = safe_stat(live_stats, "Total Shots", 1)
                                                home_on = safe_stat(live_stats, "Shots on Goal", 0)
                                                away_on = safe_stat(live_stats, "Shots on Goal", 1)
                                                home_poss = safe_stat(live_stats, "Ball Possession", 0)
                                                away_poss = safe_stat(live_stats, "Ball Possession", 1)
                                                home_corners = safe_stat(live_stats, "Corner Kicks", 0)
                                                away_corners = safe_stat(live_stats, "Corner Kicks", 1)
                                                def pct_value(value):
                                                    if isinstance(value, str):
                                                        try: return float(value.replace("%", "").strip())
                                                        except ValueError: return None
                                                    return float(value) if isinstance(value, (int, float)) else None
                                                home_poss_n, away_poss_n = pct_value(home_poss), pct_value(away_poss)
                                                live_bits = []
                                                if isinstance(home_score, int) and isinstance(away_score, int):
                                                    live_bits.append(f"Marcador {home_score}–{away_score} al minuto {current_minute if current_minute is not None else 'N/D'}")
                                                if isinstance(home_shots, (int, float)) and isinstance(away_shots, (int, float)):
                                                    live_bits.append(f"tiros {home_name} {home_shots}–{away_shots} {away_name}")
                                                if isinstance(home_on, (int, float)) and isinstance(away_on, (int, float)):
                                                    live_bits.append(f"tiros a puerta {home_on}–{away_on}")
                                                if home_poss_n is not None and away_poss_n is not None:
                                                    leader = home_name if home_poss_n > away_poss_n else away_name if away_poss_n > home_poss_n else "ninguno"
                                                    if leader != "ninguno": live_bits.append(f"{leader} controla la posesión ({max(home_poss_n, away_poss_n):.0f}%)")
                                                if isinstance(home_corners, (int, float)) and isinstance(away_corners, (int, float)):
                                                    live_bits.append(f"córners {home_corners}–{away_corners}")
                                                if live_bits:
                                                    summary = "; ".join(live_bits[:3])
                                                    summary += "."
                                                    if isinstance(home_on, (int, float)) and isinstance(away_on, (int, float)):
                                                        if home_on + away_on == 0:
                                                            summary += " Aún no hay tiros a puerta; falta evidencia ofensiva clara para respaldar una entrada agresiva."
                                                        elif abs(home_on - away_on) >= 2:
                                                            summary += f" La amenaza más clara hasta ahora favorece a {home_name if home_on > away_on else away_name}."
                                                        else:
                                                            summary += " La producción a puerta está relativamente equilibrada."
                                                else:
                                                    summary = "La API no entregó estadísticas detalladas suficientes para describir la presión ofensiva sin especular."
                                                st.markdown('<div class="goal-live-summary"><div class="goal-live-summary-title">◉ LECTURA EN VIVO</div><p>' + html.escape(summary) + '</p></div>', unsafe_allow_html=True)
                                                goal_history_rows = [
                                                    (f"{home_name} · goles a favor en casa", history.get("home_goals_for"), history.get("home_goal_sample", 0)),
                                                    (f"{home_name} · goles recibidos en casa", history.get("home_goals_against"), history.get("home_goal_sample", 0)),
                                                    (f"{away_name} · goles a favor fuera", history.get("away_goals_for"), history.get("away_goal_sample", 0)),
                                                    (f"{away_name} · goles recibidos fuera", history.get("away_goals_against"), history.get("away_goal_sample", 0)),
                                                ]
                                                goal_table_html = '<div class="goal-history-wrap"><div class="goal-history-heading">▥ Promedios de goles por localía <span>Histórico</span></div><table class="goal-history-table"><thead><tr><th>Equipo / indicador</th><th>Prom.</th><th>N</th></tr></thead><tbody>'
                                                for label, avg, sample in goal_history_rows:
                                                    avg_text = f"{avg:.2f}".rstrip("0").rstrip(".") if isinstance(avg, (int, float)) else "N/D"
                                                    goal_table_html += f'<tr><td>{html.escape(str(label))}</td><td>{avg_text}</td><td>{sample if sample else "—"}</td></tr>'
                                                goal_table_html += '</tbody></table></div>'
                                                st.markdown(goal_table_html, unsafe_allow_html=True)
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
                                                if deep_context.get("available"):
                                                    st.markdown('<div class="goal-deep-heading">⌁ CONTEXTO HISTÓRICO Y REACCIÓN AL GOL</div>', unsafe_allow_html=True)
                                                    form_cols = st.columns(2, gap="small")
                                                    for col, label, form_data in (
                                                        (form_cols[0], home_name, deep_context.get("home_form") or {}),
                                                        (form_cols[1], away_name, deep_context.get("away_form") or {}),
                                                    ):
                                                        col.markdown(
                                                            f'<div class="goal-form-card"><div class="goal-form-team">{html.escape(label)}</div>'
                                                            f'<div class="goal-form-record">{html.escape(str(form_data.get("record", "N/D")))}</div>'
                                                            f'<div class="goal-form-line">GF {form_data.get("goals_for_avg") if form_data.get("goals_for_avg") is not None else "N/D"} · GC {form_data.get("goals_against_avg") if form_data.get("goals_against_avg") is not None else "N/D"}</div>'
                                                            f'<div class="goal-form-line">Ambos marcan {form_data.get("btts_rate") if form_data.get("btts_rate") is not None else "N/D"}% · +2.5 goles {form_data.get("over_2_5_rate") if form_data.get("over_2_5_rate") is not None else "N/D"}%</div></div>',
                                                            unsafe_allow_html=True,
                                                        )
                                                    h2h_data = deep_context.get("h2h") or {}
                                                    h2h_summary = (
                                                        f'{h2h_data.get("matches", 0)} partidos · promedio {h2h_data.get("avg_goals") if h2h_data.get("avg_goals") is not None else "N/D"} goles · ambos marcan {h2h_data.get("btts_rate") if h2h_data.get("btts_rate") is not None else "N/D"}% · +2.5 {h2h_data.get("over_2_5_rate") if h2h_data.get("over_2_5_rate") is not None else "N/D"}%'
                                                    )
                                                    st.markdown(f'<div class="goal-h2h-summary"><b>H2H · enfrentamientos directos</b><br>{html.escape(h2h_summary)}</div>', unsafe_allow_html=True)
                                                    target_minute = deep_context.get("current_goal_minute")
                                                    if target_minute is not None:
                                                        st.caption(f"Último gol detectado en el minuto {target_minute}" + (f" · anotado por {deep_context.get('current_goal_team')}" if deep_context.get("current_goal_team") else "") + ".")
                                                    comeback = deep_context.get("comeback") or {}
                                                    comeback_cols = st.columns(2, gap="small")
                                                    for col, team in zip(comeback_cols, (match_home, match_away)):
                                                        data = comeback.get(team.get("id"), {})
                                                        sample = data.get("sample", 0)
                                                        if sample:
                                                            col.markdown(
                                                                f'<div class="goal-comeback-card"><b>{html.escape(str(team.get("name") or "Equipo"))} · reacción</b>'
                                                                f'<span>Se quedó por detrás en {data.get("behind_cases", 0)} casos comparables; marcó después en {data.get("scored_after_conceding", 0)} y empató en {data.get("equalized", 0)}.</span>'
                                                                f'<small>Muestra de eventos analizados: {sample}; no representa una probabilidad calibrada.</small></div>',
                                                                unsafe_allow_html=True,
                                                            )
                                                        else:
                                                            col.caption(f"{team.get('name') or 'Equipo'}: muestra insuficiente de eventos para estimar reacción tras recibir gol.")
                                                else:
                                                    st.caption("El contexto profundo de forma/H2H no está disponible con las consultas actuales; el bot no lo tratará como dato conocido.")
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
                                                live_odds_rows = st.session_state.get("live_odds_by_fixture", {}).get(str(match_id), [])
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
                                                    if 1.25 <= odd < 1.60:
                                                        match_main_options.append(option)
                                                    elif odd >= 1.60:
                                                        match_risk_options.append(option)

                                                st.markdown('<div class="tip-section-heading"><span class="tip-heading-icon">◈</span><span>TIP PRINCIPAL</span><span class="tip-heading-status">EN VIVO</span></div>', unsafe_allow_html=True)
                                                if match_main_options:
                                                    selected_main = max(match_main_options, key=lambda x: x["prob"])
                                                    st.markdown(
                                                        f'<div class="tip-card"><div class="tip-card-label">✦ SEÑAL PRINCIPAL</div>'
                                                        f'<div class="tip-card-title">{html.escape(selected_main["market"])}</div>'
                                                        f'<div class="tip-card-meta">{html.escape(selected_main["bookmaker"])} · mercado en vivo verificado</div></div>',
                                                        unsafe_allow_html=True,
                                                    )
                                                else:
                                                    st.markdown('<div class="tip-card tip-card-empty"><div class="tip-card-label">✦ SEÑAL PRINCIPAL</div><div class="tip-card-title">Sin oportunidad confirmada por ahora</div><div class="tip-card-meta">Esperando una cuota disponible con respaldo estadístico.</div></div>', unsafe_allow_html=True)

                                                st.markdown('<div class="tip-section-heading risk-heading"><span class="tip-heading-icon">⌁</span><span>TIP DE ALTO RIESGO</span><span class="tip-heading-status">RIESGO ALTO</span></div>', unsafe_allow_html=True)
                                                if match_risk_options:
                                                    selected_risk = max(match_risk_options, key=lambda x: x["prob"])
                                                    st.markdown(
                                                        f'<div class="tip-card risk-tip-card"><div class="tip-card-label">⚡ SEÑAL DE ALTO RIESGO</div>'
                                                        f'<div class="tip-card-title">{html.escape(selected_risk["market"])}</div>'
                                                        f'<div class="tip-card-meta">{html.escape(selected_risk["bookmaker"])} · mercado en vivo verificado</div></div>',
                                                        unsafe_allow_html=True,
                                                    )
                                                else:
                                                    st.markdown('<div class="tip-card risk-tip-card tip-card-empty"><div class="tip-card-label">⚡ SEÑAL DE ALTO RIESGO</div><div class="tip-card-title">Sin oportunidad confirmada por ahora</div><div class="tip-card-meta">No se fuerza una selección ni se inventa un mercado.</div></div>', unsafe_allow_html=True)

                                                # Numerology is strictly risk-only context, never a standalone prediction.
                                                match_stats_for_patterns = st.session_state.stats_cache.get(str(match_id), [])
                                                numerology_patterns = numerology_context(
                                                    home_score, away_score,
                                                    safe_stat(match_stats_for_patterns, "Corner Kicks", 0),
                                                    safe_stat(match_stats_for_patterns, "Corner Kicks", 1),
                                                    safe_stat(match_stats_for_patterns, "Yellow Cards", 0),
                                                    safe_stat(match_stats_for_patterns, "Yellow Cards", 1),
                                                )
                                            else:
                                                st.info("Primero pulsa «Escanear todos los partidos en vivo». Después, vuelve a abrir Goles y señales para ver promedios por localía, lectura en vivo y tip principal.")
                                        elif market_key == "corners":
                                            with st.container(key=f"analysis_scan_cta_corners_{match_id}"):
                                                _corner_scan_cols = st.columns(2, gap="small")
                                                with _corner_scan_cols[0]:
                                                    _corner_radar_clicked = st.button("⚽ Escanear en vivo", key=f"analysis_scan_radar_corners_{match_id}")
                                                with _corner_scan_cols[1]:
                                                    _corner_refresh_clicked = st.button("⟳ Actualizar scan", key=f"analysis_scan_corners_{match_id}")
                                                if _corner_radar_clicked or _corner_refresh_clicked:
                                                    # Dar prioridad al partido que el usuario tiene abierto antes de
                                                    # construir el contexto histórico de los demás partidos en vivo.
                                                    st.session_state["selected_match_detail"] = {
                                                        "fixture_id": match_id,
                                                        "market": "corners",
                                                    }
                                                    manual_scan = True
                                                    internal_scan_requested = True
                                                    st.markdown('<div class="scan-running-status"><span class="scan-code-icon">⟳</span><div><strong>ESCANEANDO…</strong><div class="scan-running-subtitle">Actualizando proyección y datos en vivo</div></div><span class="scan-sweep"></span></div>', unsafe_allow_html=True)
                                            st.markdown('<div class="match-analysis-kicker">Mercado seleccionado · córners</div><div class="match-analysis-title">Ritmo y proyección de córners</div>', unsafe_allow_html=True)
                                            # Reutilizar primero las estadísticas que ya consultó el escáner en vivo.
                                            live_corner_stats = st.session_state.stats_cache.get(str(match_id))
                                            known_stats_error = str(match_id) in st.session_state.get("stats_errors", {})
                                            if live_corner_stats is None or (not live_corner_stats and not known_stats_error):
                                                try:
                                                    live_corner_stats = (api_get("fixtures/statistics", {"fixture": match_id}).get("response") or [])
                                                    st.session_state.stats_cache[str(match_id)] = live_corner_stats
                                                    selected_home_corners = safe_stat(live_corner_stats, "Corner Kicks", 0)
                                                    selected_away_corners = safe_stat(live_corner_stats, "Corner Kicks", 1)
                                                    if selected_home_corners is None or selected_away_corners is None:
                                                        st.session_state.setdefault("stats_errors", {})[str(match_id)] = "La API no entregó córners para ambos equipos."
                                                    else:
                                                        st.session_state.setdefault("stats_errors", {}).pop(str(match_id), None)
                                                except Exception as live_corner_exc:
                                                    live_corner_stats = []
                                                    st.session_state.stats_cache[str(match_id)] = []
                                                    st.session_state.setdefault("stats_errors", {})[str(match_id)] = str(live_corner_exc)
                                            selected_home_corners = safe_stat(live_corner_stats or [], "Corner Kicks", 0)
                                            selected_away_corners = safe_stat(live_corner_stats or [], "Corner Kicks", 1)
                                            st.markdown(fixture_hero_html(match, mode="corners", home_corners=selected_home_corners, away_corners=selected_away_corners), unsafe_allow_html=True)
                                            corner_item = next((item for item in st.session_state.get("corner_scan_results", []) if str(((item.get("fixture") or {}).get("fixture") or {}).get("id")) == str(match_id)), None)
                                            if corner_item and not corner_item.get("error"):
                                                home_c, away_c = corner_item.get("home_corners"), corner_item.get("away_corners")
                                                current_minute = (match_fixture.get("status") or {}).get("elapsed")
                                                current_total = (home_c + away_c) if isinstance(home_c, (int, float)) and isinstance(away_c, (int, float)) else None
                                                history = corner_item.get("automatic_history") or {}
                                                # Los córners actuales ya aparecen en la tarjeta superior del partido.
                                                # Evitamos repetir local, visitante y total en tres tarjetas separadas.

                                                st.markdown("### 📊 Promedios de córners en la competición actual")
                                                history_rows = [
                                                    {"Indicador": "Córners a favor del local en casa", "Promedio": history.get("home_corners_for"), "Muestra": history.get("home_corner_sample", 0)},
                                                    {"Indicador": "Córners concedidos por el local en casa", "Promedio": history.get("home_corners_against"), "Muestra": history.get("home_corner_sample", 0)},
                                                    {"Indicador": "Córners a favor del visitante fuera", "Promedio": history.get("away_corners_for"), "Muestra": history.get("away_corner_sample", 0)},
                                                    {"Indicador": "Córners concedidos por el visitante fuera", "Promedio": history.get("away_corners_against"), "Muestra": history.get("away_corner_sample", 0)},
                                                ]
                                                history_html = '<table class="history-table"><thead><tr><th>Indicador</th><th>Promedio</th></tr></thead><tbody>'
                                                for row in history_rows:
                                                    avg = row["Promedio"]
                                                    avg_text = f"{avg:.2f}".rstrip("0").rstrip(".") if isinstance(avg, (int, float)) else "N/D"
                                                    history_html += f"<tr><td>{html.escape(row['Indicador'])}</td><td>{avg_text}</td></tr>"
                                                history_html += "</tbody></table>"
                                                st.markdown(history_html, unsafe_allow_html=True)

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
                                                if projected_home_corners is not None and projected_away_corners is not None:
                                                    competition_corner_average = projected_home_corners + projected_away_corners
                                                    st.markdown(
                                                        f"""
                                                        <div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;
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

                                                st.markdown("### ⌁ Histórico de córners")
                                                home_team = (match.get("teams") or {}).get("home") or {}
                                                away_team = (match.get("teams") or {}).get("away") or {}
                                                h2h_key = f"corner-h2h-v3-home-{home_team.get('id')}-{away_team.get('id')}"
                                                if "corner_h2h_cache" not in st.session_state:
                                                    st.session_state.corner_h2h_cache = {}
                                                if st.button("Consultar histórico de córners", key=f"corner_h2h_{match_id}"):
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
                                                                    stats_key = f"corner-h2h-stats:{past_id}"
                                                                    if stats_key not in st.session_state.stats_cache:
                                                                        st.session_state.stats_cache[stats_key] = (api_get("fixtures/statistics", {"fixture": past_id}).get("response") or [])
                                                                    past_stats = st.session_state.stats_cache.get(stats_key) or []
                                                                    past_home_c = safe_stat(past_stats, "Corner Kicks", 0)
                                                                    past_away_c = safe_stat(past_stats, "Corner Kicks", 1)
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
                                                        corners_html = '<div class="corner-h2h-row corner-history-grid" style="font-weight:800;color:#FACC15;border-bottom:1px solid #51451D;"><span>Fecha</span><span>Local</span><span class="corner-h2h-value">Córners L</span><span>Visitante</span><span class="corner-h2h-value">Córners V</span><span class="corner-h2h-value">Total córners</span></div>'
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
                                                                f'<span class="corner-h2h-value">{html.escape(str(row.get("Total") if row.get("Total") is not None else "N/D"))}</span></div>'
                                                            )
                                                        st.markdown(corners_html, unsafe_allow_html=True)
                                                        valid_totals = [row["Total"] for row in h2h_rows if isinstance(row.get("Total"), (int, float))]
                                                        if valid_totals:
                                                            h2h_avg = sum(valid_totals) / len(valid_totals)
                                                            st.markdown(
                                                                f"""
                                                                <div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;
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
                                                    total_match_average = (competition_corner_average + h2h_avg) / 2
                                                    st.markdown(
                                                        f"""
                                                        <div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;
                                                                    margin:16px 0 18px;padding:7px 10px;
                                                                    border:1px solid #51451D;border-radius:9px;
                                                                    background:linear-gradient(135deg,#17191f,#20232b);
                                                                    width:fit-content;max-width:100%;clear:both;position:relative;">
                                                          <span style="font-size:11px;font-weight:700;color:#FACC15;letter-spacing:.3px;">
                                                            PROMEDIO TOTAL PARA ESTE PARTIDO
                                                          </span>
                                                          <span style="display:inline-block;padding:4px 9px;
                                                                       border:1px solid #FACC15;border-radius:7px;
                                                                       background:#FACC15;color:#111827;
                                                                       font-size:13px;font-weight:800;line-height:1.1;">
                                                            {total_match_average:.2f}
                                                          </span>
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
                                                        st.markdown(f'<div class="tip-card"><div class="tip-card-label">✦ SEÑAL PRINCIPAL · CUOTA {chosen["odd"]:.2f}</div><div class="tip-card-title">{html.escape(chosen["market"])}</div><div class="tip-card-meta">{html.escape(chosen["bookmaker"])} · probabilidad exploratoria {chosen["prob"]:.1%} · ventaja estimada {chosen["edge"]:.1%}</div></div>', unsafe_allow_html=True)
                                                    else:
                                                        st.markdown('<div class="tip-card tip-card-empty"><div class="tip-card-label">✦ SEÑAL PRINCIPAL</div><div class="tip-card-title">Sin oportunidad confirmada por ahora</div><div class="tip-card-meta">Se requiere respaldo estadístico suficiente.</div></div>', unsafe_allow_html=True)
                                                    st.markdown('<div class="tip-section-heading risk-heading"><span class="tip-heading-icon">⌁</span><span>TIP DE ALTO RIESGO</span></div>', unsafe_allow_html=True)
                                                    if risk_options:
                                                        chosen_risk = max(risk_options, key=lambda option: option["edge"])
                                                        st.markdown(f'<div class="tip-card risk-tip-card"><div class="tip-card-label">⚡ SEÑAL DE ALTO RIESGO · CUOTA {chosen_risk["odd"]:.2f}</div><div class="tip-card-title">{html.escape(chosen_risk["market"])}</div><div class="tip-card-meta">{html.escape(chosen_risk["bookmaker"])} · probabilidad exploratoria {chosen_risk["prob"]:.1%} · ventaja estimada {chosen_risk["edge"]:.1%}</div></div>', unsafe_allow_html=True)
                                                    else:
                                                        st.markdown('<div class="tip-card risk-tip-card tip-card-empty"><div class="tip-card-label">⚡ SEÑAL DE ALTO RIESGO</div><div class="tip-card-title">Sin oportunidad confirmada por ahora</div><div class="tip-card-meta">Se requiere respaldo estadístico suficiente.</div></div>', unsafe_allow_html=True)
                                                    goals = match.get("goals") or {}
                                                    patterns = numerology_context(goals.get("home"), goals.get("away"), home_c, away_c, safe_stat(st.session_state.stats_cache.get(str(match_id), []), "Yellow Cards", 0), safe_stat(st.session_state.stats_cache.get(str(match_id), []), "Yellow Cards", 1))
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
        and now_epoch - int(st.session_state.last_auto_market_scan_epoch) >= 300
    )
    if manual_scan or auto_scan_due:
        st.session_state.last_auto_market_scan_epoch = now_epoch
        scan_api_calls_start = st.session_state.api_request_count
        # Force fresh statistics for this scan; cap detailed-stat calls to protect API quota.
        st.session_state.stats_cache = {}
        st.session_state.goal_scan_results = []
        st.session_state.corner_scan_results = []
        # Fetch live statistics before estimating goals, so this same scan can
        # actually use the activity context instead of only using a cache from a
        # previous run. One request per fixture; subsequent sections reuse the cache.
        stats_fetch_progress = st.empty()
        effective_stats_limit = min(stats_limit, 5) if auto_scan_due and not manual_scan else stats_limit
        stats_fixtures = filtered[:effective_stats_limit]
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
        # Mark fixtures beyond the configured detail limit as unavailable for this
        # scan, so the corners pass does not issue hidden extra API requests.
        for skipped_fixture in filtered[len(stats_fixtures):]:
            skipped_id = (skipped_fixture.get("fixture") or {}).get("id")
            if skipped_id is not None:
                st.session_state.stats_cache[str(skipped_id)] = []
        stats_fetch_progress.empty()
        st.session_state.last_scan_stats_matches = stats_queries_attempted

        # Fetch live odds once per scan for all returned fixtures (never one request per match).
        # Refresh no more often than the scan itself; the API plan limits still apply.
        odds_now = datetime.now().timestamp()
        last_odds_epoch = float(st.session_state.get("live_odds_last_fetch_epoch", 0) or 0)
        if get_api_key() and (manual_scan or odds_now - last_odds_epoch >= 300):
            try:
                odds_payload = api_get("odds/live")
                st.session_state.live_odds_by_fixture = extract_live_odds(odds_payload)
                st.session_state.live_odds_last_fetch = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                st.session_state.live_odds_last_fetch_epoch = odds_now
                st.session_state.live_odds_error = ""
            except Exception as odds_exc:
                st.session_state.live_odds_error = str(odds_exc)
        elif "live_odds_by_fixture" not in st.session_state:
            st.session_state.live_odds_by_fixture = {}

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
        # Automatic historical context, cached by team and fixture. Limit historical
        # statistics calls per scan so this does not silently consume the whole API quota.
        history_calls_before = st.session_state.api_request_count
        history_cache = st.session_state.setdefault("automatic_history_cache", {})
        history_cache["_automatic_history_stats_calls"] = 0
        # El límite de consultas de equipos empieza desde cero en cada escaneo.
        # No reservar consultas a ciegas para partidos que el usuario no está viendo.
        history_cache["_automatic_history_team_fixture_calls"] = 0
        # Priorizar el partido abierto por el usuario para que el presupuesto histórico
        # no se consuma primero en otros partidos del escáner.
        selected_detail_for_history = st.session_state.get("selected_match_detail") or {}
        selected_history_fixture_id = str(selected_detail_for_history.get("fixture_id") or "")
        corner_results.sort(
            key=lambda item: 0 if str(((item.get("fixture") or {}).get("fixture") or {}).get("id") or "") == selected_history_fixture_id else 1
        )
        for corner_item in corner_results:
            if corner_item.get("error"):
                continue
            try:
                used_history_stats = int(history_cache.get("_automatic_history_stats_calls", 0))
                history_budget = 8 if auto_scan_due and not manual_scan else 20
                corner_item["automatic_history"] = build_automatic_history(
                    corner_item["fixture"],
                    api_get=api_get,
                    cache=history_cache,
                    stats_budget=max(0, history_budget - used_history_stats),
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

        # Si el escaneo se inició desde la vista individual, volver a renderizarla con resultados nuevos.
        if internal_scan_requested:
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
        for fixture, estimate, tips, context in goal_results_with_context:
            for market, probability in tips:
                fixture_data = fixture.get("fixture") or {}
                goals_data = fixture.get("goals") or {}
                row = {
                    "recorded_at": datetime.now().isoformat(timespec="seconds"),
                    "fixture_id": fixture_data.get("id"),
                    "league": (fixture.get("league") or {}).get("name"),
                    "home": ((fixture.get("teams") or {}).get("home") or {}).get("name"),
                    "away": ((fixture.get("teams") or {}).get("away") or {}).get("name"),
                    "minute": context.get("elapsed"),
                    "score_home": goals_data.get("home"),
                    "score_away": goals_data.get("away"),
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
                }
                row_key = (str(row["fixture_id"]), str(row["market"]), str(row["minute"]),
                           str(row["score_home"]), str(row["score_away"]))
                if row_key not in existing_keys:
                    signal_rows.append(row)
                    existing_keys.add(row_key)
        st.session_state.signal_rows = signal_rows
        try:
            if signal_rows:
                SIGNAL_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
                with SIGNAL_HISTORY_PATH.open("w", encoding="utf-8-sig", newline="") as history_file:
                    writer = csv.DictWriter(history_file, fieldnames=list(signal_rows[0].keys()))
                    writer.writeheader()
                    writer.writerows(signal_rows)
        except OSError as history_exc:
            st.session_state.signal_history_write_error = str(history_exc)
        st.session_state.last_scan_api_calls = st.session_state.api_request_count - scan_api_calls_start

    # El panel global de escaneo no debe mezclarse con la pantalla individual seleccionada.
    if not _analysis_page_active:
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
                search_matches = st.text_input("🔎 Buscar equipo o liga", placeholder="Ej. Argentinos Juniors, Premier League…", key="search_goal_matches").strip().casefold()
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
                    home_shots = safe_stat(live_stats, "Total Shots", 0)
                    away_shots = safe_stat(live_stats, "Total Shots", 1)
                    home_on = safe_stat(live_stats, "Shots on Goal", 0)
                    away_on = safe_stat(live_stats, "Shots on Goal", 1)
                    home_poss = safe_stat(live_stats, "Ball Possession", 0)
                    away_poss = safe_stat(live_stats, "Ball Possession", 1)
                    home_corners = safe_stat(live_stats, "Corner Kicks", 0)
                    away_corners = safe_stat(live_stats, "Corner Kicks", 1)
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
                    odds_by_fixture = st.session_state.get("live_odds_by_fixture", {})
                    match_odds = odds_by_fixture.get(str(fixture_id), [])
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
                                    current_home_corners = safe_stat(corner_stats, "Corner Kicks", 0)
                                    current_away_corners = safe_stat(corner_stats, "Corner Kicks", 1)
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
                        if 1.25 <= odd < 1.60:
                            main_options.append(option)
                        if odd >= 1.60:
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
                            f'<div class="tip-card"><div class="tip-card-label">TIP PRINCIPAL · CUOTA {chosen_main["odd"]:.2f}</div>'
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
                                f'<div class="tip-card risk-tip-card"><div class="tip-card-label">ALTO RIESGO · CUOTA {risk_item["odd"]:.2f}</div>'
                                f'<div class="tip-card-title">{html.escape(risk_item["market"])}</div>'
                                f'<div class="tip-card-meta">{html.escape(risk_item["bookmaker"])} · Probabilidad estimada {risk_item["model_prob"]:.1%} · Implícita {risk_item["implied_probability"]:.1%} · Ventaja estimada {risk_item["estimated_edge"]:.1%}</div></div>',
                                unsafe_allow_html=True,
                            )
                        risk_stats = st.session_state.stats_cache.get(str(fixture_id), [])
                        risk_home_corners = safe_stat(risk_stats, "Corner Kicks", 0)
                        risk_away_corners = safe_stat(risk_stats, "Corner Kicks", 1)
                        risk_home_yellow = safe_stat(risk_stats, "Yellow Cards", 0)
                        risk_away_yellow = safe_stat(risk_stats, "Yellow Cards", 1)
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
                            # Match live corner markets to real odds from API-Football.
                            # A price alone is never enough: require a provisional model edge.
                            fixture_id = ((item.get("fixture") or {}).get("fixture") or {}).get("id")
                            live_rows = st.session_state.get("live_odds_by_fixture", {}).get(str(fixture_id), [])
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
                                    f'<div class="tip-card"><div class="tip-card-label">TIP PRINCIPAL</div>'
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
                                    f'<div class="tip-card risk-tip-card"><div class="tip-card-label">ALTO RIESGO</div>'
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
                st.caption(f"Registro guardado en el archivo local {SIGNAL_HISTORY_PATH}. En servicios de alojamiento con disco efímero, descarga el CSV para conservarlo fuera de la sesión.")
                if st.session_state.get("signal_history_write_error"):
                    st.warning(f"No se pudo guardar el registro en disco: {st.session_state.signal_history_write_error}")

        if not goal_results and not corner_results:
            st.info("Pulsa «Escanear todos los partidos en vivo» para generar el primer informe.")
        elif not goal_results:
            st.info("En esta ronda no hubo señales de goles que superaran el umbral experimental del 65%. Esto no significa que todos los partidos carezcan de datos ni que no existan candidatos de córners.")
            st.caption("El modelo necesita una referencia histórica compatible para estimar goles. Si no la encuentra, la señal se marca como no disponible; las estadísticas en vivo no sustituyen por sí solas una base histórica fiable.")


