
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

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    port = 8000
    host = "127.0.0.1"
    url = f"http://{host}:{port}"
    
    print("╔════════════════════════════════════════╗")
    print("║         Video Downloader Web UI        ║")
    print("╚════════════════════════════════════════╝")
    
    # Get script directory
    script_dir = Path(__file__).parent.absolute()
    
    # Check if main.py exists
    if not (script_dir / "main.py").exists():
        print(f" Error: main.py not found in {script_dir}")
        print(f"Current directory: {os.getcwd()}")
        sys.exit(1)
    
    # Check for ffmpeg
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
    except:
        print("  Warning: ffmpeg not found")
        print("   Install: sudo apt install ffmpeg")
    
    print(f" Opening browser to {url}...")
    threading.Timer(2.0, lambda: webbrowser.open(url)).start()
    
    print(f" Starting server on {url}")
    print(" Press Ctrl+C to stop the server\n")
    
    # Change to script directory
    os.chdir(script_dir)
    
    # Import and run uvicorn directly
    try:
        import uvicorn
        from main import app
        
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level="info"
        )
    except ImportError as e:
        print(f" Error: Import error: {e}")
        print("\nMake sure you have all dependencies installed:")
        print("pip install fastapi uvicorn yt-dlp python-multipart")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n Server stopped. Goodbye!")
        sys.exit(0)
    except Exception as e:
        print(f" Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()