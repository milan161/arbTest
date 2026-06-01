# config_local.example.py - 本地敏感配置模板
# 请复制此文件为 config_local.py，并填入真实账号

# ============================================================
# 交易账号配置
# ============================================================

# 国金证券 MiniQMT 账号
GJS_ACCOUNT = "您的国金QMT账号"  # 国金QMT账号

# 银河证券 QMT 账号
YH_ACCOUNT = "您的银河QMT账号"  # 银河QMT账号

# ============================================================
# API密钥配置（如有）
# ============================================================

# 东方财富 token（如有）
EM_TOKEN = "您的东方财富token"

# 聚宽 token（如有）
JQ_TOKEN = "您的聚宽token"

# 其他密钥...

# ============================================================
# Woody API 账号配置
# ============================================================
WOODY_USERNAME = "your_email@example.com"
WOODY_PASSWORD = "your_password_here"
WOODY_BOT_TOKEN = "your_bot_token_here" # 访问 palmmicro.com 接口所需的 Token

# ============================================================
# 云端数据采集 (Cloud Siphon) 配置 (可选)
# 用于从海外 VPS 定时拉取 Woody API 数据和汇率
# ============================================================
VPS_HOST = ""       # 例如: "192.168.1.100"
VPS_PORT = 22       # SSH 端口，默认为 22
VPS_USER = ""       # SSH 用户名
VPS_PASSWORD = ""   # SSH 密码 (建议使用私钥认证)
# VPS_KEY_PATH = r"C:\Users\yourname\.ssh\id_rsa" # 可选，如果使用私钥认证
VPS_DATA_DIR = "/opt/arb_siphon_data" # VPS上保存数据的目录
