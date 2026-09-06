// frontend/src/App.tsx
// Main dashboard: metrics strip, live WebSocket queue, Green/Yellow/Red lanes,
// evidence drill-down, and the threshold simulator.

import { useState, useEffect, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  listReturns, getReturn, getMetrics, getThresholdCurve, updateThresholds,
  recordOutcome, login, ReturnListItem, ReturnDetail,
} from "./api/client";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar,
} from "recharts";
import "./App.css";

const WS_URL = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws/returns";

function LoginScreen({ onLogin }: { onLogin: () => void }) {
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    try {
      await login(apiKey);
      onLogin();
    } catch {
      setError("Invalid API key. Check the key issued by scripts/bootstrap.py.");
    }
  }

  return (
    <div className="login-screen">
      <h1>🛡️ Return-Abuse Sentinel</h1>
      <p>Defense-only risk router — scores, routes, explains. Never auto-refunds or auto-denies.</p>
      <form onSubmit={handleSubmit}>
        <input
          type="password" placeholder="Paste your API key"
          value={apiKey} onChange={(e) => setApiKey(e.target.value)}
        />
        <button type="submit">Sign in</button>
      </form>
      {error && <p className="error">{error}</p>}
    </div>
  );
}

function MetricsStrip() {
  const { data, isError } = useQuery({ queryKey: ["metrics"], queryFn: getMetrics, retry: false });
  if (isError || !data) {
    return <div className="metrics-strip metrics-empty">Not enough labeled outcomes yet to compute live metrics — record some via the queue below.</div>;
  }
  return (
    <div className="metrics-strip">
      <div className="metric-card">
        <span className="metric-label">Loss prevented (est.)</span>
        <span className="metric-value">₹{data.loss_prevented_inr.toLocaleString()}</span>
      </div>
      <div className="metric-card">
        <span className="metric-label">Automation rate</span>
        <span className="metric-value">{data.automation_rate_pct}%</span>
      </div>
      <div className="metric-card">
        <span className="metric-label">Red-band precision</span>
        <span className="metric-value">{(data.precision_red * 100).toFixed(1)}%</span>
      </div>
      <div className="metric-card">
        <span className="metric-label">Overall recall</span>
        <span className="metric-value">{(data.recall_overall * 100).toFixed(1)}%</span>
      </div>
      <div className={`metric-card ${data.psi_alert ? "alert" : ""}`}>
        <span className="metric-label">Drift (PSI)</span>
        <span className="metric-value">{data.psi_score} {data.psi_alert ? "⚠️" : "✅"}</span>
      </div>
    </div>
  );
}

function EvidenceDrawer({ orderId, onClose }: { orderId: string; onClose: () => void }) {
  const { data } = useQuery({
    queryKey: ["return", orderId], queryFn: () => getReturn(orderId), enabled: !!orderId,
  });
  const queryClient = useQueryClient();

  async function handleOutcome(label: 0 | 1) {
    await recordOutcome(orderId, label);
    queryClient.invalidateQueries({ queryKey: ["returns"] });
    queryClient.invalidateQueries({ queryKey: ["metrics"] });
    onClose();
  }

  if (!data) return null;

  const contributions = data.evidence
    ? Object.entries(data.evidence.contributions)
        .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
        .slice(0, 8)
        .map(([feature, value]) => ({ feature, value: Math.round(value * 1000) / 10 }))
    : [];

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <button className="drawer-close" onClick={onClose}>✕</button>
        <h2>{data.order_id}</h2>
        <p className={`band-badge band-${data.band?.toLowerCase()}`}>{data.band} — {data.risk_score}/100</p>

        {contributions.length > 0 && (
          <>
            <h3>Feature contributions (SHAP waterfall)</h3>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={contributions} layout="vertical" margin={{ left: 60 }}>
                <XAxis type="number" unit="pp" />
                <YAxis type="category" dataKey="feature" width={150} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="value" fill="#6366f1" />
              </BarChart>
            </ResponsiveContainer>
          </>
        )}

        {data.evidence && (
          <>
            <h3>Why this was flagged</h3>
            <ul>{data.evidence.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
          </>
        )}

        <h3>Recommended action</h3>
        <p className="recommended-action">{data.recommended_action}</p>

        <div className="outcome-buttons">
          <p>Human reviewer: confirm the true outcome (feeds the retraining pipeline)</p>
          <button className="btn-legit" onClick={() => handleOutcome(0)}>Mark: Legitimate</button>
          <button className="btn-fraud" onClick={() => handleOutcome(1)}>Mark: Confirmed abuse</button>
        </div>
      </div>
    </div>
  );
}

