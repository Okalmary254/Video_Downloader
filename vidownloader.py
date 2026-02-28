
"""
Video Downloader CLI - Launch the web UI in your browser
"""

import click
import subprocess
import sys
import os
import webbrowser
import time
import threading
from pathlib import Path

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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
    click.echo(click.style('║         Video Downloader Web UI        ║', fg='cyan', bold=True))
    click.echo(click.style('╚════════════════════════════════════════╝', fg='cyan', bold=True))
    
    # Get the directory where this script is located
    script_dir = Path(__file__).parent.absolute()
    
    # Check if main.py exists
    main_py = script_dir / 'main.py'
    if not main_py.exists():
        click.echo(click.style(f' Error: main.py not found at {main_py}', fg='red'))
        click.echo(f"Current directory: {os.getcwd()}")
        click.echo(f"Script directory: {script_dir}")
        sys.exit(1)
    
    # Check if uvicorn is installed
    try:
        import uvicorn
    except ImportError:
        click.echo(click.style(' Error: uvicorn not installed. Run: pip install uvicorn', fg='red'))
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
    
    # Change to the script directory before running
    os.chdir(script_dir)
    
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
    main()