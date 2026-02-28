
"""
Video Downloader Desktop App - Launches the web UI in your default browser
"""

import os
import sys
import webbrowser
import time
import threading
import subprocess
from pathlib import Path

def find_ffmpeg():
    """Check if ffmpeg is available"""
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        return True
    except:
        return False

def launch_server():
    """Launch the FastAPI server"""
    import uvicorn
    from main import app
    
    port = 8000
    host = "127.0.0.1"
    
    print(f"\n Server starting at http://{host}:{port}")
    print(" Opening browser in 2 seconds...")
    print(" Press Ctrl+C to quit\n")
    
    # Open browser in a separate thread
    threading.Timer(2.0, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    
    # Run the server
    uvicorn.run(app, host=host, port=port, log_level="warning")

def main():
    print("╔════════════════════════════════════════╗")
    print("║        Video Downloader Desktop        ║")
    print("╚════════════════════════════════════════╝")
    
    # Check if we're in the right directory
    if not Path("main.py").exists():
        print(" Error: main.py not found in current directory")
        print("   Please run this script from your project folder")
        input("\nPress Enter to exit...")
        sys.exit(1)
    
    # Check for ffmpeg
    if not find_ffmpeg():
        print("  Warning: ffmpeg not found")
        print("   Some features may not work properly")
        print("   Install: sudo apt install ffmpeg (Linux)")
        print("            brew install ffmpeg (Mac)")
        print("            https://ffmpeg.org (Windows)")
    
    try:
        launch_server()
    except KeyboardInterrupt:
        print("\n\n Goodbye!")
    except Exception as e:
        print(f"\n Error: {e}")
        input("\nPress Enter to exit...")

if __name__ == "__main__":
    main()