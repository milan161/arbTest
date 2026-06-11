import paramiko
import os
import yaml
import pandas as pd
from LOFarb.account_private import VPS_HOST, VPS_PORT, VPS_USER, VPS_PASSWORD, VPS_DATA_DIR, WOODY_BOT_TOKEN

def deploy():
    print(f"🚀 正在连接东京 VPS ({VPS_HOST})...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        # 1. 自动从 lof_config.yaml 提取 LOF 基金代码
        config_path = os.path.join("LOFarb", "lof_config.yaml")
        lof_symbols = []
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                for fund in config.get('funds', []):
                    code = str(fund.get('code', ''))
                    if code:
                        prefix = 'sh' if code.startswith('5') else 'sz'
                        lof_symbols.append(f"{prefix}{code}")
        
        lof_symbols_str = ",".join(set(lof_symbols))
        print(f"📊 [LOF] 自动提取基金数量: {len(lof_symbols)}")

        ssh.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASSWORD, timeout=15)
        sftp = ssh.open_sftp()

        remote_home = "/root" if VPS_USER == "root" else f"/home/{VPS_USER}"
        remote_project_dir = f"{remote_home}/LOFarb"
        remote_script = f"{remote_project_dir}/cloud_siphon.py"
        remote_log = f"{remote_project_dir}/siphon.log"

        ssh.exec_command(f"mkdir -p {remote_project_dir}")
        ssh.exec_command(f"mkdir -p {VPS_DATA_DIR}")

        # 上传 采集器
        sftp.put(os.path.join("ArbDashboard", "scripts", "cloud_siphon.py"), remote_script)
        
        # 2. 直接从 jsl/fund_list.csv 提取 JSL 基金代码
        jsl_csv_path = os.path.join("jsl", "fund_list.csv")
        jsl_remote_script = f"{remote_project_dir}/041_jsl_cloud_shares.py"
        jsl_remote_symbols = f"{remote_project_dir}/jsl_vps_symbols.txt"
        jsl_log = f"{remote_project_dir}/jsl_shares.log"
        
        jsl_codes = []
        if os.path.exists(jsl_csv_path):
            # 读取 CSV，提取代码列
            df = pd.read_csv(jsl_csv_path, encoding='utf-8')
            # 过滤深交所代码 (16, 15, 14 开头)
            all_codes = df['代码'].astype(str).tolist()
            jsl_codes = [c for c in all_codes if c.startswith(('16', '15', '14'))]
            
            # 生成并上传 symbols 文件
            temp_symbols_file = os.path.join("jsl", "jsl_vps_symbols.txt")
            with open(temp_symbols_file, 'w', encoding='utf-8') as f:
                f.write(",".join(jsl_codes))
            
            sftp.put(temp_symbols_file, jsl_remote_symbols)
            sftp.put(os.path.join("jsl", "041_jsl_cloud_shares.py"), jsl_remote_script)
            print(f"📊 [JSL] 从 CSV 提取基金数量: {len(jsl_codes)}")
        
        sftp.close()

        # 3. 系统配置与定时任务
        ssh.exec_command("timedatectl set-timezone Asia/Shanghai || ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime")

        cron_woody = f"20 9 * * 1-5 /usr/bin/python3 {remote_script} --symbols {lof_symbols_str} --token {WOODY_BOT_TOKEN} --outdir {VPS_DATA_DIR} >> {remote_log} 2>&1"
        cron_jsl = f"0 6 * * 1-5 /usr/bin/python3 {jsl_remote_script} --file {jsl_remote_symbols} --outdir {VPS_DATA_DIR} >> {jsl_log} 2>&1"

        print("⏰ 更新 Crontab 定时任务 (09:20 & 06:00 Beijing)...")
        ssh.exec_command(f'(crontab -l 2>/dev/null | grep -vE "cloud_siphon.py|041_jsl_cloud_shares.py"; echo "{cron_woody}"; echo "{cron_jsl}") | crontab -')

        print("\n✅ VPS 多维度采集环境部署成功！")
        print(f"LOF 监控: {len(lof_symbols)} 只 (09:20)")
        print(f"JSL 份额: {len(jsl_codes)} 只 (06:00)")

    except Exception as e:
        print(f"❌ 部署失败: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    deploy()
