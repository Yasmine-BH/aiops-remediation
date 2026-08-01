from flask import Flask, jsonify, render_template_string
import pandas as pd
import os
import json
import time

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CPU_CSV = os.path.join(BASE_DIR, "cpu_metrics_log.csv")
SERVICE_CSV = os.path.join(BASE_DIR, "service_metrics_log.csv")
INCIDENTS_LOG = os.path.join(BASE_DIR, "incidents_log.jsonl")
MODEL_FILE = os.path.join(BASE_DIR, "iso_forest_cpu.joblib")
RETRAIN_LOG = os.path.join(BASE_DIR, "retrain.log")

MAX_POINTS = 200
MAX_INCIDENTS = 20
RECOVERY_CHECK_WINDOW = 120  # seconds after the incident to look at, wide enough to cover a full stress test
RECOVERY_TAIL_SECONDS = 20   # only judge recovery using the END of that window, not the whole thing


def safe_read_csv(path, n=MAX_POINTS):
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        return pd.read_csv(path).tail(n)
    except Exception:
        return pd.DataFrame()


def read_incidents():
    if not os.path.exists(INCIDENTS_LOG):
        return []
    records = []
    with open(INCIDENTS_LOG, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def determine_outcome(incident, cpu_full_df):
    """Did the situation actually recover after this incident? A naive
    average over the whole post-incident window is misleading: a real
    stress test can run for 50+ seconds AFTER the incident already
    fired (it needs ~10s of sustained high CPU just to cross the
    trigger threshold), so most of a short window would still be
    inside the active stress test, making genuine recoveries look
    "unresolved". Instead, we look at a wide window, but judge
    recovery using only its tail end — i.e. where things actually
    stand by the time the window closes."""
    if incident["source"] != "cpu" or cpu_full_df.empty:
        return "unknown"

    window_end = incident["timestamp"] + RECOVERY_CHECK_WINDOW
    tail_start = window_end - RECOVERY_TAIL_SECONDS

    full_window = cpu_full_df[
        (cpu_full_df["timestamp"] > incident["timestamp"]) &
        (cpu_full_df["timestamp"] <= window_end)
    ]
    if full_window.empty:
        return "pending"  # not enough time has passed yet to know

    # If we don't have data reaching all the way to the tail portion
    # yet, the full recovery window hasn't elapsed — still pending.
    latest_reading_time = full_window["timestamp"].max()
    if latest_reading_time < tail_start:
        return "pending"

    tail = full_window[full_window["timestamp"] >= tail_start]
    if tail.empty:
        return "pending"

    avg_cpu_tail = tail["cpu_percent"].mean()
    return "resolved" if avg_cpu_tail < 50 else "unresolved"


@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/data")
def api_data():
    cpu_df = safe_read_csv(CPU_CSV)
    service_df = safe_read_csv(SERVICE_CSV)

    cpu_data = {"timestamps": [], "cpu_percent": [], "mem_percent": [], "load_avg_1min": []}
    latest_cpu = {"cpu_percent": None, "mem_percent": None, "load_avg_1min": None}
    cpu_active_incident = False

    if not cpu_df.empty:
        cpu_data["timestamps"] = cpu_df["timestamp"].tolist()
        cpu_data["cpu_percent"] = cpu_df["cpu_percent"].tolist()
        cpu_data["mem_percent"] = cpu_df["mem_percent"].tolist()
        cpu_data["load_avg_1min"] = cpu_df["load_avg_1min"].tolist()
        last_row = cpu_df.iloc[-1]
        latest_cpu = {
            "cpu_percent": float(last_row["cpu_percent"]),
            "mem_percent": float(last_row["mem_percent"]),
            "load_avg_1min": float(last_row["load_avg_1min"]),
        }
        cpu_active_incident = bool(last_row["is_incident"])

    service_status = {"status": "unknown", "responding": None, "response_time_ms": None}
    if not service_df.empty:
        last_service = service_df.iloc[-1]
        service_status = {
            "status": last_service["status"],
            "responding": bool(last_service["responding"]),
            "response_time_ms": last_service["response_time_ms"],
        }

    cpu_full_df = pd.read_csv(CPU_CSV) if os.path.exists(CPU_CSV) else pd.DataFrame()
    all_incidents = read_incidents()
    raw_incidents = sorted(all_incidents, key=lambda x: x["timestamp"], reverse=True)[:MAX_INCIDENTS]

    incident_stories = []
    for inc in raw_incidents:
        outcome = determine_outcome(inc, cpu_full_df)
        incident_stories.append({
            "time": time.strftime("%H:%M:%S", time.gmtime(inc["timestamp"])),
            "date": time.strftime("%Y-%m-%d", time.gmtime(inc["timestamp"])),
            "source": inc["source"],
            "type": inc["type"],
            "priority": inc.get("priority", "-"),
            "trigger_values": inc.get("trigger_values", {}),
            "ml_detected": inc.get("ml_detected", False),
            "root_cause": inc.get("root_cause"),
            "action_taken": inc.get("action_taken"),
            "dispatch_success": inc.get("dispatch_success"),
            "outcome": outcome,
        })

    cpu_incident_count = len([i for i in all_incidents if i["source"] == "cpu"])
    service_incident_count = len([i for i in all_incidents if i["source"] == "service"])
    resolved_count = len([s for s in incident_stories if s["outcome"] == "resolved"])
    unresolved_count = len([s for s in incident_stories if s["outcome"] == "unresolved"])

    apache_ok = service_status["status"] == "active" and service_status["responding"]
    overall_status = "operational"
    if not apache_ok:
        overall_status = "degraded"
    elif cpu_active_incident:
        overall_status = "elevated"

    model_info = {"exists": False, "last_modified": None}
    if os.path.exists(MODEL_FILE):
        model_info["exists"] = True
        model_info["last_modified"] = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(os.path.getmtime(MODEL_FILE)))

    last_retrain_metrics = None
    if os.path.exists(RETRAIN_LOG):
        try:
            with open(RETRAIN_LOG, "r") as f:
                lines = f.readlines()
            for line in reversed(lines):
                if "Precision" in line and "Recall" in line:
                    last_retrain_metrics = line.strip()
                    break
        except Exception:
            pass

    return jsonify({
        "overall_status": overall_status,
        "cpu": cpu_data,
        "latest_cpu": latest_cpu,
        "service_status": service_status,
        "cpu_incident_count": cpu_incident_count,
        "service_incident_count": service_incident_count,
        "resolved_count": resolved_count,
        "unresolved_count": unresolved_count,
        "incident_stories": incident_stories,
        "model_info": model_info,
        "last_retrain_metrics": last_retrain_metrics,
        "server_time": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
    })


DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AIOps - Sofiatech</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<style>
    :root {
        --bg: #090b11; --panel: #10141d; --panel-border: #1c212c; --grid-line: #171b24;
        --text: #e9ebf1; --text-dim: #7a8496; --text-faint: #454c5c;
        --signal: #5eead4; --ok: #34d399; --warn: #fbbf24; --bad: #f87171;
        --violet: #a78bfa; --orange: #fb923c;
    }
    * { box-sizing: border-box; }
    body {
        background: radial-gradient(ellipse 1200px 600px at 50% -10%, rgba(94,234,212,0.05), transparent), var(--bg);
        color: var(--text); font-family: 'Inter', sans-serif; margin: 0; padding: 0 32px 48px;
    }
    .topbar { display: flex; justify-content: space-between; align-items: center; padding: 26px 0 20px; }
    .wordmark { display: flex; align-items: baseline; gap: 11px; }
    .wordmark .brand { font-weight: 800; font-size: 17px; letter-spacing: -0.01em; }
    .wordmark .sub { font-size: 12px; color: var(--text-dim); letter-spacing: 0.06em; }
    .live-indicator { display: flex; align-items: center; gap: 9px; font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text-dim); }
    .pulse-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--ok); animation: pulse 1.8s infinite; }
    @keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(52,211,153,0.5);} 70% {box-shadow: 0 0 0 7px rgba(52,211,153,0);} 100% {box-shadow: 0 0 0 0 rgba(52,211,153,0);} }
    @media (prefers-reduced-motion: reduce) { .pulse-dot { animation: none; } }

    .status-hero {
        display: flex; align-items: center; justify-content: space-between;
        border: 1px solid var(--panel-border); border-radius: 10px; padding: 22px 26px; margin-bottom: 22px;
        background: linear-gradient(180deg, #0e1119, var(--panel)); position: relative; overflow: hidden;
    }
    .status-hero::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; background: var(--status-color, var(--ok)); }
    .status-hero .status-left { display: flex; align-items: center; gap: 16px; }
    .status-hero .status-dot { width: 12px; height: 12px; border-radius: 50%; background: var(--status-color, var(--ok)); box-shadow: 0 0 16px 2px var(--status-color, var(--ok)); }
    .status-hero .label { font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--text-dim); font-weight: 600; margin-bottom: 3px; }
    .status-hero .value { font-size: 22px; font-weight: 700; letter-spacing: -0.01em; }
    .status-hero .status-meta { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text-dim); text-align: right; }

    .vitals-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 14px; margin-bottom: 22px; }
    .vital { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 8px; padding: 16px 18px; }
    .vital .eyebrow { font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text-dim); margin-bottom: 8px; font-weight: 600; }
    .vital .readout { font-family: 'JetBrains Mono', monospace; font-size: 26px; font-weight: 600; color: var(--signal); line-height: 1; }
    .vital .readout.ok { color: var(--ok); } .vital .readout.bad { color: var(--bad); } .vital .readout.neutral { color: var(--text); }
    .vital .unit { font-size: 12px; color: var(--text-dim); margin-left: 3px; font-weight: 400; }

    .section-title {
        font-size: 12px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text-dim);
        font-weight: 700; margin: 32px 0 14px; display: flex; align-items: center; gap: 10px;
    }
    .section-title .count-pill {
        background: rgba(94,234,212,0.1); color: var(--signal); font-family: 'JetBrains Mono', monospace;
        font-size: 11px; padding: 2px 8px; border-radius: 10px; font-weight: 600;
    }

    .panels { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
    @media (max-width: 900px) { .panels { grid-template-columns: 1fr; } }
    .panel { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 8px; padding: 20px 22px; }
    .panel .panel-title { font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text-dim); font-weight: 600; margin-bottom: 16px; }
    canvas.main-chart { max-height: 210px; }

    .incident-card {
        background: var(--panel); border: 1px solid var(--panel-border); border-radius: 8px;
        padding: 18px 20px; margin-bottom: 12px; position: relative; overflow: hidden;
    }
    .incident-card::before { content: ''; position: absolute; top: 0; left: 0; bottom: 0; width: 3px; background: var(--card-accent, var(--bad)); }
    .incident-card .ic-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; flex-wrap: wrap; gap: 8px; }
    .incident-card .ic-title { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    .incident-card .ic-type { font-weight: 700; font-size: 14px; }
    .incident-card .ic-badge {
        font-family: 'JetBrains Mono', monospace; font-size: 10px; padding: 2px 8px; border-radius: 4px;
        font-weight: 700; letter-spacing: 0.03em; text-transform: uppercase;
    }
    .badge-resolved { background: rgba(52,211,153,0.12); color: var(--ok); }
    .badge-unresolved { background: rgba(248,113,113,0.12); color: var(--bad); }
    .badge-pending { background: rgba(251,191,36,0.12); color: var(--warn); }
    .badge-unknown { background: rgba(122,132,150,0.12); color: var(--text-dim); }
    .incident-card .ic-time { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text-faint); }

    .ic-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; }
    .ic-field .ic-label { font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-faint); font-weight: 600; margin-bottom: 4px; }
    .ic-field .ic-value { font-size: 13px; color: var(--text); line-height: 1.4; }
    .ic-field .ic-value.mono { font-family: 'JetBrains Mono', monospace; font-size: 12px; }
    .ml-tag { display: inline-block; font-size: 10px; padding: 1px 6px; border-radius: 3px; background: rgba(94,234,212,0.12); color: var(--signal); font-weight: 700; }
    .rule-tag { display: inline-block; font-size: 10px; padding: 1px 6px; border-radius: 3px; background: rgba(167,139,250,0.12); color: var(--violet); font-weight: 700; }

    .incident-empty { color: var(--text-faint); font-size: 13px; font-family: 'JetBrains Mono', monospace; padding: 40px 0; text-align: center; border: 1px dashed var(--panel-border); border-radius: 8px; }

    .footer-bar { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text-faint); padding-top: 18px; margin-top: 30px; border-top: 1px solid var(--panel-border); }
