
"""
Video Downloader CLI - Launch the web UI in your browser
"""

import click
import subprocess
import sys
import os
import webbrowser
import time
import signal
import atexit
import threading
from pathlib import Path

@click.command()
@click.option('--port', '-p', default=8000, help='Port to run the server on')
@click.option('--host', '-h', default='127.0.0.1', help='Host to bind to')
@click.option('--no-browser', '-n', is_flag=True, help='Don\'t open browser automatically')
@click.option('--debug', '-d', is_flag=True, help='Run in debug mode')
@click.version_option(version='1.0.0')
def main(port, host, no_browser, debug):
    """
    Video Downloader - Download videos from YouTube, TikTok, Instagram, and more!
    
    This command starts the Video Downloader web interface and opens it in your browser.
    """
    click.echo(click.style('╔════════════════════════════════════════╗', fg='cyan', bold=True))
    click.echo(click.style('║      Video Downloader Web UI        ║', fg='cyan', bold=True))
    click.echo(click.style('╚════════════════════════════════════════╝', fg='cyan', bold=True))
    
    # Check if uvicorn is installed
    try:
        import uvicorn
    except ImportError:
        click.echo(click.style(' Error: uvicorn not installed. Run: pip install uvicorn', fg='red'))
        sys.exit(1)
    
    # Check if main.py exists
    main_py = Path(__file__).parent / 'main.py'
    if not main_py.exists():
        click.echo(click.style(f' Error: main.py not found at {main_py}', fg='red'))
        sys.exit(1)
    
    # Check if ffmpeg is installed
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        click.echo(click.style('  Warning: ffmpeg not found. Some features may not work.', fg='yellow'))
        click.echo('   Install ffmpeg: sudo apt install ffmpeg (Linux) or brew install ffmpeg (Mac)')
    
    url = f"http://{host}:{port}"
    
    if not no_browser:
        click.echo(click.style(f' Opening browser to {url}...', fg='green'))
        # Small delay to let server start
        threading.Thread(target=lambda: (time.sleep(2), webbrowser.open(url)), daemon=True).start()
    
    click.echo(click.style(f' Starting server on {url}', fg='green'))
    click.echo(click.style(' Press Ctrl+C to stop the server', fg='yellow'))
    
    # Run the FastAPI server
    try:
        uvicorn.run(
            "main:app",
            host=host,
            port=port,
            reload=debug,
            log_level="info" if debug else "warning"
        )
    except KeyboardInterrupt:
        click.echo(click.style('\n Server stopped. Goodbye!', fg='cyan'))
    except Exception as e:
        click.echo(click.style(f' Error: {e}', fg='red'))
        sys.exit(1)

if __name__ == '__main__':
    # Import threading here to avoid circular imports
    import threading
    main()