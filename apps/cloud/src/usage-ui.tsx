import {renderPage} from "./ui-shell.js";
import {Icon} from "./ui-icons.js";

export type UsageMetrics = {
  totalCallsThisMonth: number;
  monthlyQuota: number;
  dailyAverage: number;
  daysRemainingInMonth: number;
  resetDateLabel: string;
  monthlyHistory: Array<{month: string; calls: number}>;
  toolBreakdown: Array<{name: string; count: number; percentage: number}>;
  recentActivity: Array<{
    id: string;
    toolName: string;
    clientName: string;
    timestamp: string;
    status: "success" | "denied" | "pending";
  }>;
};

export const defaultMetrics: UsageMetrics = {
  totalCallsThisMonth: 473,
  monthlyQuota: 10000,
  dailyAverage: 47,
  daysRemainingInMonth: 21,
  resetDateLabel: "1st of next month",
  monthlyHistory: [
    {month: "Jun", calls: 0},
    {month: "Jul", calls: 0},
    {month: "Aug", calls: 0},
    {month: "Sep", calls: 7850},
    {month: "Oct", calls: 0},
    {month: "Nov", calls: 473}
  ],
  toolBreakdown: [
    {name: "project_summary", count: 322, percentage: 68},
    {name: "list_projects", count: 85, percentage: 18},
    {name: "get_project", count: 48, percentage: 10},
    {name: "list_devices", count: 18, percentage: 4}
  ],
  recentActivity: [
    {id: "act-1", toolName: "project_summary", clientName: "ChatGPT", timestamp: "Today, 16:42", status: "success"},
    {id: "act-2", toolName: "list_projects", clientName: "ChatGPT", timestamp: "Today, 16:40", status: "success"},
    {id: "act-3", toolName: "get_project", clientName: "ChatGPT", timestamp: "Today, 15:18", status: "success"},
    {id: "act-4", toolName: "project_summary", clientName: "Claude", timestamp: "Yesterday, 19:05", status: "success"},
    {id: "act-5", toolName: "list_devices", clientName: "ChatGPT", timestamp: "Yesterday, 14:22", status: "success"}
  ]
};

export function renderUsagePage(metrics: UsageMetrics = defaultMetrics, userEmail?: string): string {
  const remaining = Math.max(0, metrics.monthlyQuota - metrics.totalCallsThisMonth);
  const percentage = Math.min(100, Math.round((metrics.totalCallsThisMonth / metrics.monthlyQuota) * 100));
  const maxCalls = Math.max(...metrics.monthlyHistory.map(h => h.calls), 10000);

  return renderPage({
    title: "Usage",
    kind: "account",
    eyebrow: "Workspace / Metrics & Activity",
    summary: "Real-time usage statistics and MCP tool call telemetry for your account.",
    userEmail,
    children: (
      <div className="page-stack usage-dashboard">
        {/* Top Allowance Banner */}
        <section className="card usage-banner" aria-label="Monthly allowance">
          <div className="usage-banner-content">
            <span className="banner-kicker">MONTHLY ALLOWANCE</span>
            <h2>{remaining.toLocaleString()} tool calls left this month</h2>
            <p>Resets on {metrics.resetDateLabel} · Standard Developer Plan active.</p>
          </div>
          <div className="usage-banner-badge">
            <span className="plan-badge"><Icon name="spark" size={14}/> Active Plan</span>
          </div>
        </section>

        {/* 2 Key Stat Cards Side-by-Side */}
        <div className="usage-stats-grid">
          <section className="card stat-card" aria-label="Tool calls this month">
            <span className="card-kicker">TOOL CALLS THIS MONTH</span>
            <div className="stat-hero">
              <span className="stat-value">{metrics.totalCallsThisMonth.toLocaleString()}</span>
              <span className="stat-total"> / {metrics.monthlyQuota.toLocaleString()}</span>
            </div>
            <div className="stat-progress-bar" role="progressbar" aria-valuenow={percentage} aria-valuemin={0} aria-valuemax={100}>
              <div className="stat-progress-fill" style={{width: `${percentage}%`}}/>
            </div>
            <div className="stat-subtext">
              <span>{percentage}% used</span>
              <span>·</span>
              <span>Resets on {metrics.resetDateLabel}, in {metrics.daysRemainingInMonth} days</span>
            </div>
          </section>

          <section className="card stat-card" aria-label="Daily average">
            <span className="card-kicker">DAILY AVERAGE</span>
            <div className="stat-hero">
              <span className="stat-value">{metrics.dailyAverage}</span>
            </div>
            <p className="stat-caption">Calls so far this month ÷ days elapsed.</p>
          </section>
        </div>

        {/* Calls Over Time Chart */}
        <section className="card chart-card" aria-label="Calls over time">
          <div className="chart-header">
            <div>
              <span className="card-kicker">ACTIVITY TIMELINE</span>
              <h2>Calls over time</h2>
              <p className="chart-subtitle">Last 6 months, grouped by month</p>
            </div>
          </div>
          <div className="chart-container" aria-label="Bar chart showing calls over the last 6 months">
            <div className="chart-y-axis" aria-hidden="true">
              <span>10.000</span>
              <span>5.000</span>
              <span>0</span>
            </div>
            <div className="chart-bars-wrap">
              <div className="chart-gridlines" aria-hidden="true">
                <div className="gridline"/>
                <div className="gridline"/>
                <div className="gridline"/>
              </div>
              <div className="chart-bars">
                {metrics.monthlyHistory.map(item => {
                  const barHeight = item.calls > 0 ? Math.max(6, Math.round((item.calls / maxCalls) * 160)) : 3;
                  return (
                    <div className="chart-bar-col" key={item.month}>
                      <div className="bar-track">
                        <div
                          className={item.calls > 0 ? "bar-fill active" : "bar-fill empty"}
                          style={{height: `${barHeight}px`}}
                          title={`${item.month}: ${item.calls.toLocaleString()} calls`}
                        />
                      </div>
                      <span className="bar-label">{item.month}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </section>

        {/* 2-Column: Tool Breakdown & Recent Activity */}
        <div className="usage-details-grid">
          <section className="card detail-card" aria-label="Tool breakdown">
            <span className="card-kicker">TOOL USAGE BREAKDOWN</span>
            <h2>Most used tools</h2>
            <p className="section-description">Distribution of MCP operations executed across all connected AI clients.</p>
            <ul className="tool-breakdown-list">
              {metrics.toolBreakdown.map(item => (
                <li className="breakdown-item" key={item.name}>
                  <div className="breakdown-row">
                    <code>{item.name}</code>
                    <span className="breakdown-count">{item.count} calls ({item.percentage}%)</span>
                  </div>
                  <div className="breakdown-bar">
                    <div className="breakdown-fill" style={{width: `${item.percentage}%`}}/>
                  </div>
                </li>
              ))}
            </ul>
          </section>

          <section className="card detail-card" aria-label="Recent activity">
            <span className="card-kicker">SESSION TELEMETRY</span>
            <h2>Recent MCP activity</h2>
            <p className="section-description">Authenticated tool call audit log.</p>
            <ul className="activity-list">
              {metrics.recentActivity.map(act => (
                <li className="activity-item" key={act.id}>
                  <div className="activity-meta">
                    <span className="activity-client"><Icon name="connections" size={14}/> {act.clientName}</span>
                    <span className="activity-time">{act.timestamp}</span>
                  </div>
                  <div className="activity-tool">
                    <code>{act.toolName}</code>
                    <span className="status-pill ready"><Icon name="check" size={12}/> Success</span>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        </div>
      </div>
    )
  });
}
