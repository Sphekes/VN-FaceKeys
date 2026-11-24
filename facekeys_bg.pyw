"""Run FaceKeys without a console window, retaining logs for troubleshooting."""
from pathlib import Path
import os
import sys
import traceback
from datetime import datetime

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
log_stream = open(LOG_DIR / "facekeys.log", "a", encoding="utf-8", buffering=1)
sys.stdout = log_stream
sys.stderr = log_stream
print(f"\n=== FaceKeys background launch: {datetime.now().isoformat(timespec='seconds')} ===", flush=True)
try:
    from facekeys_server import main
    main()
except BaseException:
    traceback.print_exc()
    raise
finally:
    log_stream.flush()
    log_stream.close()
