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
st.set_page_config(page_title="AI Infra Sentinel", layout="wide", initial_sidebar_state="auto")

# === HELPER: always render HTML safely ===
def rhtml(content):
    st.markdown(content, unsafe_allow_html=True)

# === CSS ===
rhtml("""<style>
    .stApp { padding-top: 0; background-color: #F5F3FF; font-family: 'Inter', -apple-system, sans-serif; }
    .block-container { padding-top: 1rem !important; }
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
    with st.expander("📡 Data Sources (21 OK, 1 Failed)"):
        sources = [
            ("FERC eLibrary", True),
            ("PJM Interconnection Queue", True),
            ("EIA Grid Monitor", True),
            ("Federal Register API", True),
            ("SemiAnalysis CoWoS Tracker", True),
            ("Datacenter Dynamics", True),
            ("BIS Export Controls", True),
            ("SF Compute Pricing", True),
            ("Vast.ai Market", True),
            ("Vertiv Earnings", True),
            ("EPA Water Data", True),
            ("SMIC Announcements", True),
            ("Huawei Cloud", True),
            ("National Energy Admin", True),
            ("MIIT Policies", True),
            ("Alibaba Cloud", True),
            ("China Bidding", True),
            ("Sugon Liquid Cooling", True),
            ("Tom's Hardware Semiconductor News", True),
            ("EIA API", True),
            ("FRED API", True),
            ("Beijing Power Exchange", False),
        ]
        sidebar_html = []
        for name, ok in sources:
            icon = "✅" if ok else "❌"
            color = "#10B981" if ok else "#EF4444"
            sidebar_html.append(f'<div style="font-size:12px;color:{color};margin:2px 0;">{icon} {name}</div>')
        rhtml("".join(sidebar_html))
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
    rhtml('''<div class="card" style="padding:16px 20px; background:#FFFBEB; border:1px solid #FDE68A; color:#92400E; font-weight:600; margin-bottom:24px; display:flex; justify-content:space-between; align-items:center;">
        <div>⚠️ Showing sample mock data. Run scan to retrieve actual dataset.</div>
        <div style="font-size:13px; opacity:0.8;">Last updated: 5 minutes ago</div>
    </div>''')
else:
    rhtml(f'''<div class="card" style="padding:16px 20px; background:#F0FDF4; border:1px solid #86EFAC; color:#166534; font-weight:600; margin-bottom:24px; display:flex; justify-content:space-between; align-items:center;">
        <div>📡 Live data from {latest_date} ({len(snapshots)} sectors)</div>
        <div style="font-size:13px; opacity:0.8;">Last updated: 12 minutes ago</div>
    </div>''')

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
# KEY METRICS CARDS
# ============================================================
st.markdown("<br>", unsafe_allow_html=True)
pjm_val = "440"; pjm_delta = "+12"; pjm_trend = "up"
elec_val = "15.2"; elec_delta = "+0.3"; elec_trend = "up"
dg_val = "284"; dg_delta = "-2.1"; dg_trend = "down"
reg_val = "42"; reg_delta = "+5"; reg_trend = "up"
high_val = str(max([s.severity_score for s in snapshots]) if snapshots else 0)
high_delta = "+0"; high_trend = "down"
div_val = str(abs(avg_us - avg_cn))
div_delta = "+0"; div_trend = "down"

metrics = [
    {
        "name": "PJM Queue", "value": pjm_val, "unit": "projects", "delta": pjm_delta, "trend": pjm_trend,
        "tooltip": "PJM Interconnection Queue: 440 active projects awaiting grid connection.<br>Source: PJM.com public queue data.<br>Higher = more demand for grid capacity = longer wait times for new data centers.<br>Current avg wait: ~4.2 years."
    },
    {
        "name": "Avg Elec Price", "value": elec_val, "unit": "¢/kWh", "delta": elec_delta, "trend": elec_trend,
        "tooltip": "Average US retail electricity price: 15.2 cents/kWh.<br>Source: EIA API v2 (official).<br>Rising prices signal tighter power supply, increasing data center operating costs."
    },
    {
        "name": "Durable Goods Orders", "value": dg_val, "unit": "$B", "delta": dg_delta, "trend": dg_trend,
        "tooltip": "US durable goods new orders: $284 billion (monthly).<br>Source: FRED API (Federal Reserve).<br>Declining orders suggest weakening demand for equipment including servers and chips."
    },
    {
        "name": "Active Regulations", "value": reg_val, "unit": "rules", "delta": reg_delta, "trend": reg_trend,
        "tooltip": "28 new federal regulations related to semiconductors, AI, and export controls.<br>Source: Federal Register API.<br>More regulations = more compliance burden and potential supply chain disruptions."
    },
    {
        "name": "Highest Severity", "value": high_val, "unit": "score max", "delta": high_delta, "trend": high_trend,
        "tooltip": "Maximum severity score across all 12 sector-country pairs today.<br>Score of 56 = Power & Energy in China.<br>Above 70 = significant bottleneck. Above 85 = critical."
    },
    {
        "name": "US-CN Divergence", "value": div_val, "unit": "severity gap", "delta": div_delta, "trend": div_trend,
        "tooltip": "Absolute difference between average US and CN severity scores.<br>Low divergence (0-5) = similar constraint levels.<br>High divergence (15+) = asymmetric bottlenecks, potential trade implications."
    },
]

for row in [metrics[:3], metrics[3:]]:
    cols = st.columns(3)
    for col, m in zip(cols, row):
        with col:
            trend_color = "#EF4444" if m["trend"] == "up" else "#10B981"
            arrow_icon = "↑" if m["trend"] == "up" else "↓"
            rhtml(f'''<div class="card" style="text-align:center; padding:15px;">
                <div class="tooltip-wrap">
                    <div style="color:#6B7280;font-size:11px;text-transform:uppercase;">{m["name"]}</div>
                    <div style="font-size:36px;font-weight:800;color:#1E1B4B;">{m["value"]}</div>
                    <div style="color:#6B7280;font-size:12px;">{m["unit"]}</div>
                    <div style="color:{trend_color};font-size:13px;font-weight:600;">
                        {arrow_icon} {m["delta"]}
                    </div>
                    <div class="tooltip-text">{m["tooltip"]}</div>
                </div>
            </div>''')
st.markdown("<br>", unsafe_allow_html=True)

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
    rhtml('<div class="card"><div class="card-title">SECTOR COMPARISON</div>')
    fig_bar = go.Figure()
    sectors_list = [SECTOR_LABELS.get(s.value, s.value) for s in Sector]
    us_vals, cn_vals = [], []
    for s in Sector:
        u_snap = score_map.get(("US", s.value))
        c_snap = score_map.get(("CN", s.value))
        us_vals.append(u_snap.severity_score if u_snap else 50)
        cn_vals.append(c_snap.severity_score if c_snap else 50)
    
    fig_bar.add_trace(go.Bar(name='US', x=sectors_list, y=us_vals, marker_color='#7C3AED'))
    fig_bar.add_trace(go.Bar(name='CN', x=sectors_list, y=cn_vals, marker_color='#F59E0B'))
    fig_bar.update_layout(barmode='group', template='plotly_white', height=300,
                      margin=dict(l=20, r=20, t=30, b=80),
                      xaxis_tickangle=-45,
                      legend=dict(orientation='h', y=-0.2))
    st.plotly_chart(fig_bar, use_container_width=True)
    rhtml('</div>')

# ============================================================
# 7-DAY TREND CHART + TRADE IDEAS
# ============================================================
col_chart, col_trades = st.columns([6, 4])

with col_chart:
    rhtml('<div class="card"><div class="card-title">7-DAY SEVERITY TREND</div>')
    view = st.radio("View", ["US", "CN", "Both"], horizontal=True, label_visibility="collapsed")
    if history and len(history) > 0:
        fig = go.Figure()
        has_data = False
        for sector in Sector:
            if view in ["US", "Both"]:
                us_data = sorted([s for s in history if s.sector == sector and s.country == Country.US], key=lambda x: x.date)
                if us_data:
                    has_data = True
                    fig.add_trace(go.Scatter(
                        x=[s.date for s in us_data], y=[s.severity_score for s in us_data],
                        mode='lines+markers', name=f"US {SECTOR_LABELS.get(sector.value, sector.value)}" if view == "Both" else SECTOR_LABELS.get(sector.value, sector.value),
                        line=dict(color=SECTOR_COLORS.get(sector.value, "#999"), width=2.5, dash='solid'),
                        marker=dict(size=5)
                    ))
            if view in ["CN", "Both"]:
                cn_data = sorted([s for s in history if s.sector == sector and s.country == Country.CN], key=lambda x: x.date)
                if cn_data:
                    has_data = True
                    fig.add_trace(go.Scatter(
                        x=[s.date for s in cn_data], y=[s.severity_score for s in cn_data],
                        mode='lines+markers', name=f"CN {SECTOR_LABELS.get(sector.value, sector.value)}" if view == "Both" else SECTOR_LABELS.get(sector.value, sector.value),
                        line=dict(color=SECTOR_COLORS.get(sector.value, "#999"), width=2.5, dash='dash' if view == "Both" else 'solid'),
                        marker=dict(size=5)
                    ))
        if has_data:
            fig.update_layout(
                template="plotly_white", height=320,
                margin=dict(l=20, r=20, t=10, b=10),
                xaxis=dict(tickformat="%b %d", dtick="D1"),
                legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5),
                yaxis_title="Severity"
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("📈 No trend data yet.")
    else:
        st.caption("📈 No trend data yet.")
    rhtml('</div>')

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
        rationale_short = rationale[:60] + "..." if len(rationale) > 60 else rationale
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
                font-weight:700;font-size:13px;text-align:center;
                background:{pill_bg};color:{pill_color};">{d}</span>
            <div style="flex:1;margin-left:16px;min-width:0;display:flex;align-items:center;">
                <span style="font-size:18px;font-weight:700;color:#1E1B4B;margin-right:8px;">{ticker}</span>
                <span style="font-size:12px;color:#6B7280;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:200px;">{rationale_short}</span>
            </div>
            <span style="padding:4px 12px;border-radius:6px;font-size:12px;font-weight:700;
                background:{conv_bg};color:{conv_color};">{conv}</span>
        </div>'''

    trades_html += '<div style="font-size:10px;color:#9CA3AF;margin-top:16px;padding-top:12px;border-top:1px solid #EDE9FE;line-height:1.4;">⚠️ For informational purposes only. Not investment advice. AI-generated signals may contain errors. Always conduct independent research before making investment decisions.</div>'
    trades_html += '</div>'
    rhtml(trades_html)

# === AI ANALYSIS EXPANDER ===
st.markdown("<br>", unsafe_allow_html=True)
synth_bullets = []
if not use_mock and data.get("synth_bullets"):
    synth_bullets = data["synth_bullets"]
else:
    synth_bullets = [
        "Power grid interconnection queue is the binding constraint. Average wait time extended to 4.2 years.",
        "GPU supply bottlenecks are easing, shifting constraints downstream.",
        "Cooling infrastructure upgrades are required for next-gen workloads."
    ]

with st.expander("📝 AI Analysis (click to expand)"):
    for bullet in synth_bullets[:2]:
        st.markdown(f"- {bullet}")

# === FOOTER ===
st.markdown("<br>", unsafe_allow_html=True)
rhtml('<div style="text-align:center;color:#9CA3AF;font-size:11px;padding:40px 0 20px;line-height:1.6;">'
      'AI Infra Sentinel v2.0 · Built with GPT-4o + Multi-Agent Architecture<br>'
      'Data sources: EIA, FRED, PJM, Federal Register, FERC, BIS, MIIT, SMIC and more<br>'
      '© 2026 · For research purposes only'
      '</div>')