function ThresholdSimulator() {
  const { data } = useQuery({ queryKey: ["threshold-curve"], queryFn: getThresholdCurve, retry: false });
  const [applying, setApplying] = useState(false);

  if (!data || data.length === 0) {
    return <div className="panel">Threshold simulator needs at least 30 labeled outcomes to run.</div>;
  }

  async function applyPoint(green: number, red: number) {
    setApplying(true);
    await updateThresholds(green, red);
    setApplying(false);
    alert(`Applied thresholds: Green<${green}, Red>=${red}`);
  }

  return (
    <div className="panel">
      <h3>Threshold simulator — automation rate vs. loss reduction</h3>
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="target_automation_rate" unit="%" label={{ value: "Automation rate", position: "insideBottom", offset: -5 }} />
          <YAxis unit="%" label={{ value: "Loss reduction", angle: -90, position: "insideLeft" }} />
          <Tooltip />
          <Line type="monotone" dataKey="loss_reduction_pct" stroke="#6366f1" strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
      <table className="curve-table">
        <thead><tr><th>Automation</th><th>Loss reduction</th><th>Green_t</th><th>Red_t</th><th></th></tr></thead>
        <tbody>
          {data.map((row) => (
            <tr key={row.target_automation_rate}>
              <td>{row.actual_automation_rate}%</td>
              <td>{row.loss_reduction_pct}%</td>
              <td>{row.green_threshold}</td>
              <td>{row.red_threshold}</td>
              <td><button disabled={applying} onClick={() => applyPoint(row.green_threshold, row.red_threshold)}>Apply</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Queue() {
  const [band, setBand] = useState<string>("Red");
  const [selectedOrder, setSelectedOrder] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data } = useQuery({
    queryKey: ["returns", band],
    queryFn: () => listReturns({ band, page_size: 50 }),
  });

  useEffect(() => {
    const ws = new WebSocket(WS_URL);
    ws.onmessage = () => {
      queryClient.invalidateQueries({ queryKey: ["returns"] });
      queryClient.invalidateQueries({ queryKey: ["metrics"] });
    };
    const keepAlive = setInterval(() => ws.readyState === 1 && ws.send("ping"), 20000);
    return () => { clearInterval(keepAlive); ws.close(); };
  }, [queryClient]);

  return (
    <div className="panel">
      <div className="tabs">
        {["Green", "Yellow", "Red"].map((b) => (
          <button key={b} className={`tab tab-${b.toLowerCase()} ${band === b ? "active" : ""}`}
                  onClick={() => setBand(b)}>
            {b === "Green" ? "🟢" : b === "Yellow" ? "🟡" : "🔴"} {b}
          </button>
        ))}
      </div>
      <table className="queue-table">
        <thead><tr><th>Order</th><th>Score</th><th>Value</th><th>Category</th><th>Status</th></tr></thead>
        <tbody>
          {data?.items.map((item: ReturnListItem) => (
            <tr key={item.order_id} onClick={() => setSelectedOrder(item.order_id)} className="clickable-row">
              <td>{item.order_id}</td>
              <td>{item.risk_score ? (item.risk_score * 100).toFixed(1) : "-"}</td>
              <td>₹{item.order_value.toLocaleString()}</td>
              <td>{item.category}</td>
              <td>{item.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {selectedOrder && <EvidenceDrawer orderId={selectedOrder} onClose={() => setSelectedOrder(null)} />}
    </div>
  );
}

export default function App() {
  const [loggedIn, setLoggedIn] = useState(!!localStorage.getItem("sentinel_token"));

  if (!loggedIn) return <LoginScreen onLogin={() => setLoggedIn(true)} />;

  return (
    <div className="app">
      <header>
        <h1>🛡️ Return-Abuse Sentinel</h1>
        <p className="tagline">Defense-only. Scores, routes, explains. Never auto-refunds or auto-denies.</p>
      </header>
      <MetricsStrip />
      <Queue />
      <ThresholdSimulator />
    </div>
  );
}
