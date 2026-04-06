import csv
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from config import APP_CONFIG


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = DATA_DIR / "results"
DASHBOARD_STATE_FILE = BASE_DIR / APP_CONFIG.monitoring.dashboard_state_file

TRADE_EVENT_FILES = [
    RESULTS_DIR / "trade_events_sell.csv",
    RESULTS_DIR / "trade_events_buy.csv",
]
SUMMARY_FILES = {
    "daily_sell": RESULTS_DIR / "daily_summary.csv",
    "daily_buy": RESULTS_DIR / "daily_summary_buy.csv",
    "daily_combined": RESULTS_DIR / "daily_summary_combined.csv",
    "trade_sell": RESULTS_DIR / "trade_summary.csv",
    "trade_buy": RESULTS_DIR / "trade_summary_buy.csv",
    "trade_combined": RESULTS_DIR / "trade_summary_combined.csv",
}


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def load_csv_rows(path: Path):
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def load_recent_trade_events(limit: int | None = None):
    rows = []
    for path in TRADE_EVENT_FILES:
        rows.extend(load_csv_rows(path))

    rows.sort(
        key=lambda row: (row.get("exit_time", ""), row.get("entry_time", ""), row.get("trade_id", "")),
        reverse=True,
    )
    if limit is None:
        return rows
    return rows[:limit]


def load_summaries():
    return {
        key: load_csv_rows(path)
        for key, path in SUMMARY_FILES.items()
    }


