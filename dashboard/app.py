import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import subprocess
import json
import html as html_module
from datetime import date, timedelta
import plotly.graph_objects as go

from core.models import ConstraintSnapshot, RegimeStatus, Sector, Country

# === PAGE CONFIG ===
st.set_page_config(page_title="AI Infra Sentinel", layout="wide", initial_sidebar_state="expanded")

# === HELPER: always render HTML safely ===
def rhtml(content):
    st.markdown(content, unsafe_allow_html=True)

# === CSS ===
rhtml("""<style>
    .stApp { background-color: #F5F3FF; font-family: 'Inter', -apple-system, sans-serif; }
    .block-container { padding-top: 2rem !important; }
    .card {
        background: #FFFFFF; border-radius: 16px; border: 1px solid #EDE9FE;
        padding: 20px; box-shadow: 0 2px 8px rgba(139,92,246,0.08);
        margin-bottom: 16px; height: 100%;
    }
    .card-title {
        color: #6B7280; font-size: 13px; font-weight: 600;
        text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 12px;
    }
    .score { font-size: 32px; font-weight: 700; color: #1E1B4B; }
    .metric-big { font-size: 42px; font-weight: 800; color: #1E1B4B; }
    .dot-g { display:inline-block; width:10px; height:10px; border-radius:50%; background:#10B981; margin-left:8px; vertical-align:middle; }
    .dot-a { display:inline-block; width:10px; height:10px; border-radius:50%; background:#F59E0B; margin-left:8px; vertical-align:middle; }
    .dot-r { display:inline-block; width:10px; height:10px; border-radius:50%; background:#EF4444; margin-left:8px; vertical-align:middle; }
    .badge-stable { background:#D1FAE5; color:#065F46; padding:6px 16px; border-radius:999px; font-weight:bold; font-size:14px; display:inline-block; }
    .badge-shift { background:#FEF3C7; color:#92400E; padding:6px 16px; border-radius:999px; font-weight:bold; font-size:14px; display:inline-block; }
    .badge-change { background:#FEE2E2; color:#991B1B; padding:6px 16px; border-radius:999px; font-weight:bold; font-size:14px; display:inline-block; }
    .badge-purple { background:#F5F3FF; color:#7C3AED; border:1px solid #EDE9FE; padding:6px 16px; border-radius:999px; font-weight:bold; font-size:14px; display:inline-block; }
    
    .tooltip-wrap { position: relative; cursor: help; }
    .tooltip-wrap .tooltip-text {
        visibility: hidden; opacity: 0;
        position: absolute; z-index: 999;
        bottom: 110%; left: 50%; transform: translateX(-50%);
        background: #1E1B4B; color: #fff; padding: 12px 16px;
        border-radius: 10px; font-size: 12px; line-height: 1.5;
        width: 280px; white-space: pre-line;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        transition: opacity 0.2s;
        pointer-events: none;
    }
    .tooltip-wrap:hover .tooltip-text {
        visibility: visible; opacity: 1;
    }
</style>""")

# === SECTOR CONFIG ===
SECTOR_LABELS = {
    "GPU_CHIPS": "GPU/Chips", "DATA_CENTERS": "Data Centers",
    "POWER_ENERGY": "Power & Energy", "CLOUD_COMPUTE": "Cloud/Compute",
    "COOLING_INFRA": "Cooling & Infra", "POLICY": "Policy"
}
SECTOR_COLORS = {
    "GPU_CHIPS": "#7C3AED", "DATA_CENTERS": "#2563EB",
    "POWER_ENERGY": "#DC2626", "CLOUD_COMPUTE": "#059669",
    "COOLING_INFRA": "#D97706", "POLICY": "#6B7280"
}

# === MOCK DATA ===
def generate_mock_data():
    import random
    random.seed(42)
    snapshots = []
    for sector in Sector:
        for country in [Country.US, Country.CN]:
            score = random.randint(20, 90)
            snapshots.append(ConstraintSnapshot(
                date=date.today(), country=country, sector=sector,
                severity_score=score,
                top_signals=["Sample signal A", "Sample signal B", "Sample signal C"],
                source_urls=["https://example.com"],
                reasoning=f"Mock analysis for {SECTOR_LABELS.get(sector.value, sector.value)} in {country.value}."
            ))
    return snapshots

