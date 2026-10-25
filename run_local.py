import time
import subprocess
import sys

INTERVAL_SECONDS = 60  # Check every 60 seconds

print(f"[*] Starting Local MS Rewards Sentinel (Interval: {INTERVAL_SECONDS}s)")
print("[*] Press Ctrl+C at any time to stop.\n")

while True:
    try:
        subprocess.run([sys.executable, "sentinel.py"])
    except KeyboardInterrupt:
        print("\n[*] Local sentinel stopped.")
        break
    except Exception as e:
        print(f"[-] Execution error: {e}")
    time.sleep(INTERVAL_SECONDS)
