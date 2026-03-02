from email.quoprimime import quote
from pathlib import Path
from fastapi import FastAPI, Form, BackgroundTasks, Response, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp
import os
import uuid
import threading
from threading import Lock
import time
import urllib.request
import urllib.error
import re
import subprocess
import json
from fastapi.staticfiles import StaticFiles
import socket
import mimetypes
from urllib.parse import unquote
import tempfile
import shutil
from starlette.responses import StreamingResponse
import aiofiles
from cachetools import cached, TTLCache
import aiocache
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # project root
WEB_DIR = BASE_DIR / "web"
TEMP_DOWNLOAD_FOLDER = BASE_DIR / "temp_downloads"  # Temporary storage
THUMBNAIL_FOLDER = BASE_DIR / "thumbnails"
COOKIES_FILE_PATH = BASE_DIR / "cookies.txt"

print(f"looking for cookies file at: {COOKIES_FILE_PATH}")
print(f"cookie file exists: {COOKIES_FILE_PATH.exists()}")
print(f"BASE_DIR: {BASE_DIR}")
print(f"WEB_DIR: {WEB_DIR}")
print(f"TEMP_DOWNLOAD_FOLDER: {TEMP_DOWNLOAD_FOLDER}")
print(f"COOKIES_FILE_PATH: {COOKIES_FILE_PATH}")

# Create folders if missing
TEMP_DOWNLOAD_FOLDER.mkdir(exist_ok=True)
THUMBNAIL_FOLDER.mkdir(exist_ok=True)

# Create web folder if it doesn't exist
WEB_DIR.mkdir(exist_ok=True)
# Limit quality for faster downloads

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
print(f"\n Server is accessible at:")
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
        Path(__file__).parent / "web" / "index.html",
    ]
    
    for path in possible_paths:
        if path.exists():
            print(f"Found index.html at: {path}")
            return path.read_text(encoding="utf-8")
    
    return HTMLResponse(content="<h1>Video Downloader</h1><p>index.html not found</p>", status_code=200)

# Serve JS & CSS
@app.get("/app.js")
async def get_app_js():
    possible_paths = [
        WEB_DIR / "app.js",
        BASE_DIR / "web" / "app.js",
        BASE_DIR / "app.js",
        Path(__file__).parent / "app.js",
        Path(__file__).parent / "web" / "app.js",
    ]
    
    for path in possible_paths:
        if path.exists():
            return FileResponse(path, media_type="application/javascript")
    
    return JSONResponse(status_code=404, content={"error": "app.js not found"})

@app.get("/styles.css")
async def get_styles_css():
    possible_paths = [
        WEB_DIR / "styles.css",
        BASE_DIR / "web" / "styles.css",
        BASE_DIR / "styles.css",
        Path(__file__).parent / "styles.css",
        Path(__file__).parent / "web" / "styles.css",
    ]
    
    for path in possible_paths:
        if path.exists():
            return FileResponse(path, media_type="text/css")
    
    return JSONResponse(status_code=404, content={"error": "styles.css not found"})

# Serve sw.js
@app.get("/sw.js")
async def get_sw_js():
    possible_paths = [
        WEB_DIR / "sw.js",
        BASE_DIR / "web" / "sw.js",
        BASE_DIR / "sw.js",
        Path(__file__).parent / "sw.js",
        Path(__file__).parent / "web" / "sw.js",
    ]
    
    for path in possible_paths:
        if path.exists():
            return FileResponse(path, media_type="application/javascript")
    
    return JSONResponse(status_code=404, content={"error": "sw.js not found"})

@app.get("/icons/{filename}")
async def get_icon(filename: str):
    """Serve icon files"""
    filename = os.path.basename(filename)
    icon_path = WEB_DIR / "icons" / filename
    
    if icon_path.exists():
        return FileResponse(icon_path, media_type='image/png')
    
    return JSONResponse(status_code=404, content={"error": "Icon not found"})

# Global progress store with lock for thread safety
progress_store = {}
progress_lock = Lock()
file_metadata = {}

# Clean up old temp files every hour
AUTO_DELETE_AFTER = 3600  # 1 hour