# === CACHED DATA LOADING ===
@st.cache_data(ttl=300)
def load_all_data():
    import json
    from data.db import get_latest_by_sector, get_history, get_conn
    from core.delta_tracker import compute_deltas
    from core.rules_engine import evaluate_regime, identify_bottleneck
    from datetime import date, timedelta
    from core.models import RegimeStatus

    snapshots = list(get_latest_by_sector().values())
    history = get_history(days=7)
    latest_date = max(s.date for s in snapshots) if snapshots else date.today()
    
    yesterday = [s for s in history if s.date == latest_date - timedelta(days=1)]
    week_ago = [s for s in history if s.date == latest_date - timedelta(days=7)]
    deltas = compute_deltas(snapshots, yesterday, week_ago) if yesterday else []
    
    if history:
        regime, bottleneck = evaluate_regime(deltas, history)
    else:
        regime = RegimeStatus.STABLE
        bottleneck = identify_bottleneck(snapshots)
        
    synth_bullets = []
    trade_list = []
    try:
        conn = get_conn()
        row = conn.execute("SELECT synthesis, trade_ideas FROM daily_summaries ORDER BY date DESC LIMIT 1").fetchone()
        conn.close()
        if row:
            if row.get("synthesis"):
                loaded = row["synthesis"]
                if isinstance(loaded, str): loaded = json.loads(loaded)
                if isinstance(loaded, list) and len(loaded) > 0: synth_bullets = loaded
            if row.get("trade_ideas"):
                loaded_trades = row["trade_ideas"]
                if isinstance(loaded_trades, str): loaded_trades = json.loads(loaded_trades)
                if isinstance(loaded_trades, list) and len(loaded_trades) > 0: trade_list = loaded_trades
    except Exception:
        pass
        
    return {
        "snapshots": snapshots,
        "history": history, 
        "deltas": deltas,
        "regime": regime,
        "bottleneck": bottleneck,
        "latest_date": latest_date,
        "synth_bullets": synth_bullets,
        "trade_list": trade_list
    }

# === LOAD DATA ===
try:
    data = load_all_data()
    use_mock = False
    snapshots = data["snapshots"]
    history = data["history"]
    deltas = data["deltas"]
    regime = data["regime"]
    bottleneck = data["bottleneck"]
    latest_date = data["latest_date"]
except Exception:
    use_mock = True
    snapshots = generate_mock_data()
    history = []
    deltas = []
    regime = RegimeStatus.STABLE
    latest_date = date.today()
    bottleneck = next((s.sector for s in snapshots if s.country == Country.US and s.severity_score > 70), Sector.POWER_ENERGY)

# === BUILD LOOKUP DICTS ===
score_map = {(s.country.value, s.sector.value): s for s in snapshots}
delta_map = {(d.country.value, d.sector.value): d for d in deltas}

us_scores = [s.severity_score for s in snapshots if s.country == Country.US]
cn_scores = [s.severity_score for s in snapshots if s.country == Country.CN]
avg_us = round(sum(us_scores) / len(us_scores)) if us_scores else 0
avg_cn = round(sum(cn_scores) / len(cn_scores)) if cn_scores else 0

if deltas:
    us_deltas = [d.delta_1d for d in deltas if d.country.value == "US"]
    cn_deltas = [d.delta_1d for d in deltas if d.country.value == "CN"]
    avg_us_delta = round(sum(us_deltas) / len(us_deltas)) if us_deltas else 0
    avg_cn_delta = round(sum(cn_deltas) / len(cn_deltas)) if cn_deltas else 0
else:
    avg_us_delta = 0
    avg_cn_delta = 0

# === SIDEBAR ===
with st.sidebar:
    st.markdown("### 🛰️ AI Infra Sentinel")
    st.divider()
    st.markdown(f"**Last scan:** {latest_date}")
    st.markdown(f"**Regime:** {regime.value.replace('_', ' ')}")
    st.markdown(f"**Bottleneck:** {SECTOR_LABELS.get(bottleneck.value, bottleneck.value)}")
    st.divider()
    if st.button("🔄 Run Full Scan", use_container_width=True):
        with st.spinner("Running AI Agents (Scan in progress)..."):
            project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            result = subprocess.run(
                ["python", "orchestrator.py"],
                capture_output=True, text=True, encoding="utf-8",
                cwd=project_dir
            )
            if result.returncode == 0:
                st.success("Scan complete!")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error(f"Scan error: {result.stderr[-500:]}")
    st.divider()
    if use_mock:
        st.caption("⚠️ Showing mock data")
    else:
        st.caption(f"✅ DB: {len(snapshots)} sectors loaded")
    st.caption("v1.0 · Powered by GPT-4o")

# === STATUS BANNER ===
if use_mock:
    st.warning("Showing sample data. Run scan to retrieve actual dataset.")
else:
    st.info(f"📡 Live data from {latest_date} ({len(snapshots)} sectors)")

# ============================================================
# KPI CARDS ROW
# ============================================================
c1, c2, c3, c4 = st.columns(4)

