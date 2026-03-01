from email.quoprimime import quote
from pathlib import Path
from fastapi import FastAPI, Form, BackgroundTasks, Response
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
import yt_dlp
import os
import uuid
import threading
from threading import Lock
from collections import defaultdict
import time
import urllib.request
import urllib.error
import re
import subprocess
import json
from fastapi.staticfiles import StaticFiles
import socket
import mimetypes

app = FastAPI()

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # project root
WEB_DIR = BASE_DIR / "web"
DOWNLOAD_FOLDER = BASE_DIR / "downloads"
THUMBNAIL_FOLDER = BASE_DIR / "thumbnails"

# Create folders if missing
DOWNLOAD_FOLDER.mkdir(exist_ok=True)
THUMBNAIL_FOLDER.mkdir(exist_ok=True)

# Create web folder if it doesn't exist
WEB_DIR.mkdir(exist_ok=True)

# Mount static files
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

# Get local IP address for network access
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

LOCAL_IP = get_local_ip()
print(f"\n🌐 Server is accessible at:")
print(f"   Local: http://127.0.0.1:8000")
print(f"   Network: http://{LOCAL_IP}:8000 (for mobile devices)\n")

# Serve index.html
@app.get("/", response_class=HTMLResponse)
async def home():
    # Try multiple possible locations for index.html
    possible_paths = [
        WEB_DIR / "index.html",
        BASE_DIR / "web" / "index.html",
        BASE_DIR / "index.html",
        Path(__file__).parent / "index.html",
    ]
    
    for path in possible_paths:
        if path.exists():
            print(f"Found index.html at: {path}")
            return path.read_text(encoding="utf-8")
    
    # If not found, return debug info
    html_content = f"""
    <html>
    <head><title>Video Downloader</title></head>
    <body>
        <h1>Video Downloader</h1>
        <p>Server is running but index.html not found</p>
        <p>Searched in:</p>
        <ul>
            {"".join(f'<li>{p}</li>' for p in possible_paths)}
        </ul>
        <p>Current directory: {os.getcwd()}</p>
        <p>Files in current directory:</p>
        <ul>
            {"".join(f'<li>{f}</li>' for f in os.listdir('.') if f.endswith('.html'))}
        </ul>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)

# Serve JS & CSS
@app.get("/app.js")
async def get_app_js():
    possible_paths = [
        WEB_DIR / "app.js",
        BASE_DIR / "web" / "app.js",
        BASE_DIR / "app.js",
        Path(__file__).parent / "app.js",
    ]
    
    for path in possible_paths:
        if path.exists():
            return FileResponse(path, media_type="application/javascript")
    
    return JSONResponse(
        status_code=404, 
        content={"error": "app.js not found", "searched": [str(p) for p in possible_paths]}
    )

@app.get("/styles.css")
async def get_styles_css():
    possible_paths = [
        WEB_DIR / "styles.css",
        BASE_DIR / "web" / "styles.css",
        BASE_DIR / "styles.css",
        Path(__file__).parent / "styles.css",
    ]
    
    for path in possible_paths:
        if path.exists():
            return FileResponse(path, media_type="text/css")
    
    return JSONResponse(
        status_code=404, 
        content={"error": "styles.css not found", "searched": [str(p) for p in possible_paths]}
    )

# Global progress store with lock for thread safety
progress_store = {}
progress_lock = Lock()
file_metadata = {}

AUTO_DELETE_AFTER = 3600  # 1 hour

def auto_cleanup():
    while True:
        now = time.time()
        # Clean downloads
        for file in os.listdir(DOWNLOAD_FOLDER):
            path = DOWNLOAD_FOLDER / file
            if path.is_file():
                if now - path.stat().st_mtime > AUTO_DELETE_AFTER:
                    try:
                        path.unlink()
                        print(f"Cleaned up old file: {file}")
                    except:
                        pass
        
        # Clean thumbnails
        for thumb in THUMBNAIL_FOLDER.iterdir():
            if thumb.is_file():
                if time.time() - thumb.stat().st_mtime > AUTO_DELETE_AFTER:
                    try:
                        thumb.unlink()
                        print(f"Cleaned up old thumbnail: {thumb.name}")
                    except:
                        pass
        
        time.sleep(300)

threading.Thread(target=auto_cleanup, daemon=True).start()

def sanitize_filename(filename):
    """Remove invalid characters from filename"""
    return re.sub(r'[<>:"/\\|?*]', '', filename)

def download_task(job_id, url, format_option):
    def progress_hook(d):
        with progress_lock:
            if d['status'] == 'downloading':
                # Extract percentage from string like "45.2%"
                percent_str = d.get('_percent_str', '0%').strip()
                # Remove color codes if present
                percent_str = re.sub(r'\x1b\[[0-9;]*m', '', percent_str)
                # Extract numeric value
                percent_match = re.search(r'(\d+(?:\.\d+)?)', percent_str)
                percent = percent_match.group(1) if percent_match else '0'
                
                # Update progress store
                progress_store[job_id] = {
                    "status": "downloading",
                    "percent": percent,
                    "speed": d.get('_speed_str', 'N/A').strip(),
                    "eta": d.get('_eta_str', 'N/A').strip()
                }
            elif d['status'] == 'finished':
                if job_id in progress_store:
                    progress_store[job_id]["status"] = "processing"
                    progress_store[job_id]["filename"] = os.path.basename(d.get('filename', ''))

    # Format mapping for yt-dlp
    format_map = {
        "best": "bestvideo+bestaudio/best",
        "1080": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best[height<=1080]",
        "720": "bestvideo[height<=720]+bestaudio/best[height<=720]/best[height<=720]",
        "audio": "bestaudio/best"
    }
    
    actual_format = format_map.get(format_option, "best")

    # Base options
    ydl_opts = {
        'outtmpl': str(DOWNLOAD_FOLDER / '%(title)s.%(ext)s'),
        'format': actual_format,
        'progress_hooks': [progress_hook],
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'ignoreerrors': True,
        'no_color': True,
    }

    # Add post-processors for specific formats
    if format_option == "audio":
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    else:
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegVideoRemuxer',
            'preferedformat': 'mp4',
        }]

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract info first
            info = ydl.extract_info(url, download=False)
            
            if not info:
                raise Exception("Could not extract video info")
            
            # Handle playlist
            if 'entries' in info and info['entries']:
                info = info['entries'][0]
            
            # Get the actual filename that will be created
            video_filename = ydl.prepare_filename(info)
            video_basename = os.path.basename(video_filename)
            
            # Handle audio extension change
            if format_option == "audio":
                video_basename = video_basename.rsplit('.', 1)[0] + '.mp3'
            
            # Update progress with title
            with progress_lock:
                if job_id in progress_store:
                    progress_store[job_id]["title"] = info.get('title', 'Unknown')
            
            # Download the video
            ydl.download([url])
            
            # Wait a moment for file to be fully written
            time.sleep(1)
            
            # Verify file exists
            actual_path = DOWNLOAD_FOLDER / video_basename
            if not actual_path.exists():
                # Try to find the actual file
                files = list(DOWNLOAD_FOLDER.glob("*.mp4")) + list(DOWNLOAD_FOLDER.glob("*.mp3"))
                if files:
                    video_basename = files[-1].name
                    print(f"Found actual file: {video_basename}")
            
            # Download and save thumbnail
            if info.get('thumbnail'):
                try:
                    thumb_url = info['thumbnail']
                    
                    req = urllib.request.Request(
                        thumb_url,
                        headers={
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                        }
                    )
                    
                    with urllib.request.urlopen(req, timeout=15) as response:
                        # Determine thumbnail extension
                        content_type = response.headers.get('content-type', '')
                        if 'jpeg' in content_type or 'jpg' in content_type:
                            thumb_ext = 'jpg'
                        elif 'png' in content_type:
                            thumb_ext = 'png'
                        elif 'webp' in content_type:
                            thumb_ext = 'webp'
                        else:
                            thumb_ext = 'jpg'
                        
                        # Save thumbnail
                        thumb_filename = f"{job_id}.{thumb_ext}"
                        thumb_path = THUMBNAIL_FOLDER / thumb_filename
                        
                        with open(thumb_path, 'wb') as f:
                            f.write(response.read())
                        
                        # Store metadata
                        file_metadata[video_basename] = {
                            'thumbnail': f"/thumbnails/{thumb_filename}",
                            'title': info.get('title', 'Unknown'),
                            'uploader': info.get('uploader', 'Unknown'),
                            'duration': info.get('duration', 0),
                            'filename': video_basename
                        }
                        
                        print(f"Thumbnail saved for: {video_basename}")
                except Exception as e:
                    print(f"Thumbnail download failed: {e}")
            
            # Mark as finished
            with progress_lock:
                progress_store[job_id] = {
                    "status": "finished",
                    "filename": video_basename,
                    "title": info.get('title', 'Unknown')
                }
            
            print(f"Download completed: {video_basename}")
            
    except Exception as e:
        with progress_lock:
            progress_store[job_id] = {
                "status": "error",
                "error": str(e)
            }
        print(f"Download error: {e}")
        import traceback
        traceback.print_exc()

# [Rest of your endpoints remain the same until the download_file endpoint]

@app.api_route("/download-file/{filename:path}", methods=["GET", "HEAD"])
async def download_file(filename: str):
    """Download a file with proper headers for all devices"""
    try:
        # Prevent directory traversal
        filename = os.path.basename(filename)
        
        # URL decode the filename first (if it was encoded)
        from urllib.parse import unquote
        filename = unquote(filename)
        
        path = DOWNLOAD_FOLDER / filename

        print(f"Download requested: {filename}")
        print(f"Full path: {path}")
        print(f"File exists: {path.exists()}")

        if not path.exists():
            # Try to find the file with different extensions
            stem = Path(filename).stem
            files = list(DOWNLOAD_FOLDER.glob(f"{stem}.*"))
            if files:
                path = files[0]
                filename = path.name
                print(f"Found alternative: {filename}")
            else:
                return JSONResponse(
                    status_code=404,
                    content={"error": f"File not found: {filename}"}
                )

        # Get file size for logging
        file_size = path.stat().st_size
        print(f"Serving file: {filename} ({file_size} bytes)")

        # Determine media type
        media_type = mimetypes.guess_type(str(path))[0]
        if not media_type:
            if filename.endswith('.mp4'):
                media_type = 'video/mp4'
            elif filename.endswith('.mp3'):
                media_type = 'audio/mpeg'
            elif filename.endswith('.webm'):
                media_type = 'video/webm'
            else:
                media_type = 'application/octet-stream'

        # For the Content-Disposition header, we need to handle special characters
        # Use a simple ASCII fallback for the filename in the header
        ascii_filename = ''.join(c for c in filename if ord(c) < 128)
        if not ascii_filename:  # If no ASCII chars, use a default
            ascii_filename = "video.mp4"
        
        # Create response with proper headers
        response = FileResponse(
            path=path,
            media_type=media_type,
            filename=ascii_filename,  # Use ASCII version for the response
            headers={
                "Content-Disposition": f"attachment; filename=\"{ascii_filename}\"",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
                "Access-Control-Allow-Headers": "*",
                "Content-Length": str(file_size),
                "Cache-Control": "no-cache",
                "Accept-Ranges": "bytes",
            }
        )
        
        return response
        
    except Exception as e:
        print(f"Download error: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": f"Download failed: {str(e)}"}
        )

# Add OPTIONS method for CORS preflight
@app.options("/download-file/{filename:path}")
async def download_file_options(filename: str):
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        }
    )
# Add OPTIONS method for CORS preflight
@app.options("/download-file/{filename:path}")
async def download_file_options(filename: str):
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        }
    )

@app.get("/files")
async def list_files():
    try:
        files = []
        for f in DOWNLOAD_FOLDER.glob("*"):
            if f.is_file() and not any([
                f.name.endswith(('.jpg', '.jpeg', '.png', '.webp', '.part', '.ytdl')),
                f.name.startswith('.')
            ]):
                file_info = {
                    'name': f.name,
                    'size': f.stat().st_size,
                    'modified': f.stat().st_mtime,
                    'metadata': file_metadata.get(f.name, {})
                }
                files.append(file_info)
        
        # Sort by modification time (newest first)
        files.sort(key=lambda x: x['modified'], reverse=True)
        
        # Return just the filenames for compatibility
        return [f['name'] for f in files]
        
    except Exception as e:
        print(f"Error listing files: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.get("/file-info")
async def get_file_info():
    """Get detailed file information including download URLs"""
    try:
        files = []
        for f in DOWNLOAD_FOLDER.glob("*"):
            if f.is_file() and not any([
                f.name.endswith(('.jpg', '.jpeg', '.png', '.webp', '.part', '.ytdl')),
                f.name.startswith('.')
            ]):
                file_info = {
                    'name': f.name,
                    'size': f.stat().st_size,
                    'modified': f.stat().st_mtime,
                    'download_url': f"/download-file/{quote(f.name)}",
                    'metadata': file_metadata.get(f.name, {})
                }
                files.append(file_info)
        
        files.sort(key=lambda x: x['modified'], reverse=True)
        return files
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.get("/debug/paths")
async def debug_paths():
    """Debug endpoint to check file paths"""
    return {
        "base_dir": str(BASE_DIR),
        "web_dir": str(WEB_DIR),
        "download_folder": str(DOWNLOAD_FOLDER),
        "download_folder_exists": DOWNLOAD_FOLDER.exists(),
        "download_folder_contents": [str(f) for f in DOWNLOAD_FOLDER.iterdir()] if DOWNLOAD_FOLDER.exists() else [],
        "thumbnails_folder": str(THUMBNAIL_FOLDER),
        "file_metadata": file_metadata,
    }

# [Keep your existing preview, start_download, progress, etc. endpoints]

if __name__ == "__main__":
    import uvicorn
    PORT = int(os.getenv("PORT", 8000))
    print(f"Starting Video Downloader...")
    print(f"Local access: http://127.0.0.1:{PORT}")
    print(f"Network access: http://{LOCAL_IP}:{PORT} (for mobile)")
    print(f"Downloads folder: {DOWNLOAD_FOLDER}")
    print(f"Thumbnails folder: {THUMBNAIL_FOLDER}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)