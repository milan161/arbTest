import os
import sys

# Add jsl directory to path to import 00_web_server
sys.path.append(os.path.join(os.getcwd(), 'jsl'))

# Use a trick to import a file starting with digits
import importlib.util
spec = importlib.util.spec_from_file_location("web_server", "jsl/00_web_server.py")
web_server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web_server)

try:
    data = web_server.load_jsl_data()
    print(f"Categories found: {list(data.keys())}")
    for cat, funds in data.items():
        print(f"  {cat}: {len(funds)} funds")
        if funds:
            f = funds[0]
            print(f"    Sample: {f['code']} - {f['name']} (NAV: {f['nav']}, Date: {f['nav_date']})")
except Exception as e:
    import traceback
    traceback.print_exc()