def render_index():
    return """<!DOCTYPE html>
<html>
<head>
  <title>NIFTY Monitor</title>
  <link rel="icon" href="/static/favicon.ico" />
  <link rel="shortcut icon" href="/static/favicon.ico" />
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root {
      --bg: #f4f1e8;
      --panel: rgba(255, 252, 246, 0.92);
      --panel-strong: #fffdfa;
      --ink: #182126;
      --muted: #5f6c72;
      --line: rgba(24, 33, 38, 0.12);
      --green: #1d7a4a;
      --green-soft: rgba(29, 122, 74, 0.12);
      --red: #b14332;
      --red-soft: rgba(177, 67, 50, 0.12);
      --amber: #9b6a11;
      --amber-soft: rgba(155, 106, 17, 0.14);
      --blue: #215d7a;
      --blue-soft: rgba(33, 93, 122, 0.12);
      --shadow: 0 18px 40px rgba(48, 39, 28, 0.10);
      --radius: 20px;
      --mono: "SFMono-Regular", Consolas, monospace;
      --serif: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
      --sans: "Avenir Next", "Segoe UI", sans-serif;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      color: var(--ink);
      font-family: var(--sans);
      background:
        radial-gradient(circle at top left, rgba(33, 93, 122, 0.18), transparent 24%),
        radial-gradient(circle at top right, rgba(29, 122, 74, 0.14), transparent 28%),
        linear-gradient(180deg, #fbf7ef 0%, var(--bg) 100%);
    }

    .page {
      max-width: 1380px;
      margin: 0 auto;
      padding: 28px 18px 40px;
    }

    .hero {
      display: grid;
      grid-template-columns: minmax(0, 1.6fr) minmax(280px, 0.8fr);
      gap: 18px;
      margin-bottom: 18px;
    }

    .hero-card,
    .panel,
    .metric-card,
    .side-card,
    .position-card,
    .insight-card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      backdrop-filter: blur(8px);
    }

    .hero-card {
      padding: 24px;
    }

    .hero h1 {
      margin: 0 0 8px;
      font-family: var(--serif);
      font-size: clamp(2rem, 3vw, 3.2rem);
      line-height: 1;
      letter-spacing: -0.03em;
    }

    .hero p {
      margin: 0;
      color: var(--muted);
      max-width: 70ch;
      font-size: 0.98rem;
    }

    .hero-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 18px;
    }

    .chip {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.7);
      border: 1px solid var(--line);
      color: var(--ink);
      font-size: 0.86rem;
      white-space: nowrap;
    }

    .dot {
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: var(--amber);
      box-shadow: 0 0 0 4px var(--amber-soft);
      flex: none;
    }

    .dot.ok {
      background: var(--green);
      box-shadow: 0 0 0 4px var(--green-soft);
    }

    .dot.bad {
      background: var(--red);
      box-shadow: 0 0 0 4px var(--red-soft);
    }

    .hero-aside {
      padding: 24px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      gap: 18px;
    }

    .eyebrow {
      margin: 0 0 8px;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-size: 0.72rem;
      color: var(--muted);
      font-weight: 700;
    }

    .hero-number {
      font-size: clamp(2rem, 3vw, 2.8rem);
      line-height: 1;
      font-weight: 800;
      margin: 0;
      font-family: var(--serif);
    }

    .hero-caption {
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 0.92rem;
    }

    .grid-4,
    .grid-2,
    .side-grid,
    .position-grid,
    .insights-grid {
      display: grid;
      gap: 18px;
      margin-bottom: 18px;
    }

    .grid-4 {
      grid-template-columns: repeat(4, minmax(0, 1fr));
    }

    .grid-2,
    .side-grid,
    .position-grid,
    .insights-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .metric-card,
    .side-card,
    .position-card,
    .insight-card,
    .panel {
      padding: 18px 20px;
    }

    .metric-label,
    .section-label {
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 0.74rem;
      margin-bottom: 10px;
      font-weight: 700;
    }

    .metric-value {
      font-size: 2rem;
      line-height: 1;
      font-weight: 800;
      margin: 0 0 8px;
      font-family: var(--serif);
    }

    .metric-subtext {
      color: var(--muted);
      font-size: 0.93rem;
    }

    .positive { color: var(--green); }
    .negative { color: var(--red); }
    .neutral { color: var(--amber); }

    .side-card {
      position: relative;
      overflow: hidden;
    }

    .side-card::after {
      content: "";
      position: absolute;
      inset: auto -30px -30px auto;
      width: 130px;
      height: 130px;
      border-radius: 50%;
      opacity: 0.6;
      pointer-events: none;
    }

    .side-card.sell::after { background: var(--blue-soft); }
    .side-card.buy::after { background: var(--green-soft); }

    .side-header {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 14px;
      margin-bottom: 14px;
    }

    .side-title {
      margin: 0;
      font-size: 1.28rem;
      font-family: var(--serif);
    }

    .state-pill {
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 0.8rem;
      font-weight: 700;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.68);
    }

    .stats-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }

    .stat {
      padding: 12px;
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.72);
      border: 1px solid var(--line);
    }

    .stat-label {
      font-size: 0.76rem;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 4px;
      font-weight: 700;
    }

    .stat-value {
      font-size: 1.18rem;
      font-weight: 800;
      line-height: 1.15;
    }

    .section-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
      margin-bottom: 14px;
    }

    .section-header h2 {
      margin: 0;
      font-size: 1.18rem;
      font-family: var(--serif);
    }

    .mini-note {
      color: var(--muted);
      font-size: 0.88rem;
    }

    .position-card.empty {
      background: rgba(255, 252, 246, 0.55);
    }

    .position-title {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      margin-bottom: 14px;
    }

    .position-title h3 {
      margin: 0;
      font-size: 1.08rem;
    }

    .position-grid-lines {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }

    .line-label {
      font-size: 0.75rem;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 4px;
      font-weight: 700;
    }

    .line-value {
      font-size: 0.97rem;
      font-weight: 700;
    }

    .legs {
      margin-top: 14px;
      padding-top: 14px;
      border-top: 1px solid var(--line);
      color: var(--muted);
      font-size: 0.9rem;
      line-height: 1.5;
    }

    .table-wrap {
      overflow-x: auto;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 720px;
      font-size: 0.92rem;
    }

    th, td {
      padding: 12px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }

    th {
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 0.74rem;
      font-weight: 800;
      background: rgba(255, 255, 255, 0.58);
      position: sticky;
      top: 0;
    }

    tbody tr:hover {
      background: rgba(255, 255, 255, 0.54);
    }

    .mono {
      font-family: var(--mono);
    }

    .alerts {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }

    .alert-pill {
      padding: 10px 12px;
      border-radius: 14px;
      font-size: 0.92rem;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.72);
    }

    .alert-pill.ok {
      color: var(--green);
      background: var(--green-soft);
      border-color: rgba(29, 122, 74, 0.18);
    }

    .alert-pill.warn {
      color: var(--amber);
      background: var(--amber-soft);
      border-color: rgba(155, 106, 17, 0.18);
    }

    .alert-pill.bad {
      color: var(--red);
      background: var(--red-soft);
      border-color: rgba(177, 67, 50, 0.2);
    }

    @media (max-width: 1080px) {
      .hero,
      .grid-4,
      .grid-2,
      .side-grid,
      .position-grid,
      .insights-grid {
        grid-template-columns: 1fr;
      }
    }

    @media (max-width: 720px) {
      .page {
        padding: 16px 12px 28px;
      }

      .hero-card,
      .hero-aside,
      .metric-card,
      .side-card,
      .position-card,
      .insight-card,
      .panel {
        padding: 16px;
        border-radius: 16px;
      }

      .stats-grid,
      .position-grid-lines {
        grid-template-columns: 1fr;
      }

      .chip {
        white-space: normal;
      }
    }
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <div class="hero-card">
        <p class="eyebrow">Nifty Options Paper Trading</p>
        <h1>Buy vs Sell at a glance</h1>
        <p>
          A cleaner monitor for spotting which side is outperforming, whether a regime is active,
          and if capital is currently at work.
        </p>
        <div class="hero-meta" id="hero-meta"></div>
      </div>
      <div class="hero-card hero-aside">
        <div>
          <p class="eyebrow">Current Edge</p>
          <p class="hero-number" id="headline-edge">0</p>
          <p class="hero-caption" id="headline-caption">Waiting for live data</p>
        </div>
        <div>
          <p class="eyebrow">Active Setup</p>
          <p class="hero-number" id="headline-regime">WAIT</p>
          <p class="hero-caption" id="headline-regime-caption">No active position</p>
        </div>
      </div>
    </section>

    <section class="grid-4">
      <article class="metric-card">
        <div class="metric-label">Leader</div>
        <div class="metric-value" id="leader-value">Flat</div>
        <div class="metric-subtext" id="leader-subtext">Both sides are tied</div>
      </article>
      <article class="metric-card">
        <div class="metric-label">Combined Net PnL</div>
        <div class="metric-value mono" id="combined-pnl">0.00</div>
        <div class="metric-subtext" id="combined-subtext">Sell + Buy current total</div>
      </article>
      <article class="metric-card">
        <div class="metric-label">Open Exposure</div>
        <div class="metric-value" id="open-exposure">0</div>
        <div class="metric-subtext" id="open-subtext">No open positions</div>
      </article>
      <article class="metric-card">
        <div class="metric-label">Last Daily Net</div>
        <div class="metric-value mono" id="daily-combined">0.00</div>
        <div class="metric-subtext" id="daily-combined-subtext">Most recent combined session</div>
      </article>
    </section>

    <section class="side-grid">
      <article class="side-card sell">
        <div class="side-header">
          <h2 class="side-title">Option Selling</h2>
          <span class="state-pill" id="sell-state">UNKNOWN</span>
        </div>
        <div class="stats-grid" id="sell-stats"></div>
      </article>
      <article class="side-card buy">
        <div class="side-header">
          <h2 class="side-title">Option Buying</h2>
          <span class="state-pill" id="buy-state">UNKNOWN</span>
        </div>
        <div class="stats-grid" id="buy-stats"></div>
      </article>
    </section>

    <section class="insights-grid">
      <article class="insight-card">
        <div class="section-header">
          <h2>System Context</h2>
          <span class="mini-note">Live evaluator snapshot</span>
        </div>
        <div class="stats-grid" id="system-context"></div>
      </article>
      <article class="insight-card">
        <div class="section-header">
          <h2>Session Scoreboard</h2>
          <span class="mini-note">Latest completed day by method</span>
        </div>
        <div class="stats-grid" id="session-scoreboard"></div>
      </article>
    </section>

    <section class="position-grid">
      <article class="position-card" id="sell-position"></article>
      <article class="position-card" id="buy-position"></article>
    </section>

    <section class="panel">
      <div class="section-header">
        <h2>Recent Trades</h2>
        <span class="mini-note">Latest exits across both methods</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Exit</th>
              <th>Method</th>
              <th>Regime</th>
              <th>PnL</th>
              <th>Peak</th>
              <th>Drawdown</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody id="trades"></tbody>
        </table>
      </div>
    </section>

    <section class="panel">
      <div class="section-header">
        <h2>Daily Performance</h2>
        <span class="mini-note">Latest five rows per method</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Method</th>
              <th>Date</th>
              <th>Trades</th>
              <th>Win Rate</th>
              <th>Gross</th>
              <th>Cost</th>
              <th>Net</th>
            </tr>
          </thead>
          <tbody id="daily"></tbody>
        </table>
      </div>
    </section>

    <section class="panel">
      <div class="section-header">
        <h2>Alerts</h2>
        <span class="mini-note">Things worth your attention right now</span>
      </div>
      <div class="alerts" id="alerts"></div>
    </section>
  </div>

<script>
function asNumber(value) {
  const num = Number(value);
  return Number.isFinite(num) ? num : 0;
}

function numberClass(value) {
  const num = asNumber(value);
  if (num > 0) return 'positive';
  if (num < 0) return 'negative';
  return 'neutral';
}

function formatNumber(value, digits = 2) {
  return asNumber(value).toFixed(digits);
}

function formatSigned(value, digits = 2) {
  const num = asNumber(value);
  const prefix = num > 0 ? '+' : '';
  return `${prefix}${num.toFixed(digits)}`;
}

function formatPct(value, digits = 1) {
  return `${asNumber(value).toFixed(digits)}%`;
}

function latestRow(rows) {
  return rows && rows.length ? rows[rows.length - 1] : null;
}

function buildChip(label, value, dotClass = '') {
  const dot = `<span class="dot ${dotClass}"></span>`;
  return `<span class="chip">${dot}<strong>${label}:</strong> ${value}</span>`;
}

function statCard(label, value, extra = '', valueClass = '') {
  return `
    <div class="stat">
      <div class="stat-label">${label}</div>
      <div class="stat-value ${valueClass}">${value}</div>
      ${extra ? `<div class="mini-note">${extra}</div>` : ''}
    </div>
  `;
}

function buildLegs(position) {
  if (!position || !position.legs || !position.legs.length) return 'No leg data';
  return position.legs.map(leg =>
    `${leg.type || ''} ${leg.security_id || '-'} @ ${leg.entry_price ?? '-'} x ${leg.lots ?? '-'}`
  ).join('<br>');
}

function buildPositionCard(side, position) {
  const label = side === 'sell' ? 'Option Selling' : 'Option Buying';
  if (!position) {
    return `
      <div class="position-title">
        <h3>${label}</h3>
        <span class="state-pill">FLAT</span>
      </div>
      <div class="mini-note">No open position right now.</div>
    `;
  }

  return `
    <div class="position-title">
      <h3>${label}</h3>
      <span class="state-pill">${position.status || 'OPEN'}</span>
    </div>
    <div class="position-grid-lines">
      <div>
        <div class="line-label">Regime</div>
        <div class="line-value">${position.regime || '-'}</div>
      </div>
      <div>
        <div class="line-label">Trade ID</div>
        <div class="line-value mono">${position.trade_id || '-'}</div>
      </div>
      <div>
        <div class="line-label">Entry Time</div>
        <div class="line-value">${position.entry_time || '-'}</div>
      </div>
      <div>
        <div class="line-label">Strike / Expiry</div>
        <div class="line-value">${position.strike || '-'} / ${position.expiry || '-'}</div>
      </div>
    </div>
    <div class="legs">
      <div class="line-label">Legs</div>
      <div>${buildLegs(position)}</div>
    </div>
  `;
}

function buildDailyRows(rows, method) {
  return (rows || []).slice(-5).reverse().map(row => {
    const trades = asNumber(row.total_trades);
    const wins = asNumber(row.winning_trades);
    const winRate = trades ? (wins / trades) * 100 : 0;
    return `
      <tr>
        <td><strong>${method}</strong></td>
        <td>${row.date || ''}</td>
        <td>${row.total_trades || ''}</td>
        <td>${formatPct(winRate)}</td>
        <td class="mono">${formatSigned(row.gross_pnl || 0)}</td>
        <td class="mono">${formatSigned(row.estimated_cost || 0)}</td>
        <td class="mono ${numberClass(row.net_pnl || 0)}">${formatSigned(row.net_pnl || 0)}</td>
      </tr>
    `;
  });
}

async function load() {
  const [dashboardRes, tradesRes, summariesRes] = await Promise.all([
    fetch('/api/dashboard'),
    fetch('/api/trades/recent'),
    fetch('/api/summaries')
  ]);

  const dashboard = await dashboardRes.json();
  const trades = await tradesRes.json();
  const summaries = await summariesRes.json();

  const sell = dashboard.pnl?.sell || {};
  const buy = dashboard.pnl?.buy || {};
  const sellTotal = asNumber(sell.total);
  const buyTotal = asNumber(buy.total);
  const combinedTotal = sellTotal + buyTotal;
  const edge = sellTotal - buyTotal;
  const openCount = ['sell', 'buy'].filter(side => dashboard.positions?.[side]?.status === 'OPEN').length;

  let leader = 'Flat';
  let leaderSubtext = 'Both sides are tied on current net PnL';
  if (edge > 0) {
    leader = 'Selling';
    leaderSubtext = `Selling leads buying by ${formatSigned(edge)}`;
  } else if (edge < 0) {
    leader = 'Buying';
    leaderSubtext = `Buying leads selling by ${formatSigned(Math.abs(edge))}`;
  }

  const confirmedRegime = dashboard.signal?.confirmed_regime || 'WAIT';
  const candidateRegime = dashboard.signal?.candidate_regime || 'WAIT';
  const sellDailyLatest = latestRow(summaries.daily_sell || []);
  const buyDailyLatest = latestRow(summaries.daily_buy || []);
  const combinedDailyLatest = latestRow(summaries.daily_combined || []);

  document.getElementById('hero-meta').innerHTML = [
    buildChip('Experiment', dashboard.experiment || 'n/a', 'ok'),
    buildChip('Generated', dashboard.generated_at || 'n/a', 'ok'),
    buildChip('Cycle Start', dashboard.cycle_started_at || 'n/a', 'ok'),
    buildChip('Updater', dashboard.updater_ok === false ? 'FAILED' : (dashboard.updater_ok === true ? 'OK' : 'n/a'), dashboard.updater_ok === false ? 'bad' : 'ok'),
    buildChip('Candidate', `${candidateRegime} (${dashboard.signal?.candidate_count || 0})`, candidateRegime === 'WAIT' ? '' : 'ok'),
    buildChip('Last Signal', dashboard.signal?.last_signal_time || 'n/a', '')
  ].join('');

  const edgeNode = document.getElementById('headline-edge');
  edgeNode.textContent = formatSigned(edge);
  edgeNode.className = `hero-number mono ${numberClass(edge)}`;
  document.getElementById('headline-caption').textContent = leaderSubtext;
  document.getElementById('headline-regime').textContent = confirmedRegime;
  document.getElementById('headline-regime-caption').textContent =
    confirmedRegime === 'WAIT' ? 'No confirmed regime at the moment' : `Candidate ${candidateRegime} with count ${dashboard.signal?.candidate_count || 0}`;

  const leaderNode = document.getElementById('leader-value');
  leaderNode.textContent = leader;
  leaderNode.className = `metric-value ${leader === 'Flat' ? 'neutral' : (leader === 'Selling' ? 'positive' : 'negative')}`;
  document.getElementById('leader-subtext').textContent = leaderSubtext;

  const combinedNode = document.getElementById('combined-pnl');
  combinedNode.textContent = formatSigned(combinedTotal);
  combinedNode.className = `metric-value mono ${numberClass(combinedTotal)}`;
  document.getElementById('combined-subtext').textContent = `${formatSigned(sellTotal)} sell and ${formatSigned(buyTotal)} buy`;

  document.getElementById('open-exposure').textContent = String(openCount);
  document.getElementById('open-exposure').className = `metric-value ${openCount ? 'negative' : 'neutral'}`;
  document.getElementById('open-subtext').textContent = openCount ? `${openCount} method${openCount > 1 ? 's are' : ' is'} carrying live risk` : 'No open positions';

  const dailyCombinedNode = document.getElementById('daily-combined');
  dailyCombinedNode.textContent = formatSigned(combinedDailyLatest?.net_pnl || 0);
  dailyCombinedNode.className = `metric-value mono ${numberClass(combinedDailyLatest?.net_pnl || 0)}`;
  document.getElementById('daily-combined-subtext').textContent = combinedDailyLatest?.date
    ? `Combined session on ${combinedDailyLatest.date}`
    : 'No combined daily summary yet';

  function renderSideStats(side, pnl, daily) {
    const total = asNumber(pnl.total);
    const realised = asNumber(pnl.realised);
    const unrealised = asNumber(pnl.unrealised);
    const totalTrades = asNumber(daily?.total_trades || 0);
    const wins = asNumber(daily?.winning_trades || 0);
    const net = asNumber(daily?.net_pnl || 0);
    const winRate = totalTrades ? (wins / totalTrades) * 100 : 0;
    const otherTotal = side === 'sell' ? buyTotal : sellTotal;
    const edgeVsOther = total - otherTotal;

    document.getElementById(`${side}-state`).textContent = pnl.state || 'UNKNOWN';
    document.getElementById(`${side}-stats`).innerHTML = [
      statCard('Current Total', `<span class="mono ${numberClass(total)}">${formatSigned(total)}</span>`, pnl.timestamp || 'No timestamp'),
      statCard('Realised / Unrealised', `<span class="mono ${numberClass(realised + unrealised)}">${formatSigned(realised)} / ${formatSigned(unrealised)}</span>`),
      statCard('Latest Daily Net', `<span class="mono ${numberClass(net)}">${formatSigned(net)}</span>`, daily?.date || 'No day yet'),
      statCard('Daily Win Rate', formatPct(winRate), `${wins} wins from ${totalTrades} trades`),
      statCard('Current Edge', `<span class="mono ${numberClass(edgeVsOther)}">${formatSigned(edgeVsOther)}</span>`, `vs ${side === 'sell' ? 'buying' : 'selling'}`),
      statCard('Live Trade', pnl.trade_id ? `<span class="mono">${pnl.trade_id}</span>` : 'None', pnl.trade_id ? 'Currently linked to PnL state' : 'No active trade id')
    ].join('');
  }

  renderSideStats('sell', sell, sellDailyLatest);
  renderSideStats('buy', buy, buyDailyLatest);

  document.getElementById('system-context').innerHTML = [
    statCard('Confirmed Regime', confirmedRegime, dashboard.signal?.last_signal_time || 'No signal timestamp'),
    statCard('Candidate Regime', candidateRegime, `Count ${dashboard.signal?.candidate_count || 0}`),
    statCard('Last Regime', dashboard.signal?.last_regime || 'WAIT'),
    statCard('Updater Health', dashboard.updater_ok === false ? 'FAILED' : (dashboard.updater_ok === true ? 'OK' : 'n/a'), dashboard.generated_at || 'No generation time')
  ].join('');

  function latestDailyCard(label, row) {
    if (!row) {
      return statCard(label, 'No data', 'No completed session');
    }
    const trades = asNumber(row.total_trades);
    const wins = asNumber(row.winning_trades);
    const winRate = trades ? (wins / trades) * 100 : 0;
    return statCard(
      label,
      `<span class="mono ${numberClass(row.net_pnl || 0)}">${formatSigned(row.net_pnl || 0)}</span>`,
      `${row.date || 'n/a'} • ${row.total_trades || 0} trades • ${formatPct(winRate)} win rate`
    );
  }

  document.getElementById('session-scoreboard').innerHTML = [
    latestDailyCard('Selling Day', sellDailyLatest),
    latestDailyCard('Buying Day', buyDailyLatest),
    latestDailyCard('Combined Day', combinedDailyLatest),
    statCard('Current Spread', `<span class="mono ${numberClass(edge)}">${formatSigned(edge)}</span>`, 'Sell total minus buy total')
  ].join('');

  const sellPositionNode = document.getElementById('sell-position');
  const buyPositionNode = document.getElementById('buy-position');
  sellPositionNode.innerHTML = buildPositionCard('sell', dashboard.positions?.sell);
  buyPositionNode.innerHTML = buildPositionCard('buy', dashboard.positions?.buy);
  sellPositionNode.className = `position-card ${dashboard.positions?.sell ? '' : 'empty'}`;
  buyPositionNode.className = `position-card ${dashboard.positions?.buy ? '' : 'empty'}`;

  document.getElementById('trades').innerHTML = (trades.rows || []).map(row => `
    <tr>
      <td>${row.exit_time || ''}</td>
      <td><strong>${row.side || ''}</strong></td>
      <td>${row.regime || ''}</td>
      <td class="mono ${numberClass(row.trade_pnl || 0)}">${formatSigned(row.trade_pnl || 0)}</td>
      <td class="mono">${formatSigned(row.peak_pnl || 0)}</td>
      <td class="mono ${numberClass(-asNumber(row.drawdown_from_peak || 0))}">${formatSigned(-asNumber(row.drawdown_from_peak || 0))}</td>
      <td>${row.exit_reason || ''}</td>
    </tr>
  `).join('') || `<tr><td colspan="7" class="mini-note">No recent trades found.</td></tr>`;

  document.getElementById('daily').innerHTML = [
    ...buildDailyRows(summaries.daily_sell, 'SELL'),
    ...buildDailyRows(summaries.daily_buy, 'BUY')
  ].join('') || `<tr><td colspan="7" class="mini-note">No daily summaries found.</td></tr>`;

  const alerts = [];
  if (dashboard.updater_ok === false) {
    alerts.push({ text: 'Updater failed on the last evaluator cycle.', klass: 'bad' });
  }
  if (confirmedRegime !== 'WAIT') {
    alerts.push({ text: `Confirmed regime is ${confirmedRegime}.`, klass: 'warn' });
  }
  if (dashboard.positions?.sell?.status === 'OPEN') {
    alerts.push({ text: 'Selling side has an open position.', klass: 'warn' });
  }
  if (dashboard.positions?.buy?.status === 'OPEN') {
    alerts.push({ text: 'Buying side has an open position.', klass: 'warn' });
  }
  if (!alerts.length) {
    alerts.push({ text: 'System is flat and no active alerts are present.', klass: 'ok' });
  }

  document.getElementById('alerts').innerHTML = alerts
    .map(alert => `<div class="alert-pill ${alert.klass}">${alert.text}</div>`)
    .join('');
}

load();
setInterval(load, 5000);
</script>

</body>
</html>"""