regime_class = {
    "STABLE": "badge-stable",
    "BOTTLENECK_SHIFT": "badge-shift",
    "REGIME_CHANGE": "badge-change"
}.get(regime.value, "badge-stable")

with c1:
    rhtml(f'''<div class="card">
        <div class="card-title">REGIME STATUS</div>
        <span class="{regime_class}">{regime.value.replace("_"," ")}</span>
    </div>''')

with c2:
    rhtml(f'''<div class="card">
        <div class="card-title">CURRENT BOTTLENECK</div>
        <span class="badge-purple">{SECTOR_LABELS.get(bottleneck.value, bottleneck.value)}</span>
    </div>''')

with c3:
    if avg_us_delta != 0:
        us_arrow = "↑" if avg_us_delta > 0 else "↓"
        us_d_color = "#EF4444" if avg_us_delta > 0 else "#10B981"
        us_delta_str = f'<span style="color:{us_d_color};font-size:14px;font-weight:600;margin-left:12px;">{us_arrow} {avg_us_delta:+d}</span>'
    else:
        us_delta_str = ""
    rhtml(f'''<div class="card">
        <div class="card-title">AVG US SEVERITY</div>
        <span class="metric-big">{avg_us}</span>{us_delta_str}
    </div>''')

with c4:
    if avg_cn_delta != 0:
        cn_arrow = "↑" if avg_cn_delta > 0 else "↓"
        cn_d_color = "#EF4444" if avg_cn_delta > 0 else "#10B981"
        cn_delta_str = f'<span style="color:{cn_d_color};font-size:14px;font-weight:600;margin-left:12px;">{cn_arrow} {avg_cn_delta:+d}</span>'
    else:
        cn_delta_str = ""
    rhtml(f'''<div class="card">
        <div class="card-title">AVG CN SEVERITY</div>
        <span class="metric-big">{avg_cn}</span>{cn_delta_str}
    </div>''')

# ============================================================
# HEATMAP TABLE + MACRO SYNTHESIS
# ============================================================
col_left, col_right = st.columns([6, 4])

with col_left:
    table_html = '<div class="card"><div class="card-title">SECTOR HEATMAP (US VS CN)</div>'
    table_html += '<table style="width:100%;border-collapse:collapse;">'
    table_html += '''<tr style="background:#EDE9FE;">
        <th style="padding:12px;text-align:left;color:#1E1B4B;font-size:12px;font-weight:700;text-transform:uppercase;">SECTOR</th>
        <th style="padding:12px;text-align:left;color:#1E1B4B;font-size:12px;font-weight:700;text-transform:uppercase;">UNITED STATES</th>
        <th style="padding:12px;text-align:left;color:#1E1B4B;font-size:12px;font-weight:700;text-transform:uppercase;">CHINA</th>
    </tr>'''

    for sector in Sector:
        table_html += '<tr style="border-bottom:1px solid #EDE9FE;">'
        table_html += f'<td style="padding:16px 12px;font-weight:600;color:#1E1B4B;">{SECTOR_LABELS.get(sector.value, sector.value)}</td>'

        for country_val in ["US", "CN"]:
            snap = score_map.get((country_val, sector.value))
            delta_obj = delta_map.get((country_val, sector.value))
            score = snap.severity_score if snap else 50
            d1 = delta_obj.delta_1d if delta_obj else 0

            dot_class = "dot-g" if score <= 40 else ("dot-a" if score <= 70 else "dot-r")

            if delta_obj and d1 != 0:
                arrow = "↑" if d1 > 0 else "↓"
                d_color = "#EF4444" if d1 > 0 else "#10B981"
                delta_display = f'<div style="color:{d_color};font-size:12px;margin-top:4px;font-weight:600;">{arrow}{d1:+d}</div>'
            else:
                delta_display = '<div style="color:#9CA3AF;font-size:12px;margin-top:4px;">—</div>'

            signals = snap.top_signals if snap else []
            reasoning = snap.reasoning if snap else ""
            sector_label = SECTOR_LABELS.get(sector.value, sector.value)
            
            signals_text = "\n".join(["• " + str(s) for s in signals[:3]])
            reasoning_short = str(reasoning)[:200]
            tooltip_content = f"""{sector_label} ({country_val})
Score: {score}/100

Signals:
{signals_text}

{reasoning_short}"""
            tooltip_content = html_module.escape(tooltip_content)

            table_html += f'''<td style="padding:16px 12px;">
                <div class="tooltip-wrap">
                    <span class="score">{score}</span>
                    <span class="{dot_class}"></span>
                    {delta_display}
                    <div class="tooltip-text">{tooltip_content}</div>
                </div>
            </td>'''

        table_html += '</tr>'

    table_html += '</table></div>'
    rhtml(table_html)

