# Monitoring Deployment

This project now includes a read-only monitoring web app in [monitoring_web.py](/home/ubuntu/nifty/monitoring_web.py).

It reads only:
- `data/dashboard_state.json`
- recent trade-event CSVs
- summary CSV files

## Local Run

```bash
cd /home/ubuntu/nifty
./run_monitoring.sh
```

Default URL:

```text
http://127.0.0.1:8010/
```

## tmux Run

```bash
tmux new -s nifty_monitor ./run_monitoring.sh
tmux attach -t nifty_monitor
tmux kill-session -t nifty_monitor
```

## systemd Setup

Copy the unit file:

```bash
sudo cp /home/ubuntu/nifty/deploy/systemd/nifty-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable nifty-monitor
sudo systemctl start nifty-monitor
sudo systemctl status nifty-monitor
```

## Nginx Setup

Copy the site config:

```bash
sudo cp /home/ubuntu/nifty/deploy/nginx/nifty.nsrk.in.conf /etc/nginx/sites-available/nifty.nsrk.in
sudo ln -s /etc/nginx/sites-available/nifty.nsrk.in /etc/nginx/sites-enabled/nifty.nsrk.in
sudo nginx -t
sudo systemctl reload nginx
```

## HTTPS

After DNS for `nifty.nsrk.in` points to the server, add TLS with Certbot or Caddy.

Example with Certbot:

```bash
sudo certbot --nginx -d nifty.nsrk.in
```

## Optional Auth

If you want basic auth in Nginx:

```bash
sudo apt-get install apache2-utils
sudo htpasswd -c /etc/nginx/.nifty-monitor.htpasswd your_user
```

Then add this inside the `location /` block:

```nginx
auth_basic "Restricted";
auth_basic_user_file /etc/nginx/.nifty-monitor.htpasswd;
```

## Notes

- The monitoring app is read-only.
- The evaluator writes `data/dashboard_state.json` each cycle.
- If the dashboard looks stale, first check the `nifty_evaluator.py` process and then `data/dashboard_state.json`.
