"""
admin_launcher.py - 维护面板后台（端口 5002）
负责：
- 启动/检测 LOF00 配置中心
- 运行 011 / 012
- 返回维护状态
"""

import os
import sys
import json
import time
import socket
import threading
import subprocess
from datetime import datetime
from flask import Flask, jsonify, redirect, request, Response

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
ADMIN_STATUS_PATH = os.path.join(LOGS_DIR, "admin_status.json")
ADMIN_LOGS = {
    "01": os.path.join(LOGS_DIR, "01_数据大一统更新.log"),
    "012": os.path.join(LOGS_DIR, "012_静态估值计算.log"),
}

LOF00_PORT = int(os.environ.get("LOF00_PORT", "5001"))
LOF00_URL = os.environ.get("LOF00_URL", f"http://localhost:{LOF00_PORT}/")

os.makedirs(LOGS_DIR, exist_ok=True)

app = Flask(__name__)

# 简单CORS，允许从5000页面调用5002接口
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response

@app.route("/admin/<path:_path>", methods=["OPTIONS"])
def admin_preflight(_path):
    return ("", 204)


def _is_port_listening(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _ensure_lof00_running():
    if _is_port_listening(LOF00_PORT):
        return True
    try:
        script_path = os.path.join(BASE_DIR, "LOF00_input_LOF_info.py")
        subprocess.Popen(
            [sys.executable, "-X", "utf8", script_path],
            cwd=BASE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        time.sleep(0.5)
        return _is_port_listening(LOF00_PORT)
    except Exception:
        return False


def _load_admin_status():
    if os.path.exists(ADMIN_STATUS_PATH):
        try:
            with open(ADMIN_STATUS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "01": {"status": "unknown", "last_run": None, "message": ""},
        "012": {"status": "unknown", "last_run": None, "message": ""},
    }


def _save_admin_status(status):
    try:
        with open(ADMIN_STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _set_admin_status(task, status, message=""):
    data = _load_admin_status()
    if task not in data:
        data[task] = {"status": "unknown", "last_run": None, "message": ""}
    data[task]["status"] = status
    data[task]["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data[task]["message"] = message
    _save_admin_status(data)


def _run_script_async(script_name, task_key, force_woody=False, extra_args=None):
    def _runner():
        _set_admin_status(task_key, "running", "执行中")
        env = os.environ.copy()
        # 强制子进程使用 UTF-8 输出，避免在 Windows 环境下默认输出 GBK 导致读取乱码
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        # 强制禁用 Python 缓冲机制，实现真正的一行一行实时吐出
        env["PYTHONUNBUFFERED"] = "1"
        if force_woody:
            env["FORCE_WOODY_UPDATE"] = "1"
        script_path = os.path.join(BASE_DIR, script_name)
        try:
            log_path = ADMIN_LOGS.get(task_key, os.path.join(LOGS_DIR, f"admin_{task_key}.log"))
            os.makedirs(LOGS_DIR, exist_ok=True)
            with open(log_path, "w", encoding="utf-8-sig") as logf:
                header = f"--- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} START {task_key} ---\n"
                logf.write(header)
                        logf.flush()
                cmd = [sys.executable, "-u", "-X", "utf8", script_path]
                if extra_args:
                    cmd.extend(extra_args)
                proc = subprocess.Popen(
                    cmd,
                    cwd=BASE_DIR,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=0,
                )
                # 同时输出到终端和日志文件
                for line_bytes in iter(proc.stdout.readline, b''):
                    try:
                        line = line_bytes.decode('utf-8')
                    except UnicodeDecodeError:
                        try:
                            line = line_bytes.decode('gbk')
                        except UnicodeDecodeError:
                            line = line_bytes.decode('utf-8', errors='replace')
                    
                    sys.stdout.write(line)
                    sys.stdout.flush()
                    logf.write(line)
                    logf.flush()
                proc.wait()
            if proc.returncode == 0:
                _set_admin_status(task_key, "success", "完成")
            else:
                _set_admin_status(task_key, "failed", "执行失败")
        except Exception as e:
            _set_admin_status(task_key, "failed", str(e))

    t = threading.Thread(target=_runner, daemon=True)
    t.start()


@app.route("/admin/status", methods=["GET"])
def admin_status():
    return jsonify(_load_admin_status()), 200

# 维护面板：读取最近日志
@app.route("/admin/log/<task>", methods=["GET"])
def admin_log(task):
    limit = int(request.args.get("limit", "200"))
    log_path = ADMIN_LOGS.get(task, os.path.join(LOGS_DIR, f"admin_{task}.log"))
    if not os.path.exists(log_path):
        return jsonify({"task": task, "lines": []}), 200
    try:
        with open(log_path, "rb") as f:
            data = f.read()
        text = data.decode("utf-8-sig", errors="replace")
        lines = text.splitlines()[-limit:]
        return jsonify({"task": task, "lines": lines}), 200
    except Exception:
        return jsonify({"task": task, "lines": []}), 200

# 维护面板：文本日志（新窗口查看）
@app.route("/admin/logtext/<task>", methods=["GET"])
def admin_logtext(task):
    log_path = ADMIN_LOGS.get(task, os.path.join(LOGS_DIR, f"admin_{task}.log"))
    if not os.path.exists(log_path):
        return Response("日志不存在或尚未运行该任务。\n", status=200, mimetype="text/plain")
    try:
        with open(log_path, "rb") as f:
            data = f.read()
        try: 
            text = data.decode("utf-8-sig")
        except Exception: 
            try:
                text = data.decode("gbk")
            except Exception:
                text = data.decode("utf-8", errors="replace")
        return Response(text, status=200, mimetype="text/plain")
    except Exception as e:
        return Response(f"读取日志失败: {e}\n", status=200, mimetype="text/plain")

@app.route("/admin/stream/<task>", methods=["GET"])
def admin_stream(task):
    """返回一个黑底白字的实时日志查看终端页面"""
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>[运行中] {task} - 实时日志回显</title>
        <style>
            body {{ background-color: #1e1e1e; color: #d4d4d4; font-family: 'Consolas', 'Courier New', monospace; padding: 15px; margin: 0; }}
            #log-container {{ white-space: pre-wrap; word-wrap: break-word; font-size: 14px; line-height: 1.5; padding-bottom: 50px; }}
        </style>
    </head>
    <body>
        <div id="log-container">正在连接日志流...</div>
        <script>
            async function fetchLog() {{
                try {{
                    // 加时间戳防止浏览器缓存
                    const res = await fetch('/admin/logtext/{task}?nocache=' + new Date().getTime());
                    if (!res.ok) throw new Error('HTTP Error: ' + res.status);
                    const text = await res.text();
                    const container = document.getElementById('log-container');
                    
                    if (text && text.trim().length > 0) {{
                        // 判断滚动条是否在最底部附近，如果是，更新后自动滚到底部
                        const isScrolledToBottom = document.documentElement.scrollHeight - window.innerHeight <= window.scrollY + 50;
                        container.textContent = text;
                        if (isScrolledToBottom) {{
                            window.scrollTo(0, document.documentElement.scrollHeight);
                        }}
                    }}
                }} catch (e) {{
                    document.getElementById('log-container').textContent = '连接日志流异常: ' + e.message + '\\n尝试重连中...';
                }}
            }}
            setInterval(fetchLog, 1000); // 每1秒刷新一次屏幕
            fetchLog();
        </script>
    </body>
    </html>
    """
    return html

@app.route("/admin/lof00", methods=["GET"])
def admin_lof00():
    return jsonify({"running": _is_port_listening(LOF00_PORT), "port": LOF00_PORT}), 200


@app.route("/admin/config", methods=["GET"])
def admin_config():
    _ensure_lof00_running()
    return redirect(LOF00_URL, code=302)


@app.route("/admin/run/01", methods=["GET", "POST"])
def admin_run_01():
    _run_script_async("LOF011_daily_updater.py", "01")
    return jsonify({"status": "started", "task": "01"}), 200


@app.route("/admin/run/012", methods=["GET", "POST"])
def admin_run_012():
    _run_script_async("LOF012_calculate_static_valuation.py", "012")
    return jsonify({"status": "started", "task": "012"}), 200

@app.route("/admin/run/woody", methods=["GET", "POST"])
def admin_run_woody():
    _run_script_async("LOF011_daily_updater.py", "woody", force_woody=True)
    return jsonify({"status": "started", "task": "woody"}), 200

@app.route("/admin/run/calib", methods=["GET", "POST"])
def admin_run_calib():
    _run_script_async("LOF011_daily_updater.py", "calib", extra_args=["--calib-only"])
    return jsonify({"status": "started", "task": "calib"}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("ADMIN_PORT", "5002"))
    print(f"[ADMIN] running on http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
