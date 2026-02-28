
"""
Simple Video Downloader Launcher
"""

import sys
import os
import webbrowser
import time
import threading
import subprocess
from pathlib import Path

def main():
    port = 8000
    host = "127.0.0.1"
    url = f"http://{host}:{port}"
    
    print("╔════════════════════════════════════════╗")
    print("║        Video Downloader Web UI        ║")
    print("╚════════════════════════════════════════╝")
    
    # Check if main.py exists
    if not Path("main.py").exists():
        print(" Error: main.py not found in current directory")
        print("   Please run this script from your project folder")
        sys.exit(1)
    
    # Check for ffmpeg
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
    except:
        print(" Warning: ffmpeg not found")
        print("   Install: sudo apt install ffmpeg")
    
    print(f" Opening browser to {url}...")
    threading.Timer(2.0, lambda: webbrowser.open(url)).start()
    
    print(f" Starting server on {url}")
    print(" Press Ctrl+C to stop the server\n")
    
    # Run uvicorn
    cmd = [sys.executable, "-m", "uvicorn", "main:app", "--host", host, "--port", str(port)]
    
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        print("\n Server stopped. Goodbye!")
        sys.exit(0)

if __name__ == "__main__":
    main()