def auto_cleanup():
    while True:
        now = time.time()
        # Clean temp downloads
        for file in TEMP_DOWNLOAD_FOLDER.glob("*"):
            if file.is_file():
                if now - file.stat().st_mtime > AUTO_DELETE_AFTER:
                    try:
                        file.unlink()
                        print(f"Cleaned up old temp file: {file.name}")
                    except:
                        pass
        
        # Clean thumbnails
        for thumb in THUMBNAIL_FOLDER.glob("*"):
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
    """Remove invalid characters from filename but keep it readable"""
    # Replace problematic characters but keep the filename intact
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Remove extra spaces
    filename = re.sub(r'\s+', ' ', filename)
    return filename.strip()

def download_task(job_id, url, format_option):
    def progress_hook(d):
        with progress_lock:
            if d['status'] == 'downloading':
                # Extract percentage from string like "45.2%"
                percent_str = d.get('_percent_str', '0%').strip()
                percent_str = re.sub(r'\x1b\[[0-9;]*m', '', percent_str)
                percent_match = re.search(r'(\d+(?:\.\d+)?)', percent_str)
                percent = percent_match.group(1) if percent_match else '0'
                
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
    
    if 'instagram.com' in url:

        if format_option == "best":
            actual_format = "best[ext=mp4]/best" 
        elif format_option == "1080":
            actual_format = "best[height<=1080][ext=mp4]/best[height<=1080]/best"
        elif format_option == "720":
            actual_format = "best[height<=720][ext=mp4]/best[height<=720]/best"
        else:
            actual_format = format_map.get(format_option, "best")
    else:
        actual_format = format_map.get(format_option, "best")

    actual_format = format_map.get(format_option, "best")

    # Base options - Use temp folder with sanitized filename
    ydl_opts = {
        'outtmpl': str(TEMP_DOWNLOAD_FOLDER / '%(title)s.%(ext)s'),
        'format': actual_format,
        'progress_hooks': [progress_hook],
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'ignoreerrors': True,
        'no_color': True,
        'geo_bypass': True,
        'windowsfilenames': True,
        'concurrent_fragment_downloads': 5,
        'fragment_retries': 3,
        'file_access_retries': 3,
        'format': 'best[height<=1080]',
        'buffersize': 1024,  
        'http_chunk_size': 10_485_760,
        'throttledratelimit': 10_000_000,
        'sleep_interval': 0,  
        'max_sleep_interval': 0,
        'sleep_interval_requests': 0,
        'cookiefile': str(COOKIES_FILE_PATH),
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
            try:
                info = ydl.extract_info(url, download=False)
            except Exception as e:
                if "Request format is not available" in str(e):
                    print(f"Requested format is not available for this video...")
                    ydl_opts['format'] = "best"
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl2:
                        info = ydl2.extract_info(url, download=False)
                else:        
                    raise Exception(f"Failed to extract video info: {e}")
            
            if not info:
                raise Exception("Could not extract video info")
            
            # Handle playlist
            if 'entries' in info and info['entries']:
                info = info['entries'][0]
            
            # Get the sanitized filename that will be created
            video_filename = ydl.prepare_filename(info)
            video_basename = os.path.basename(video_filename)
            
            # Handle audio extension change
            if format_option == "audio":
                video_basename = video_basename.rsplit('.', 1)[0] + '.mp3'
            
            # Update progress with title
            with progress_lock:
                if job_id in progress_store:
                    progress_store[job_id]["title"] = info.get('title', 'Unknown')
                else:
                    progress_store[job_id] = {
                        "status": "starting",
                        "percent": "0",
                        "title": info.get('title', 'Unknown')
                    }
            
            print(f"Starting download: {info.get('title', 'Unknown')}")
            print(f"Expected filename: {video_basename}")
            
            # Download the video
            ydl.download([url])
            
            # Wait a moment for file to be fully written
            time.sleep(2)
            
            # Find the actual file (sometimes yt-dlp changes the filename)
            actual_path = TEMP_DOWNLOAD_FOLDER / video_basename
            if not actual_path.exists():
                # Try to find the actual file by extension and modification time
                if format_option == "audio":
                    files = list(TEMP_DOWNLOAD_FOLDER.glob("*.mp3")) + list(TEMP_DOWNLOAD_FOLDER.glob("*.m4a"))
                else:
                    files = list(TEMP_DOWNLOAD_FOLDER.glob("*.mp4")) + list(TEMP_DOWNLOAD_FOLDER.glob("*.webm")) + list(TEMP_DOWNLOAD_FOLDER.glob("*.mkv"))
                
                # Filter out partial/temp files
                files = [f for f in files if not any(ext in f.name for ext in ['.part', '.ytdl', '.temp'])]
                
                if files:
                    # Get the most recently modified file
                    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                    actual_path = files[0]
                    video_basename = actual_path.name
                    print(f"Found actual file: {video_basename}")
                else:
                    raise Exception("Downloaded file not found")
            
            file_size = actual_path.stat().st_size
            
            # Download and save thumbnail (optional)
            thumbnail_url = None
            if info.get('thumbnail'):
                try:
                    thumb_url = info['thumbnail']
                    req = urllib.request.Request(thumb_url, headers={'User-Agent': 'Mozilla/5.0'})
                    
                    with urllib.request.urlopen(req, timeout=10) as response:
                        # Save thumbnail temporarily
                        thumb_filename = f"thumb_{job_id}.jpg"
                        thumb_path = THUMBNAIL_FOLDER / thumb_filename
                        
                        with open(thumb_path, 'wb') as f:
                            f.write(response.read())
                        
                        thumbnail_url = f"/thumbnails/{thumb_filename}"
                except Exception as e:
                    print(f"Thumbnail download failed: {e}")
            
            # Store metadata with the actual filename
            file_metadata[video_basename] = {
                'thumbnail': thumbnail_url,
                'title': info.get('title', 'Unknown'),
                'uploader': info.get('uploader', 'Unknown'),
                'duration': info.get('duration', 0),
                'filename': video_basename,
                'file_size': file_size,
                'download_url': f"/download-file/{video_basename}"
            }
            
            # Mark as finished with the correct filename
            with progress_lock:
                progress_store[job_id] = {
                    "status": "finished",
                    "filename": video_basename,
                    "title": info.get('title', 'Unknown'),
                    "percent": "100",
                    "download_url": f"/download-file/{video_basename}"
                }
            
            print(f"✓ Download completed: {video_basename} ({file_size:,} bytes)")
            
    except Exception as e:
        with progress_lock:
            progress_store[job_id] = {
                "status": "error",
                "error": str(e)
            }
        print(f"✗ Download error: {e}")
        import traceback
        traceback.print_exc()

@app.post("/preview")
async def preview_video(url: str = Form(...)):
    """Get video information without downloading"""
    try:
        print(f"Preview request for URL: {url}")
        print(f"using cookies file: {COOKIES_FILE_PATH} (exists: {COOKIES_FILE_PATH.exists()})")
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'ignoreerrors': True,
            'no_color': True,
            'geo_bypass': True,
            'cookiefile': str(COOKIES_FILE_PATH),
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            return JSONResponse(status_code=400, content={"error": "Could not extract video information"})

        # Handle playlist
        if 'entries' in info and info['entries']:
            info = info['entries'][0]

        # Format duration
        duration = info.get('duration')
        if duration is not None:
            try:
                duration = int(float(duration))
                minutes = duration // 60
                seconds = duration % 60
                if minutes >= 60:
                    hours = minutes // 60
                    minutes = minutes % 60
                    duration_str = f"{hours}:{minutes:02d}:{seconds:02d}"
                else:
                    duration_str = f"{minutes}:{seconds:02d}"
            except (ValueError, TypeError):
                duration_str = "Unknown"
        else:
            duration_str = "Unknown"

        # Format file size
        filesize = info.get('filesize') or info.get('filesize_approx')
        if filesize:
            try:
                filesize = float(filesize)
                if filesize > 1024 * 1024 * 1024:
                    filesize_str = f"{filesize / (1024*1024*1024):.1f} GB"
                elif filesize > 1024 * 1024:
                    filesize_str = f"{filesize / (1024*1024):.1f} MB"
                else:
                    filesize_str = f"{filesize / 1024:.1f} KB"
            except (ValueError, TypeError):
                filesize_str = "Unknown"
        else:
            filesize_str = "Unknown"

        # Get thumbnail
        thumbnail = info.get('thumbnail')
        if not thumbnail and info.get('thumbnails'):
            thumbnails = info['thumbnails']
            if thumbnails:
                thumbnail = thumbnails[-1].get('url')

        # Format view count
        view_count = info.get('view_count', 0)
        try:
            view_count = int(float(view_count))
            if view_count > 1000000:
                view_str = f"{view_count/1000000:.1f}M"
            elif view_count > 1000:
                view_str = f"{view_count/1000:.1f}K"
            else:
                view_str = str(view_count)
        except (ValueError, TypeError):
            view_str = "0"

        return {
            "title": info.get('title', 'Unknown'),
            "thumbnail": thumbnail,
            "duration": duration_str,
            "filesize": filesize_str,
            "uploader": info.get('uploader', info.get('channel', 'Unknown')),
            "view_count": view_str,
        }
        
    except Exception as e:
        print(f"Preview error: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/start-download")
async def start_download(background_tasks: BackgroundTasks,
                         url: str = Form(...),
                         quality: str = Form(...)):

    if not url or not url.strip():
        return JSONResponse(status_code=400, content={"error": "URL is required"})

    job_id = str(uuid.uuid4())

    with progress_lock:
        progress_store[job_id] = {
            "status": "starting",
            "percent": "0",
            "message": "Initializing download..."
        }

    background_tasks.add_task(download_task, job_id, url.strip(), quality)

    return {"job_id": job_id}

@app.get("/progress/{job_id}")
async def get_progress(job_id: str):
    with progress_lock:
        if job_id in progress_store:
            return JSONResponse(
                content=progress_store[job_id],
                headers={"Access-Control-Allow-Origin": "*"}
            )
    
    return JSONResponse(
        content={"status": "unknown"},
        headers={"Access-Control-Allow-Origin": "*"}
    )

@app.get("/files")
async def list_files():
    """List recently downloaded files (still on server)"""
    try:
        files = []
        for f in TEMP_DOWNLOAD_FOLDER.glob("*"):
            if f.is_file() and not any([
                f.name.endswith(('.jpg', '.jpeg', '.png', '.webp', '.part', '.ytdl')),
                f.name.startswith('.')
            ]):
                # Only show files from last hour
                if time.time() - f.stat().st_mtime < 3600:
                    # Also store in metadata if not already there
                    if f.name not in file_metadata:
                        file_metadata[f.name] = {
                            'title': f.name.rsplit('.', 1)[0],
                            'filename': f.name,
                            'file_size': f.stat().st_size
                        }
                    files.append(f.name)
        
        return JSONResponse(
            content=files,
            headers={"Access-Control-Allow-Origin": "*"}
        )
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/download-file/{filename:path}")
async def download_file(filename: str):
    """Download a file to the user's device"""
    try:
        # URL decode the filename
        filename = unquote(filename)
        filename = os.path.basename(filename)
        
        print(f"Looking for file: {filename}")
        
        # First try exact match
        path = TEMP_DOWNLOAD_FOLDER / filename
        
        if not path.exists():
            print(f"Exact match not found: {path}")
            
            # Try to find by partial match (remove special characters)
            # Get all mp4/mp3 files
            all_files = list(TEMP_DOWNLOAD_FOLDER.glob("*.mp4")) + \
                       list(TEMP_DOWNLOAD_FOLDER.glob("*.mp3")) + \
                       list(TEMP_DOWNLOAD_FOLDER.glob("*.webm"))
            
            # Get the base filename without extension
            base_name = filename.rsplit('.', 1)[0] if '.' in filename else filename
            
            # Look for files that start with the base name
            matches = []
            for f in all_files:
                if f.name.startswith(base_name) or base_name in f.name:
                    matches.append(f)
            
            if matches:
                # Get the most recent match
                matches.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                path = matches[0]
                filename = path.name
                print(f"Found match: {filename}")
            else:
                # Last resort: return the most recent file
                if all_files:
                    all_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                    path = all_files[0]
                    filename = path.name
                    print(f"Using most recent file: {filename}")
                else:
                    return JSONResponse(status_code=404, content={"error": "File not found"})

        file_size = path.stat().st_size
        
        async def interfile():
            async with aiofiles.open(path, 'rb') as f:
                while chunk := await f.read(1024 * 1024):  # 1 MB chunks
                    yield chunk

        # Determine media type
        if filename.endswith('.mp4'):
            media_type = 'video/mp4'
        elif filename.endswith('.mp3'):
            media_type = 'audio/mpeg'
        elif filename.endswith('.webm'):
            media_type = 'video/webm'
        else:
            media_type = 'application/octet-stream'

        print(f"Serving file: {filename} ({file_size:,} bytes)")
        
        # Simple filename for header
        safe_filename = filename.encode('ascii', 'ignore').decode('ascii')
        if not safe_filename:
            safe_filename = "video.mp4"
        
        return FileResponse(
            path=path,
            media_type=media_type,
            headers={
                "Content-Disposition": f"attachment; filename=\"{safe_filename}\"",
                "Content-Length": str(file_size),
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Expose-Headers": "Content-Disposition",
            }
        )
        
    except Exception as e:
        print(f"Download error: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/thumbnails/{filename}")
async def get_thumbnail(filename: str):
    filename = os.path.basename(filename)
    path = THUMBNAIL_FOLDER / filename
    
    if path.exists():
        return FileResponse(path, media_type='image/jpeg')
    
    return JSONResponse(status_code=404, content={"error": "Thumbnail not found"})

@app.get("/device-info")
async def device_info():
    """Return device info for compatibility"""
    return {
        "device": "web",
        "file_count": len(list(TEMP_DOWNLOAD_FOLDER.glob("*"))),
        "message": "Files are downloaded directly to your device"
    }

@app.get("/debug/cookies")
async def debug_cookies():
    """Detailed cookie debugging information"""
    result = {
        "cookies_file_path": str(COOKIES_FILE_PATH),
        "cookies_file_exists": COOKIES_FILE_PATH.exists(),
        "cookies_file_size": None,
        "cookies_file_permissions": None,
        "cookies_file_format_valid": False,
        "cookies_first_10_lines": [],
        "cookies_in_ydl_format": False,
    }
    
    if COOKIES_FILE_PATH.exists():
        result["cookies_file_size"] = COOKIES_FILE_PATH.stat().st_size
        
        # Check file permissions
        try:
            with open(COOKIES_FILE_PATH, 'r') as f:
                lines = f.readlines()
                result["cookies_file_permissions"] = "readable"
                result["cookies_first_10_lines"] = [line.strip() for line in lines[:10] if line.strip()]
                
                # Check if it's in Netscape format
                if lines and lines[0].strip().startswith('# Netscape'):
                    result["cookies_file_format_valid"] = True
        except Exception as e:
            result["cookies_file_permissions"] = f"error: {str(e)}"
    
    # Test if yt-dlp can load the cookies
    try:
        ydl_opts = {
            'quiet': True,
            'cookiefile': str(COOKIES_FILE_PATH),
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Just test if cookies load without error
            result["cookies_in_ydl_format"] = True
    except Exception as e:
        result["cookies_in_ydl_format"] = False
        result["ydl_error"] = str(e)
    
    # Try a test extraction with cookies
    try:
        test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        ydl_opts = {
            'quiet': True,
            'cookiefile': str(COOKIES_FILE_PATH),
            'extract_flat': True,  # Don't download, just extract info
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(test_url, download=False)
            result["test_extraction"] = "successful" if info else "failed"
    except Exception as e:
        result["test_extraction"] = f"failed: {str(e)}"
    
    return result

@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# Cache video metadata to avoid repeated extraction
@cached(cache=TTLCache(maxsize=100, ttl=300))
def get_video_info(url):
    with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
        return ydl.extract_info(url, download=False)

# Use connection pooling for HTTP requests
session = requests.Session()
retry = Retry(connect=3, backoff_factor=0.5)
adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=retry)
session.mount('http://', adapter)
session.mount('https://', adapter)

if __name__ == "__main__":
    import uvicorn
    PORT = int(os.getenv("PORT", 8000))
    print(f"Starting Video Downloader...")
    print(f"Local access: http://127.0.0.1:{PORT}")
    print(f"Network access: http://{LOCAL_IP}:{PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)