import paramiko
import os
import sys
import time

sys.path.append(os.path.abspath('D:/Study/arbTest'))
from arbcore.config.account_private import VPS_HOST, VPS_PORT, VPS_USER, VPS_PASSWORD

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASSWORD)

ssh.exec_command('pkill -f uvicorn')
time.sleep(1)

# To properly detach a process in Paramiko, you can use the pty=False and nohup, 
# or just run it inside a tmux/screen session, or use systemd.
# We will use bash -c with nohup and redirect all standard streams.
cmd = "nohup bash -c 'cd /root/ArbWebApp/ArbDashboard/backend && python3 -m uvicorn main:app --host 0.0.0.0 --port 80' > /root/ArbWebApp/server.log 2>&1 < /dev/null &"
ssh.exec_command(cmd)

time.sleep(3)

stdin, stdout, stderr = ssh.exec_command("ps aux | grep uvicorn; cat /root/ArbWebApp/server.log")
print("STDOUT:", stdout.read().decode())
ssh.close()
