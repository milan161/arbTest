import os
import sys
import pandas as pd
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Add core/arbcore to path
backend_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(backend_dir, "core"))

from arbcore.database.db_manager import DatabaseManager
from services.fund_service import FundService

app = FastAPI(title="ArbNext API", version="1.0.0")

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Database Manager and Services
# Explicitly point to the central database in the project root
root_db_path = os.path.abspath(os.path.join(backend_dir, "..", "..", "database", "arb_master.db"))
print(f"DEBUG: Using database at {root_db_path}")
db = DatabaseManager(db_path=root_db_path)

# Test connection and count
try:
    conn = db._get_conn()
    # Check if table exists first
    table_check = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='unified_fund_list'").fetchone()
    if table_check:
        count = conn.execute("SELECT count(*) FROM unified_fund_list").fetchone()[0]
        print(f"DEBUG: Found {count} records in unified_fund_list")
    else:
        print("DEBUG: Table 'unified_fund_list' NOT FOUND in database!")
    conn.close()
except Exception as e:
    print(f"DEBUG: Database error during startup: {e}")

fund_service = FundService(db)

@app.get("/api/test_db")
async def test_db():
    """Directly return raw data for debugging"""
    try:
        conn = db._get_conn()
        data = pd.read_sql_query("SELECT * FROM unified_fund_list LIMIT 5", conn).to_dict(orient='records')
        count = conn.execute("SELECT count(*) FROM unified_fund_list").fetchone()[0]
        conn.close()
        return {"status": "ok", "count": count, "raw_sample": data, "db_path": root_db_path}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/health")
async def get_health():
    health = db.get_health_status()
    return {"status": "ok", "health": health}

@app.get("/api/dashboard")
async def get_dashboard():
    """Unified dashboard data for both LOF and JSL"""
    data = fund_service.get_unified_dashboard_data()
    return {"status": "ok", "data": data}

@app.get("/api/market/overview")
async def get_market():
    data = fund_service.get_market_overview()
    return {"status": "ok", "data": data}

@app.get("/api/fund/{code}/history")
async def get_fund_history(code: str):
    data = fund_service.get_fund_history(code)
    return {"status": "ok", "data": data}

@app.get("/api/fund/{code}/basket")
async def get_fund_basket(code: str):
    data = fund_service.get_fund_basket(code)
    return {"status": "ok", "data": data}

@app.post("/api/system/trigger/{task}")
async def trigger_task(task: str):
    """Trigger LOF011 or LOF012 tasks"""
    import subprocess
    
    # Map tasks to script paths
    task_map = {
        "011": os.path.join(backend_dir, "..", "..", "LOFarb", "LOF011_daily_updater.py"),
        "012": os.path.join(backend_dir, "..", "..", "LOFarb", "LOF012_calculate_static_valuation.py")
    }
    
    if task not in task_map:
        return JSONResponse(status_code=400, content={"status": "error", "message": "Invalid task"})
    
    script_path = task_map[task]
    python_exe = os.path.join(backend_dir, "..", "..", ".venv", "Scripts", "python.exe")
    
    try:
        # Run in background to avoid blocking
        subprocess.Popen([python_exe, script_path], cwd=os.path.dirname(script_path))
        return {"status": "ok", "message": f"Task {task} started in background"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
