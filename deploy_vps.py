import paramiko
import os
import yaml
from LOFarb.account_private import VPS_HOST, VPS_PORT, VPS_USER, VPS_PASSWORD, VPS_DATA_DIR, WOODY_BOT_TOKEN

def deploy():
    print(f"🚀 正在连接东京 VPS ({VPS_HOST})...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        # 1. 自动从 lof_config.yaml 提取所有基金代码
        config_path = os.path.join("LOFarb", "lof_config.yaml")
        symbols_list = []
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                for fund in config.get('funds', []):
                    code = str(fund.get('code', ''))
                    if code:
                        prefix = 'sh' if code.startswith('5') else 'sz'
                        symbols_list.append(f"{prefix}{code}")
        
        symbols_str = ",".join(set(symbols_list))
        print(f"📊 自动提取基金数量: {len(symbols_list)}")

        ssh.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASSWORD, timeout=15)
        sftp = ssh.open_sftp()

        remote_home = "/root" if VPS_USER == "root" else f"/home/{VPS_USER}"
        remote_project_dir = f"{remote_home}/LOFarb"
        remote_script = f"{remote_project_dir}/LOF_cloud_siphon.py"
        remote_log = f"{remote_project_dir}/siphon.log"

        print(f"📂 同步目录结构...")
        ssh.exec_command(f"mkdir -p {remote_project_dir}")
        ssh.exec_command(f"mkdir -p {VPS_DATA_DIR}")

        local_script = os.path.join("LOFarb", "LOF_cloud_siphon.py")
        print(f"📤 上传采集器: {local_script}")
        sftp.put(local_script, remote_script)
        
        sftp.close()

        print(f"🌍 配置 VPS 时区为 Asia/Shanghai (北京时间)...")
        ssh.exec_command("timedatectl set-timezone Asia/Shanghai || ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime")

        # 2. 设置定时任务 (北京 9:20)
        # 格式: 分 时 * * 1-5 (周一至周五)
        cron_command = f"20 9 * * 1-5 /usr/bin/python3 {remote_script} --symbols {symbols_str} --token {WOODY_BOT_TOKEN} --outdir {VPS_DATA_DIR} >> {remote_log} 2>&1"
        
        print("⏰ 更新 Crontab 定时任务 (09:20 Beijing)...")
        ssh.exec_command(f'(crontab -l 2>/dev/null | grep -v "LOF_cloud_siphon.py"; echo "{cron_command}") | crontab -')

        print("\n✅ VPS 全量采集环境部署成功！")
        print(f"已监控基金: {len(symbols_list)} 只")
        print(f"下次运行时间: 每个工作日 北京 09:20")

    except Exception as e:
        print(f"❌ 部署失败: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    deploy()
