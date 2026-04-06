




python3 -m venv venv
source venv/bin/activate


pip freeze > requirements.txt
pip install -r requirements.txt

tree -I 'venv|__pycache__' -L 2


git add .
git commit -m "Initial commit"
git push


# TMUX commands

tmux new -s nifty_eval ./run_nifty.sh

Ctrl + b
then d

tmux ls  

tmux attach -t nifty_eval

Ctrl + C. # To stop the code

tmux kill-session -t nifty_eval

# ----------------------------

# Monitoring web app

tmux new -s nifty_monitor ./run_monitoring.sh
tmux attach -t nifty_monitor
tmux kill-session -t nifty_monitor

# systemd

sudo cp deploy/systemd/nifty-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable nifty-monitor
sudo systemctl start nifty-monitor
sudo systemctl status nifty-monitor

# nginx

sudo cp deploy/nginx/nifty.nsrk.in.conf /etc/nginx/sites-available/nifty.nsrk.in
sudo ln -s /etc/nginx/sites-available/nifty.nsrk.in /etc/nginx/sites-enabled/nifty.nsrk.in
sudo nginx -t
sudo systemctl reload nginx


