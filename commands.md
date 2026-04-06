# NIFTY Manual Commands

## 1) Check services

```bash
sudo systemctl status nifty-auto-paper.service
sudo systemctl status nifty-monitor.service
```

## 2) Runtime supervisor

```bash
sudo systemctl restart nifty-auto-paper.service
sudo systemctl stop nifty-auto-paper.service
sudo journalctl -u nifty-auto-paper.service -f
```

## 3) Monitoring UI

```bash
sudo systemctl restart nifty-monitor.service
sudo systemctl stop nifty-monitor.service
sudo journalctl -u nifty-monitor.service -f
```

## 4) One-shot manual runs

```bash
python3 scripts/run_paper_live_eval.py
./run_monitoring.sh
./run_auto_paper.sh
```

## 5) Stop manual foreground runs

```bash
pkill -f 'scripts/run_paper_live_eval.py'
pkill -f 'monitoring_web.py'
pkill -f 'scripts/auto_paper_runtime.py'
```

## 6) Tests

```bash
python3 -m pytest
python3 -m pytest tests/test_monitoring_web.py
```

## 7) Public checks

```bash
curl -s https://nifty.nsrk.in/health
curl -s 'https://nifty.nsrk.in/api/dashboard?ts=1' | python3 -m json.tool | head -n 80
```