</style>
</head>
<body>

<div class="topbar">
    <div class="wordmark"><span class="brand">AIOPS</span><span class="sub">SOFIATECH · LIVE TELEMETRY</span></div>
    <div class="live-indicator"><span class="pulse-dot"></span><span id="server-time">--:--:--</span></div>
</div>

<div class="status-hero" id="status-hero">
    <div class="status-left">
        <div class="status-dot" id="status-dot"></div>
        <div><div class="label">System Status</div><div class="value" id="status-value">Loading</div></div>
    </div>
    <div class="status-meta" id="status-meta">--</div>
</div>

<div class="vitals-row">
    <div class="vital"><div class="eyebrow">CPU</div><div class="readout" id="cpu-value">--<span class="unit">%</span></div></div>
    <div class="vital"><div class="eyebrow">Memory</div><div class="readout" id="mem-value">--<span class="unit">%</span></div></div>
    <div class="vital"><div class="eyebrow">Load Avg</div><div class="readout" id="load-value">--</div></div>
    <div class="vital"><div class="eyebrow">Apache</div><div class="readout" id="apache-value">--</div></div>
    <div class="vital"><div class="eyebrow">Resolved</div><div class="readout ok neutral" id="resolved-value">--</div></div>
    <div class="vital"><div class="eyebrow">Unresolved</div><div class="readout neutral" id="unresolved-value">--</div></div>