class MonitoringHandler(BaseHTTPRequestHandler):
    def send_json(self, payload, status=HTTPStatus.OK, *, head_only=False):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

    def send_html(self, payload, status=HTTPStatus.OK, *, head_only=False):
        data = payload.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

    def handle_request(self, *, head_only=False):
        path = urlparse(self.path).path

        if path == "/":
            self.send_html(render_index(), head_only=head_only)
            return

        if path == "/static/favicon.ico":
            favicon_path = BASE_DIR / "static" / "favicon.ico"
            if favicon_path.exists():
                data = favicon_path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/x-icon")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if not head_only:
                    self.wfile.write(data)
                return
            self.send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND, head_only=head_only)
            return

        if path == "/api/dashboard":
            self.send_json(load_json(DASHBOARD_STATE_FILE, {}), head_only=head_only)
            return

        if path == "/api/trades/recent":
            self.send_json({
                "rows": load_recent_trade_events(APP_CONFIG.monitoring.recent_trades_limit),
            }, head_only=head_only)
            return

        if path == "/api/summaries":
            self.send_json(load_summaries(), head_only=head_only)
            return

        self.send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND, head_only=head_only)

    def do_GET(self):
        self.handle_request()

    def do_HEAD(self):
        self.handle_request(head_only=True)

    def log_message(self, format, *args):
        return


def run_server(host=None, port=None):
    bind_host = host or APP_CONFIG.monitoring.host
    bind_port = port or APP_CONFIG.monitoring.port
    server = ThreadingHTTPServer((bind_host, bind_port), MonitoringHandler)
    print(f"Monitoring UI serving on http://{bind_host}:{bind_port}")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
