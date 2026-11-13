import type {UsageSummary,UsageEvent} from "./usage.js";
import {renderPage} from "./ui-shell.js";
import {Icon} from "./ui-icons.js";

export type UsagePageMetrics={
  summary:UsageSummary;
  recent:UsageEvent[];
};

const statusLabels:Record<UsageEvent["status"],string>={
  success:"Success",denied:"Denied",error:"Error"};

function formatDate(iso:string|null):string{
  if(!iso)return "—";
  return iso.slice(0,16).replace("T"," ")+" UTC";
}

export function renderUsagePage(
  metrics:UsagePageMetrics|null=null,userEmail?:string):string{
  if(!metrics){
    return renderPage({
      title:"Usage",
      kind:"usage",
      eyebrow:"Workspace / Usage",
      summary:"Observed MCP tool-call activity for your account.",
      userEmail,
      children:(
        <div className="page-stack usage-dashboard">
          <section className="card detail-card" aria-label="Usage data unavailable">
            <div className="notice-icon"><Icon name="usage" size={23}/></div>
            <h2>No tool-call activity recorded yet</h2>
            <p>Counts appear once AI clients make verified tool calls through
              this Cloud account. Nothing is estimated and no usage limit is
              implied.</p>
            <a className="button secondary" href="/devices">View connected devices</a>
          </section>
        </div>
      )
    });
  }
  const {summary,recent}=metrics;
  const maxDay=Math.max(1,...summary.byDay.map(d=>d.calls));
  const maxTool=Math.max(1,...summary.byTool.map(t=>t.count));
  return renderPage({
    title:"Usage",
    kind:"usage",
    eyebrow:"Workspace / Metrics & Activity",
    summary:"Observed MCP tool-call counts by tool, client and outcome. Observed counts only; nothing is estimated or promised.",
    userEmail,
    children:(
      <div className="page-stack usage-dashboard">
        <section className="card usage-banner" aria-label="Observed tool calls">
          <div className="usage-banner-content">
            <span className="banner-kicker">OBSERVED TOOL CALLS</span>
            <h2>{summary.totalCalls.toLocaleString()} calls recorded
              {" "}in the last {summary.windowDays} days</h2>
            <p>First observed {formatDate(summary.firstAt)} ·
              {" "}latest {formatDate(summary.lastAt)}</p>
          </div>
          <div className="usage-banner-badge">
            <span className="verified-badge">Measured, not estimated</span>
          </div>
        </section>

        <div className="usage-stats-grid">
          {summary.byStatus.length?summary.byStatus.map(entry=>(
            <section className="card stat-card" key={entry.status}
              aria-label={`${statusLabels[entry.status]} tool calls`}>
              <span className="card-kicker">{statusLabels[entry.status].toUpperCase()}</span>
              <div className="stat-hero">
                <span className="stat-value">{entry.count.toLocaleString()}</span>
              </div>
              <p className="stat-caption">of {summary.totalCalls.toLocaleString()} observed calls.</p>
            </section>
          )):null}
          {!summary.byStatus.length?(
            <section className="card stat-card" aria-label="No calls in window">
              <span className="card-kicker">NO CALLS IN WINDOW</span>
              <div className="stat-hero">
                <span className="stat-value">0</span>
              </div>
              <p className="stat-caption">Nothing was observed in the selected window.</p>
            </section>
          ):null}
        </div>

        <section className="card chart-card" aria-label="Calls over time">
          <div className="chart-header">
            <div>
              <span className="card-kicker">ACTIVITY TIMELINE</span>
              <h2>Calls per day</h2>
              <p className="chart-subtitle">Observed calls, grouped by day (UTC)</p>
            </div>
          </div>
          <div className="chart-container" aria-label="Bar chart of observed calls per day">
            <div className="chart-y-axis" aria-hidden="true">
              <span>{maxDay.toLocaleString()}</span>
              <span>{Math.round(maxDay/2).toLocaleString()}</span>
              <span>0</span>
            </div>
            <div className="chart-bars-wrap">
              <div className="chart-gridlines" aria-hidden="true">
                <div className="gridline"/><div className="gridline"/><div className="gridline"/>
              </div>
              <div className="chart-bars">
                {summary.byDay.map(item=>{
                  const height=item.calls>0?
                    Math.max(6,Math.round((item.calls/maxDay)*160)):3;
                  return (
                    <div className="chart-bar-col" key={item.day}>
                      <div className="bar-track">
                        <div className={item.calls>0?"bar-fill active":"bar-fill empty"}
                          style={{height:`${height}px`}}
                          title={`${item.day}: ${item.calls.toLocaleString()} calls`}/>
                      </div>
                      <span className="bar-label">{item.day.slice(5)}</span>
                    </div>
                  );
                })}
                {!summary.byDay.length?(
                  <div className="chart-bar-col"><div className="bar-track">
                    <div className="bar-fill empty" style={{height:"3px"}}/></div>
                    <span className="bar-label">—</span></div>
                ):null}
              </div>
            </div>
          </div>
        </section>

        <div className="usage-details-grid">
          <section className="card detail-card" aria-label="Tool breakdown">
            <span className="card-kicker">TOOL BREAKDOWN</span>
            <h2>Most used tools</h2>
            <p className="section-description">Observed counts per MCP tool across all connected AI clients.</p>
            <ul className="tool-breakdown-list">
              {summary.byTool.map(item=>(
                <li className="breakdown-item" key={item.tool}>
                  <div className="breakdown-row">
                    <code>{item.tool}</code>
                    <span className="breakdown-count">{item.count} calls</span>
                  </div>
                  <div className="breakdown-bar">
                    <div className="breakdown-fill"
                      style={{width:`${Math.max(2,Math.round((item.count/maxTool)*100))}%`}}/>
                  </div>
                </li>
              ))}
              {!summary.byTool.length?<li className="breakdown-item">
                <span className="breakdown-count">No tool calls in this window.</span>
              </li>:null}
            </ul>
          </section>

          <section className="card detail-card" aria-label="Client breakdown">
            <span className="card-kicker">CLIENT BREAKDOWN</span>
            <h2>Calls by AI client</h2>
            <p className="section-description">Observed counts per OAuth client identity.</p>
            <ul className="tool-breakdown-list">
              {summary.byClient.map(item=>(
                <li className="breakdown-item" key={item.clientId}>
                  <div className="breakdown-row">
                    <code>{item.clientId}</code>
                    <span className="breakdown-count">{item.count} calls</span>
                  </div>
                  <div className="breakdown-bar">
                    <div className="breakdown-fill"
                      style={{width:`${Math.max(2,Math.round((item.count/Math.max(...summary.byClient.map(c=>c.count)))*100))}%`}}/>
                  </div>
                </li>
              ))}
              {!summary.byClient.length?<li className="breakdown-item">
                <span className="breakdown-count">No client activity in this window.</span>
              </li>:null}
            </ul>
          </section>
        </div>

        <section className="card detail-card" aria-label="Recent activity">
          <span className="card-kicker">RECENT ACTIVITY</span>
          <h2>Latest tool calls</h2>
          <p className="section-description">Newest observed calls, newest first.</p>
          <ul className="activity-list">
            {recent.map(act=>(
              <li className="activity-item" key={act.id}>
                <div className="activity-meta">
                  <span className="activity-client"><Icon name="connections" size={14}/> {act.clientId}</span>
                  <span className="activity-time">{act.at.slice(0,19).replace("T"," ")} UTC</span>
                </div>
                <div className="activity-tool">
                  <code>{act.tool}</code>
                  <span className={"status-pill "+(act.status==="success"?"ready":"pending")}>
                    {act.status==="success"?<Icon name="check" size={12}/>:<Icon name="warning" size={12}/>}
                    {" "}{statusLabels[act.status]}
                  </span>
                </div>
              </li>
            ))}
            {!recent.length?<li className="activity-item">
              <span className="activity-time">No recorded calls in this window.</span>
            </li>:null}
          </ul>
        </section>
      </div>
    )
  });
}