with col_right:
    synth_bullets = [
        "Power grid interconnection queue is the binding constraint. Average wait time extended to 4.2 years.",
        "GPU supply bottlenecks are easing, shifting constraints downstream.",
        "Cooling infrastructure upgrades are required for next-gen workloads."
    ]
    if not use_mock and data.get("synth_bullets"):
        synth_bullets = data["synth_bullets"]

    synth_html = '<div class="card"><div class="card-title">MACRO SYNTHESIS</div>'
    for b in synth_bullets:
        safe_b = html_module.escape(str(b))
        synth_html += f'''<div style="display:flex;gap:10px;margin-bottom:14px;align-items:flex-start;">
            <span style="color:#7C3AED;font-size:20px;line-height:1.4;">•</span>
            <span style="color:#374151;font-size:14px;line-height:1.6;">{safe_b}</span>
        </div>'''
    synth_html += '</div>'
    rhtml(synth_html)

# ============================================================
# 7-DAY TREND CHART + TRADE IDEAS
# ============================================================
col_chart, col_trades = st.columns([6, 4])

with col_chart:
    rhtml('<div class="card"><div class="card-title">7-DAY SEVERITY TREND</div></div>')

    if history and len(history) > 0:
        fig = go.Figure()
        has_data = False
        for sector in Sector:
            sector_data = sorted(
                [s for s in history if s.sector == sector and s.country == Country.US],
                key=lambda x: x.date
            )
            if sector_data:
                has_data = True
                fig.add_trace(go.Scatter(
                    x=[s.date for s in sector_data],
                    y=[s.severity_score for s in sector_data],
                    mode='lines+markers',
                    name=SECTOR_LABELS.get(sector.value, sector.value),
                    line=dict(color=SECTOR_COLORS.get(sector.value, "#999"), width=2.5),
                    marker=dict(size=5)
                ))
        if has_data:
            fig.update_layout(
                template="plotly_white", height=350,
                margin=dict(l=20, r=20, t=10, b=40),
                legend=dict(orientation="h", yanchor="bottom", y=-0.35, xanchor="center", x=0.5),
                yaxis_title="Severity", xaxis_title=""
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("📈 No trend data yet. Run scans over multiple days to see trends.")
    else:
        st.caption("📈 No trend data yet. Run scans over multiple days to see trends.")

with col_trades:
    trade_list = [
        {"direction": "LONG", "ticker": "PWR", "rationale": "Grid upgrade supercycle", "conviction": "HIGH"},
        {"direction": "SHORT", "ticker": "SMCI", "rationale": "Margin compression risks", "conviction": "HIGH"},
        {"direction": "LONG", "ticker": "MEG", "rationale": "Cooling demand surge", "conviction": "MED"},
        {"direction": "SHORT", "ticker": "NVDA", "rationale": "Short-term valuation stretch", "conviction": "LOW"},
    ]
    if not use_mock and data.get("trade_list"):
        trade_list = data["trade_list"]

    trades_html = '<div class="card"><div class="card-title">TRADE IDEAS</div>'
    for i, t in enumerate(trade_list):
        d = t.get("direction", "LONG")
        ticker = html_module.escape(str(t.get("ticker", "")))
        rationale = html_module.escape(str(t.get("rationale", "")))
        conv = t.get("conviction", "MED")

        pill_bg = "#FEE2E2" if d == "SHORT" else "#DCFCE7"
        pill_color = "#DC2626" if d == "SHORT" else "#16A34A"

        if conv == "HIGH":
            conv_bg, conv_color = "#7C3AED", "#FFFFFF"
        elif conv == "MED":
            conv_bg, conv_color = "#EDE9FE", "#7C3AED"
        else:
            conv_bg, conv_color = "#F3F4F6", "#6B7280"

        border_bottom = "border-bottom:1px solid #EDE9FE;" if i < len(trade_list) - 1 else ""

        trades_html += f'''<div style="display:flex;align-items:center;justify-content:space-between;padding:14px 0;{border_bottom}">
            <span style="display:inline-block;min-width:70px;padding:6px 14px;border-radius:8px;
                font-weight:700;font-size:13px;text-align:center;white-space:nowrap;
                background:{pill_bg};color:{pill_color};">{d}</span>
            <div style="flex:1;margin-left:16px;">
                <div style="font-size:18px;font-weight:700;color:#1E1B4B;">{ticker}</div>
                <div style="font-size:13px;color:#6B7280;margin-top:2px;">{rationale}</div>
            </div>
            <span style="padding:4px 12px;border-radius:6px;font-size:12px;font-weight:700;
                background:{conv_bg};color:{conv_color};">{conv}</span>
        </div>'''

    trades_html += '</div>'
    rhtml(trades_html)
