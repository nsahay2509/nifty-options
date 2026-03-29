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
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" />
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {
      font-family: Cambria, Georgia, serif;
    }
    .mono {
      font-family: "SFMono-Regular", Consolas, monospace;
    }
    .small-pre {
      font-size: 12px;
      white-space: pre-wrap;
      margin-bottom: 0;
    }
  </style>
</head>
<body class="bg-light">

<div class="container mt-3">

  <div class="card mb-3">
    <div class="card-header bg-dark text-white">
      <b>System Status</b>
    </div>
    <div class="card-body">
      <div id="system"></div>
    </div>
  </div>

  <div class="card mb-3">
    <div class="card-header bg-primary text-white">
      <b>Portfolio</b>
    </div>
    <div class="card-body" id="portfolio"></div>
  </div>

  <div class="card mb-3">
    <div class="card-header bg-secondary text-white">
      <b>Open Positions</b>
    </div>
    <div class="card-body table-responsive">
      <table class="table table-sm table-bordered">
        <thead class="table-dark">
          <tr>
            <th>Side</th>
            <th>Status</th>
            <th>Regime</th>
            <th>Trade ID</th>
            <th>Entry Time</th>
            <th>Strike</th>
            <th>Expiry</th>
            <th>Legs</th>
          </tr>
        </thead>
        <tbody id="positions"></tbody>
      </table>
    </div>
  </div>

  <div class="card mb-3">
    <div class="card-header bg-info text-white">
      <b>Recent Trades</b>
    </div>
    <div class="card-body table-responsive">
      <table class="table table-sm table-bordered">
        <thead class="table-dark">
          <tr>
            <th>Exit</th>
            <th>Method</th>
            <th>Regime</th>
            <th>PnL</th>
            <th>Peak</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody id="trades"></tbody>
      </table>
    </div>
  </div>

  <div class="card mb-3">
    <div class="card-header bg-success text-white">
      <b>Daily Summary</b>
    </div>
    <div class="card-body table-responsive">
      <table class="table table-sm table-bordered">
        <thead class="table-dark">
          <tr>
            <th>Method</th>
            <th>Date</th>
            <th>Trades</th>
            <th>Wins</th>
            <th>Losses</th>
            <th>Gross</th>
            <th>Net</th>
          </tr>
        </thead>
        <tbody id="daily"></tbody>
      </table>
    </div>
  </div>

  <div class="card mb-3">
    <div class="card-header bg-danger text-white">
      <b>Alerts</b>
    </div>
    <div class="card-body">
      <pre id="alerts" class="small-pre"></pre>
    </div>
  </div>

</div>

<script>
function colored(val) {
  return Number(val) >= 0 ? 'text-success' : 'text-danger';
}

function buildLegs(position) {
  if (!position || !position.legs || !position.legs.length) return '-';
  return position.legs.map(leg =>
    `${leg.type || ''} ${leg.security_id} @ ${leg.entry_price ?? '-'} x ${leg.lots ?? '-'}`
  ).join('<br>');
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

  document.getElementById('system').innerHTML = `
    <b>Experiment:</b> ${dashboard.experiment || 'n/a'} |
    <b>Generated:</b> ${dashboard.generated_at || 'n/a'} |
    <b>Cycle Start:</b> ${dashboard.cycle_started_at || 'n/a'} |
    <b>Updater OK:</b> ${dashboard.updater_ok === null ? 'n/a' : dashboard.updater_ok}<br>
    <b>Confirmed Regime:</b> ${dashboard.signal?.confirmed_regime || 'WAIT'} |
    <b>Candidate:</b> ${(dashboard.signal?.candidate_regime || 'WAIT')} (${dashboard.signal?.candidate_count || 0}) |
    <b>Last Signal:</b> ${dashboard.signal?.last_signal_time || 'n/a'}
  `;

  document.getElementById('portfolio').innerHTML = `
    <span class="${colored(dashboard.pnl?.sell?.total ?? 0)}"><b>Sell:</b> ${dashboard.pnl?.sell?.total ?? 0}</span> |
    <span class="${colored(dashboard.pnl?.buy?.total ?? 0)}"><b>Buy:</b> ${dashboard.pnl?.buy?.total ?? 0}</span><br>
    <b>Sell State:</b> ${dashboard.pnl?.sell?.state || 'UNKNOWN'} |
    <b>Buy State:</b> ${dashboard.pnl?.buy?.state || 'UNKNOWN'}
  `;

  const positions = dashboard.positions || {};
  document.getElementById('positions').innerHTML = ['sell', 'buy'].map(side => {
    const position = positions[side];
    if (!position) {
      return `<tr><td>${side.toUpperCase()}</td><td colspan="7">No position data</td></tr>`;
    }
    return `
      <tr>
        <td><b>${side.toUpperCase()}</b></td>
        <td>${position.status || ''}</td>
        <td>${position.regime || ''}</td>
        <td class="mono">${position.trade_id || ''}</td>
        <td>${position.entry_time || ''}</td>
        <td>${position.strike || ''}</td>
        <td>${position.expiry || ''}</td>
        <td>${buildLegs(position)}</td>
      </tr>
    `;
  }).join('');

  document.getElementById('trades').innerHTML = (trades.rows || []).map(row => `
    <tr>
      <td>${row.exit_time || ''}</td>
      <td><b>${row.side || ''}</b></td>
      <td>${row.regime || ''}</td>
      <td class="mono ${colored(row.trade_pnl || 0)}">${row.trade_pnl || ''}</td>
      <td class="mono">${row.peak_pnl || ''}</td>
      <td>${row.exit_reason || ''}</td>
    </tr>
  `).join('');

  const sellDaily = (summaries.daily_sell || []).slice(-5).reverse().map(row => ({...row, method: 'SELL'}));
  const buyDaily = (summaries.daily_buy || []).slice(-5).reverse().map(row => ({...row, method: 'BUY'}));
  const dailyRows = [...sellDaily, ...buyDaily];

  document.getElementById('daily').innerHTML = dailyRows.map(row => `
    <tr>
      <td><b>${row.method}</b></td>
      <td>${row.date || ''}</td>
      <td>${row.total_trades || ''}</td>
      <td>${row.winning_trades || ''}</td>
      <td>${row.losing_trades || ''}</td>
      <td class="mono">${row.gross_pnl || ''}</td>
      <td class="mono ${colored(row.net_pnl || 0)}">${row.net_pnl || ''}</td>
    </tr>
  `).join('');

  const alerts = [];
  if (dashboard.updater_ok === false) alerts.push('Updater failed on the last evaluator cycle.');
  if ((dashboard.signal?.confirmed_regime || 'WAIT') !== 'WAIT') alerts.push(`Active regime: ${dashboard.signal.confirmed_regime}`);
  if ((dashboard.positions?.sell?.status || '') === 'OPEN') alerts.push('Sell side has an open position.');
  if ((dashboard.positions?.buy?.status || '') === 'OPEN') alerts.push('Buy side has an open position.');
  if (!alerts.length) alerts.push('No active alerts.');
  document.getElementById('alerts').textContent = alerts.join("\\n");
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