</div>

<div class="panels">
    <div class="panel"><div class="panel-title">CPU Trace</div><canvas class="main-chart" id="cpuChart"></canvas></div>
    <div class="panel"><div class="panel-title">Memory &amp; Load Trace</div><canvas class="main-chart" id="memLoadChart"></canvas></div>
</div>

<div class="section-title">Incident Timeline <span class="count-pill" id="incident-total">0</span><span style="font-weight:400;text-transform:none;letter-spacing:0;color:var(--text-faint);font-size:11px;">total &middot; showing most recent 20</span></div>
<div id="incident-container"><div class="incident-empty">No incidents recorded yet</div></div>

<div class="footer-bar">
    <span id="model-info">Model: --</span>
    <span id="retrain-info">--</span>
</div>

<script>
    const gridColor = '#171b24';
    const textDim = '#7a8496';
    const monoFont = { family: 'JetBrains Mono', size: 10 };

    const cpuChart = new Chart(document.getElementById('cpuChart').getContext('2d'), {
        type: 'line',
        data: { labels: [], datasets: [{ data: [], borderColor: '#5eead4', borderWidth: 1.5, backgroundColor: 'rgba(94,234,212,0.07)', fill: true, tension: 0.3, pointRadius: 0 }]},
        options: { responsive: true, animation: false, plugins: { legend: { display: false } },
            scales: { x: { ticks: { color: textDim, maxTicksLimit: 6, font: monoFont }, grid: { color: gridColor } }, y: { min: 0, max: 100, ticks: { color: textDim, font: monoFont }, grid: { color: gridColor } } } }
    });

    const memLoadChart = new Chart(document.getElementById('memLoadChart').getContext('2d'), {
        type: 'line',
        data: { labels: [], datasets: [
            { label: 'MEM %', data: [], borderColor: '#a78bfa', borderWidth: 1.5, tension: 0.3, pointRadius: 0, yAxisID: 'y' },
            { label: 'LOAD', data: [], borderColor: '#fb923c', borderWidth: 1.5, tension: 0.3, pointRadius: 0, yAxisID: 'y1' }
        ]},
        options: { responsive: true, animation: false, plugins: { legend: { labels: { color: textDim, font: monoFont } } },
            scales: { x: { ticks: { color: textDim, maxTicksLimit: 6, font: monoFont }, grid: { color: gridColor } },
                y: { position: 'left', ticks: { color: textDim, font: monoFont }, grid: { color: gridColor } },
                y1: { position: 'right', ticks: { color: textDim, font: monoFont }, grid: { display: false } } } }
    });

    function fmtTime(ts) { return new Date(ts * 1000).toLocaleTimeString(); }

    const statusConfig = {
        operational: { color: '#34d399', label: 'Operational' },
        elevated:    { color: '#fbbf24', label: 'Elevated - CPU incident active' },
        degraded:    { color: '#f87171', label: 'Degraded - service down' },
    };
    const outcomeConfig = {
        resolved:   { badge: 'badge-resolved', accent: '#34d399', text: 'Resolved' },
        unresolved: { badge: 'badge-unresolved', accent: '#f87171', text: 'Unresolved' },
        pending:    { badge: 'badge-pending', accent: '#fbbf24', text: 'Pending' },
        unknown:    { badge: 'badge-unknown', accent: '#7a8496', text: 'Unknown' },
    };

    function renderIncidentCard(inc) {
        const oc = outcomeConfig[inc.outcome] || outcomeConfig.unknown;
        const detectTag = inc.ml_detected ? '<span class="ml-tag">ML DETECTED</span>' : '<span class="rule-tag">RULE-BASED</span>';
        const triggerStr = Object.entries(inc.trigger_values || {}).map(([k, v]) => k + '=' + v).join('  ');
        const dispatchStr = inc.dispatch_success ? 'Dispatched successfully (HTTP 204)' : 'Dispatch FAILED';
        let rootCauseStr = 'Not identified';
        if (inc.root_cause && typeof inc.root_cause === 'object') {
            rootCauseStr = inc.root_cause.name + ' (pid ' + inc.root_cause.pid + ', ' + inc.root_cause.cpu.toFixed(1) + '% cpu)';
        } else if (inc.root_cause) {
            rootCauseStr = inc.root_cause;
        }

        return '<div class="incident-card" style="--card-accent:' + oc.accent + '">' +
            '<div class="ic-header">' +
                '<div class="ic-title">' +
                    '<span class="ic-type">' + inc.type + '</span>' +
                    detectTag +
                    '<span class="ic-badge ' + oc.badge + '">' + oc.text + '</span>' +
                '</div>' +
                '<span class="ic-time">' + inc.date + ' ' + inc.time + '</span>' +
            '</div>' +
            '<div class="ic-grid">' +
                '<div class="ic-field"><div class="ic-label">What Happened</div><div class="ic-value mono">' + (triggerStr || '-') + '</div></div>' +
                '<div class="ic-field"><div class="ic-label">Why (Root Cause)</div><div class="ic-value">' + rootCauseStr + '</div></div>' +
                '<div class="ic-field"><div class="ic-label">Action Taken</div><div class="ic-value mono">' + (inc.action_taken || '-') + '</div></div>' +
                '<div class="ic-field"><div class="ic-label">Remediation Dispatch</div><div class="ic-value" style="color:' + (inc.dispatch_success ? '#34d399' : '#f87171') + '">' + dispatchStr + '</div></div>' +
            '</div>' +
        '</div>';
    }

    async function refresh() {
        try {
            const res = await fetch('/api/data');
            const data = await res.json();

            const cfg = statusConfig[data.overall_status] || statusConfig.operational;
            document.getElementById('status-hero').style.setProperty('--status-color', cfg.color);
            document.getElementById('status-dot').style.background = cfg.color;
            document.getElementById('status-dot').style.boxShadow = '0 0 16px 2px ' + cfg.color;
            document.getElementById('status-value').innerText = cfg.label;
            document.getElementById('status-meta').innerText = 'CPU ' + data.cpu_incident_count + ' incidents · SVC ' + data.service_incident_count + ' incidents';

            document.getElementById('cpu-value').innerHTML = (data.latest_cpu.cpu_percent !== null ? data.latest_cpu.cpu_percent.toFixed(1) : '--') + '<span class="unit">%</span>';
            document.getElementById('mem-value').innerHTML = (data.latest_cpu.mem_percent !== null ? data.latest_cpu.mem_percent.toFixed(1) : '--') + '<span class="unit">%</span>';
            document.getElementById('load-value').innerText = data.latest_cpu.load_avg_1min !== null ? data.latest_cpu.load_avg_1min.toFixed(2) : '--';

            const apacheEl = document.getElementById('apache-value');
            const isUp = data.service_status.status === 'active' && data.service_status.responding;
            apacheEl.innerText = isUp ? 'UP' : 'DOWN';
            apacheEl.className = 'readout ' + (isUp ? 'ok' : 'bad');

            document.getElementById('resolved-value').innerText = data.resolved_count;
            document.getElementById('unresolved-value').innerText = data.unresolved_count;
            document.getElementById('unresolved-value').className = 'readout ' + (data.unresolved_count > 0 ? 'bad' : 'neutral');

            document.getElementById('model-info').innerText = data.model_info.exists ? ('MODEL LOADED · UPDATED ' + data.model_info.last_modified) : 'MODEL NOT FOUND';
            document.getElementById('retrain-info').innerText = data.last_retrain_metrics || 'NO RETRAIN HISTORY';

            const labels = data.cpu.timestamps.map(fmtTime);
            cpuChart.data.labels = labels; cpuChart.data.datasets[0].data = data.cpu.cpu_percent; cpuChart.update();
            memLoadChart.data.labels = labels; memLoadChart.data.datasets[0].data = data.cpu.mem_percent; memLoadChart.data.datasets[1].data = data.cpu.load_avg_1min; memLoadChart.update();

            document.getElementById('incident-total').innerText = data.cpu_incident_count + data.service_incident_count;
            const container = document.getElementById('incident-container');
            container.innerHTML = data.incident_stories.length === 0
                ? '<div class="incident-empty">No incidents recorded yet</div>'
                : data.incident_stories.map(renderIncidentCard).join('');

            document.getElementById('server-time').innerText = data.server_time;
        } catch (e) {
            document.getElementById('server-time').innerText = 'connection lost';
        }
    }

    refresh();
    setInterval(refresh, 4000);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
