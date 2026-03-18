




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



