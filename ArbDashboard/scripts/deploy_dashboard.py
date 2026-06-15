import os
import sys
import shutil
import subprocess
import zipfile
import paramiko

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from arbcore.config.account_private import VPS_HOST, VPS_PORT, VPS_USER, VPS_PASSWORD

def zip_directory(folder_path, zip_path):
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(folder_path):
            # Skip private and cache directories
            dirs[:] = [d for d in dirs if d not in ('private', 'auto_trade', '__pycache__', 'node_modules', '.git')]
            for file in files:
                if file.endswith(('.pyc', '.log', '.db')): continue
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, os.path.dirname(folder_path))
                zipf.write(file_path, arcname)

def deploy():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    dashboard_dir = os.path.join(root_dir, 'ArbDashboard')
    frontend_dir = os.path.join(dashboard_dir, 'frontend')
    backend_dir = os.path.join(dashboard_dir, 'backend')
    
    print("🚀 开始一键部署 ArbDashboard 到 VPS...")
    
    # 1. 编译前端
    print("📦 1/5 正在编译 Vue 前端...")
    subprocess.run(["npm", "run", "build"], cwd=frontend_dir, shell=True, check=True)
    
    # 2. 准备安全数据库
    print("🛢️ 2/5 正在生成脱敏后的 share.db...")
    make_share_db_script = os.path.join(root_dir, "scratch", "make_share_db.py")
    if os.path.exists(make_share_db_script):
        subprocess.run(["python", make_share_db_script], env=dict(os.environ, PYTHONIOENCODING="utf8"), check=True)
    
    master_db_src = os.path.join(root_dir, "database", "arb_master_share.db")
    
    # 3. 打包代码
    print("🗜️ 3/5 正在打包后端与核心代码...")
    zip_path = os.path.join(root_dir, "ArbDashboard_Release.zip")
    if os.path.exists(zip_path):
        os.remove(zip_path)
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # 添加 Frontend Dist
        dist_dir = os.path.join(frontend_dir, 'dist')
        for root, dirs, files in os.walk(dist_dir):
            for file in files:
                fp = os.path.join(root, file)
                arcname = os.path.relpath(fp, dashboard_dir)
                zipf.write(fp, f"ArbDashboard/{arcname}")
                
        # 添加 Backend
        for root, dirs, files in os.walk(backend_dir):
            dirs[:] = [d for d in dirs if d not in ('private', 'auto_trade', '__pycache__', 'core')]
            for file in files:
                if file.endswith(('.pyc', '.log', '.db')): continue
                fp = os.path.join(root, file)
                arcname = os.path.relpath(fp, dashboard_dir)
                zipf.write(fp, f"ArbDashboard/{arcname}")
                
        # 添加 arbcore
        arbcore_dir = os.path.join(root_dir, 'arbcore')
        for root, dirs, files in os.walk(arbcore_dir):
            dirs[:] = [d for d in dirs if d not in ('__pycache__',)]
            for file in files:
                if file.endswith('.pyc'): continue
                fp = os.path.join(root, file)
                arcname = os.path.relpath(fp, root_dir)
                zipf.write(fp, arcname)

    # 4. 上传到 VPS
    print(f"☁️ 4/5 正在连接并上传文件至 VPS ({VPS_HOST})...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        ssh.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASSWORD, timeout=15)
        sftp = ssh.open_sftp()
        
        remote_home = "/root" if VPS_USER == "root" else f"/home/{VPS_USER}"
        remote_dest = f"{remote_home}/ArbWebApp"
        ssh.exec_command(f"mkdir -p {remote_dest}/database")
        
        # 上传 ZIP
        print("   - 传输 ArbDashboard_Release.zip (可能需要几十秒)...")
        sftp.put(zip_path, f"{remote_dest}/ArbDashboard_Release.zip")
        
        # 上传数据库
        if os.path.exists(master_db_src):
            print("   - 传输 arb_master_share.db...")
            sftp.put(master_db_src, f"{remote_dest}/database/arb_master.db")
            
        sftp.close()
        
        # 5. 解压并安装依赖、启动服务
        print("⚙️ 5/5 在 VPS 上部署与重启服务...")
        commands = [
            f"cd {remote_dest} && unzip -o ArbDashboard_Release.zip",
            f"cd {remote_dest} && rm ArbDashboard_Release.zip",
            f"cd {remote_dest}/ArbDashboard/backend && pip3 install -r requirements.txt",
            # 创建启动脚本
            f"echo -e '#!/bin/bash\\ncd {remote_dest}/ArbDashboard/backend\\npython3 -m uvicorn main:app --host 0.0.0.0 --port 80' > {remote_dest}/start_server.sh",
            f"chmod +x {remote_dest}/start_server.sh",
            # 停止老的服务
            f"pkill -f 'uvicorn main:app' || true",
            f"nohup {remote_dest}/start_server.sh > {remote_dest}/server.log 2>&1 </dev/null & sleep 2"
        ]
        
        for cmd in commands:
            stdin, stdout, stderr = ssh.exec_command(cmd)
            # 等待某些命令执行完
            stdout.channel.recv_exit_status()
            err = stderr.read().decode().strip()
            if err and 'warn' not in err.lower():
                pass # print(f"   [VPS Output] {err}")
                
        print(f"✅ 部署完成！")
        print(f"🌍 你的公网访问地址: http://{VPS_HOST}")
        print("（注意：VPS 需要在防火墙中放行 80 端口）")
        
    except Exception as e:
        print(f"❌ 部署失败: {e}")
    finally:
        ssh.close()
        if os.path.exists(zip_path):
            os.remove(zip_path)

if __name__ == "__main__":
    deploy()
