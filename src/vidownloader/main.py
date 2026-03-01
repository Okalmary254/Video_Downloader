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
from urllib.parse import unquote

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store device info in request state
@app.middleware("http")
async def add_device_info(request: Request, call_next):
    """Middleware to add device info to request state"""
    user_agent = request.headers.get("user-agent", "")
    device_type = get_device_type(user_agent)
    request.state.device_type = device_type
    request.state.device_folder = get_device_folder(device_type)
    
    # Log every request with device info
    print(f"\n[{device_type.upper()}] {request.method} {request.url.path}")
    print(f"  User-Agent: {user_agent[:100]}...")
    
    response = await call_next(request)
    return response

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # project root
WEB_DIR = BASE_DIR / "web"
DOWNLOAD_FOLDER = BASE_DIR / "downloads"
THUMBNAIL_FOLDER = BASE_DIR / "thumbnails"

LAPTOP_DOWNLOAD_FOLDER = DOWNLOAD_FOLDER / "laptop"
MOBILE_DOWNLOAD_FOLDER = DOWNLOAD_FOLDER / "mobile"

print(f"BASE_DIR: {BASE_DIR}")
print(f"WEB_DIR: {WEB_DIR}")
print(f"DOWNLOAD_FOLDER: {DOWNLOAD_FOLDER}")

# Create folders if missing
DOWNLOAD_FOLDER.mkdir(exist_ok=True)
THUMBNAIL_FOLDER.mkdir(exist_ok=True)
LAPTOP_DOWNLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
MOBILE_DOWNLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

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
print(f"\n Server is accessible at:")
print(f"   Local: http://127.0.0.1:8000")
print(f"   Network: http://{LOCAL_IP}:8000 (for mobile devices)\n")

def get_device_type(user_agent: str):
    """Improved user agent check to determine device type"""
    user_agent = user_agent.lower()
    
    # More comprehensive mobile detection
    mobile_keywords = [
        'iphone', 'ipad', 'ipod', 'android', 'mobile', 'phone', 
        'blackberry', 'opera mini', 'opera mobi', 'nokia', 'symbian',
        'windows phone', 'palm', 'kindle', 'silk', 'playbook',
        'bb10', 'rim tablet', 'meego', 'smartphone'
    ]
    
    # Check for mobile
    for keyword in mobile_keywords:
        if keyword in user_agent:
            print(f"✅ Mobile detected via keyword: {keyword}")
            return "mobile"
    
    # Check for tablet (also mobile)
    tablet_keywords = ['tablet', 'ipad', 'kindle', 'playbook']
    for keyword in tablet_keywords:
        if keyword in user_agent:
            print(f" Tablet detected via keyword: {keyword}")
            return "mobile"
    
    # Check for Android without mobile (could be tablet)
    if 'android' in user_agent and 'mobile' not in user_agent:
        print(f" Android tablet detected")
        return "mobile"
    
    # Check for common desktop indicators
    desktop_keywords = ['windows nt', 'macintosh', 'linux x86', 'x11']
    for keyword in desktop_keywords:
        if keyword in user_agent:
            print(f" Desktop detected via keyword: {keyword}")
            return "laptop"
    
    # Default to laptop if no mobile indicators
    print(f" Unknown device, defaulting to laptop for: {user_agent[:100]}")
    return "laptop"

def get_device_folder(device_type: str) -> Path:
    """Get folder path based on device type"""
    if device_type == "mobile":
        return MOBILE_DOWNLOAD_FOLDER
    return LAPTOP_DOWNLOAD_FOLDER

# Debug endpoint to see device detection
@app.get("/debug/device")
async def debug_device(request: Request):
    """Debug endpoint to check device detection"""
    user_agent = request.headers.get("user-agent", "")
    device_type = get_device_type(user_agent)
    device_folder = get_device_folder(device_type)
    
    # List files in both folders
    laptop_files = [f.name for f in LAPTOP_DOWNLOAD_FOLDER.glob("*") if f.is_file() and not f.name.endswith(('.jpg', '.jpeg', '.png', '.webp'))]
    mobile_files = [f.name for f in MOBILE_DOWNLOAD_FOLDER.glob("*") if f.is_file() and not f.name.endswith(('.jpg', '.jpeg', '.png', '.webp'))]
    
    return {
        "user_agent": user_agent[:200],
        "device_type": device_type,
        "device_folder": str(device_folder),
        "laptop_folder": str(LAPTOP_DOWNLOAD_FOLDER),
        "mobile_folder": str(MOBILE_DOWNLOAD_FOLDER),
        "laptop_files": laptop_files,
        "mobile_files": mobile_files,
        "detection_method": "keyword based"
    }

# Debug endpoint to see all registered routes
@app.get("/debug/routes")
async def debug_routes():
    routes = []
    for route in app.routes:
        routes.append({
            "path": route.path,
            "name": route.name,
            "methods": list(route.methods) if hasattr(route, 'methods') else None
        })
    return {
        "routes": routes,
        "base_dir": str(BASE_DIR),
        "web_dir": str(WEB_DIR),
        "download_folder": str(DOWNLOAD_FOLDER),
        "download_folder_exists": DOWNLOAD_FOLDER.exists(),
        "download_folder_contents": [str(f) for f in DOWNLOAD_FOLDER.iterdir()] if DOWNLOAD_FOLDER.exists() else [],
    }

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
        <p><a href="/debug/routes">View debug routes</a></p>
        <p><a href="/debug/device">Check device detection</a></p>
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
        Path(__file__).parent / "web" / "app.js",
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
        Path(__file__).parent / "web" / "styles.css",
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
        # Clean laptop downloads
        for file in LAPTOP_DOWNLOAD_FOLDER.glob("*"):
            if file.is_file():
                if now - file.stat().st_mtime > AUTO_DELETE_AFTER:
                    try:
                        file.unlink()
                        print(f"Cleaned up old laptop file: {file.name}")
                    except:
                        pass
        
        # Clean mobile downloads
        for file in MOBILE_DOWNLOAD_FOLDER.glob("*"):
            if file.is_file():
                if now - file.stat().st_mtime > AUTO_DELETE_AFTER:
                    try:
                        file.unlink()
                        print(f"Cleaned up old mobile file: {file.name}")
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

def download_task(job_id, url, format_option, device_type, device_folder):
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
                    "eta": d.get('_eta_str', 'N/A').strip(),
                    "device": device_type
                }
            elif d['status'] == 'finished':
                if job_id in progress_store:
                    progress_store[job_id]["status"] = "processing"
                    progress_store[job_id]["filename"] = os.path.basename(d.get('filename', ''))
                    progress_store[job_id]["device"] = device_type

    # Format mapping for yt-dlp
    format_map = {
        "best": "bestvideo+bestaudio/best",
        "1080": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best[height<=1080]",
        "720": "bestvideo[height<=720]+bestaudio/best[height<=720]/best[height<=720]",
        "audio": "bestaudio/best"
    }
    
    actual_format = format_map.get(format_option, "best")

    # Base options - Use device_folder
    ydl_opts = {
        'outtmpl': str(device_folder / '%(title)s.%(ext)s'),
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
                    progress_store[job_id]["device"] = device_type
                else:
                    progress_store[job_id] = {
                        "status": "starting",
                        "percent": "0",
                        "title": info.get('title', 'Unknown'),
                        "device": device_type
                    }
            
            print(f"Starting download to {device_type.upper()} folder: {device_folder}")
            print(f"  Title: {info.get('title', 'Unknown')}")
            
            # Download the video
            ydl.download([url])
            
            # Wait a moment for file to be fully written
            time.sleep(3)
            
            # Verify file exists in device folder
            actual_path = device_folder / video_basename
            if not actual_path.exists():
                # Try to find the actual file in device folder with more file types
                if format_option == "audio":
                    files = list(device_folder.glob("*.mp3")) + list(device_folder.glob("*.m4a")) + list(device_folder.glob("*.opus"))
                else:
                    files = list(device_folder.glob("*.mp4")) + list(device_folder.glob("*.webm")) + list(device_folder.glob("*.mkv"))
                
                # Filter out partial/temp files
                files = [f for f in files if not any(ext in f.name for ext in ['.part', '.ytdl', '.temp'])]
                
                if files:
                    # Get the most recently modified file
                    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                    video_basename = files[0].name
                    actual_path = files[0]
                    print(f"Found actual file: {video_basename} in {device_type.upper()} folder")
                else:
                    raise Exception(f"Downloaded file not found in {device_type.upper()} folder")
            
            file_size = actual_path.stat().st_size
            print(f"✓ Verified file exists: {actual_path} (size: {file_size:,} bytes)")
            
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
                        
                        # Store metadata with device info
                        file_metadata[video_basename] = {
                            'thumbnail': f"/thumbnails/{thumb_filename}",
                            'title': info.get('title', 'Unknown'),
                            'uploader': info.get('uploader', 'Unknown'),
                            'duration': info.get('duration', 0),
                            'filename': video_basename,
                            'device': device_type,
                            'download_path': str(device_folder / video_basename),
                            'file_size': file_size
                        }
                        
                        print(f"✓ Thumbnail saved for: {video_basename} ({device_type.upper()})")
                except Exception as e:
                    print(f"⚠ Thumbnail download failed: {e}")
            
            # Mark as finished - KEEP THE PROGRESS STORE UPDATED
            with progress_lock:
                progress_store[job_id] = {
                    "status": "finished",
                    "filename": video_basename,
                    "title": info.get('title', 'Unknown'),
                    "device": device_type,
                    "percent": "100"
                }
            
            print(f"✓ Download completed: {video_basename} on {device_type.upper()}")
            print(f"  File location: {actual_path}")
            print(f"  File size: {file_size:,} bytes")
            
    except Exception as e:
        with progress_lock:
            progress_store[job_id] = {
                "status": "error",
                "error": str(e),
                "device": device_type
            }
        print(f"✗ Download error: {e}")
        import traceback
        traceback.print_exc()

@app.post("/preview")
async def preview_video(url: str = Form(...)):
    """
    Get video information without downloading
    """
    try:
        print(f"Preview request for URL: {url}")
        
        # Configure yt-dlp options for extraction only
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'force_generic_extractor': False,
            'ignoreerrors': True,
            'no_color': True,
            'geo_bypass': True,
            'geo_bypass_country': 'US',
        }
        
        # Try with different options if first attempt fails
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            print(f"First attempt failed: {e}")
            # Try with different options
            ydl_opts.update({
                'format': 'best',
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'referer': 'https://www.google.com',
            })
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

        if not info:
            return JSONResponse(
                status_code=400,
                content={"error": "Could not extract video information"}
            )

        # Handle playlist or single video
        if 'entries' in info and info['entries']:
            # It's a playlist - take first entry
            info = info['entries'][0]

        # Format duration
        duration = info.get('duration')
        if duration is not None and duration > 0:
            duration = int(duration)
            minutes = duration // 60
            seconds = duration % 60
            if minutes >= 60:
                hours = minutes // 60
                minutes = minutes % 60
                duration_str = f"{hours}:{minutes:02d}:{seconds:02d}"
            else:
                duration_str = f"{minutes}:{seconds:02d}"
        else:
            duration_str = "Unknown"

        # Format file size
        filesize = info.get('filesize') or info.get('filesize_approx')
        if filesize:
            filesize = float(filesize)
            if filesize > 1024 * 1024 * 1024:
                filesize_str = f"{filesize / (1024*1024*1024):.1f} GB"
            elif filesize > 1024 * 1024:
                filesize_str = f"{filesize / (1024*1024):.1f} MB"
            else:
                filesize_str = f"{filesize / 1024:.1f} KB"
        else:
            filesize_str = "Unknown"

        # Get best thumbnail
        thumbnail = info.get('thumbnail')
        thumbnails = info.get('thumbnails', [])
        if thumbnails and not thumbnail:
            # Filter out entries with None height/width
            valid_thumbnails = [t for t in thumbnails if t.get('height') is not None or t.get('width') is not None]
            if valid_thumbnails:
                valid_thumbnails.sort(
                    key=lambda x: (x.get('height') or 0, x.get('width') or 0), 
                    reverse=True
                )
                thumbnail = valid_thumbnails[0].get('url')
            elif thumbnails:
                # Fallback to first thumbnail if all have None dimensions
                thumbnail = thumbnails[0].get('url')

        # Format view count
        view_count = info.get('view_count', 0)
        if view_count:
            if view_count > 1000000:
                view_str = f"{view_count/1000000:.1f}M"
            elif view_count > 1000:
                view_str = f"{view_count/1000:.1f}K"
            else:
                view_str = str(view_count)
        else:
            view_str = "0"

        response_data = {
            "title": info.get('title', 'Unknown'),
            "thumbnail": thumbnail,
            "duration": duration_str,
            "filesize": filesize_str,
            "uploader": info.get('uploader', info.get('channel', 'Unknown')),
            "view_count": view_str,
            "like_count": info.get('like_count', 0),
            "description": info.get('description', '')[:200] + '...' if info.get('description') else '',
            "upload_date": info.get('upload_date', 'Unknown'),
            "extractor": info.get('extractor', 'Unknown'),
            "webpage_url": info.get('webpage_url', url)
        }
        
        print(f"Preview successful for: {response_data['title']}")
        return response_data
        
    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        print(f"DownloadError in preview: {error_msg}")
        return JSONResponse(
            status_code=400,
            content={"error": f"Could not fetch video info: {error_msg}"}
        )
    except yt_dlp.utils.ExtractorError as e:
        error_msg = str(e)
        print(f"ExtractorError in preview: {error_msg}")
        return JSONResponse(
            status_code=400,
            content={"error": f"Extractor failed: {error_msg}"}
        )
    except Exception as e:
        error_msg = str(e)
        print(f"Unexpected error in preview: {error_msg}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": f"Preview failed: {error_msg}"}
        )

@app.post("/start-download")
async def start_download(background_tasks: BackgroundTasks,
                         request: Request,
                         url: str = Form(...),
                         quality: str = Form(...)):

    # Validate URL
    if not url or not url.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "URL is required"}
        )

    job_id = str(uuid.uuid4())
    device_type = request.state.device_type
    device_folder = request.state.device_folder

    print(f"\n Starting download for {device_type.upper()}:")
    print(f"  Folder: {device_folder}")
    print(f"  Job ID: {job_id}")
    print(f"  URL: {url}")
    print(f"  Quality: {quality}")

    with progress_lock:
        progress_store[job_id] = {
            "status": "starting",
            "percent": "0",
            "message": f"Initializing download for {device_type}...",
            "device": device_type
        }

    background_tasks.add_task(download_task, job_id, url.strip(), quality, device_type, device_folder)

    return {"job_id": job_id, "device": device_type}

@app.get("/progress/{job_id}")
async def get_progress(job_id: str, request: Request):
    with progress_lock:
        if job_id in progress_store:
            # Always return the progress, even if finished
            return JSONResponse(
                content=progress_store[job_id],
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, OPTIONS",
                    "Access-Control-Allow-Headers": "*",
                    "Cache-Control": "no-cache",
                }
            )
    
    # Return unknown but with proper headers
    return JSONResponse(
        content={"status": "unknown", "job_id": job_id},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        }
    )

@app.options("/progress/{job_id}")
async def progress_options(job_id: str):
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        }
    )

@app.get("/files")
async def list_files(request: Request):
    """List files only for the requesting device"""
    try:
        device_type = request.state.device_type
        device_folder = request.state.device_folder
        
        print(f"\n Listing files for {device_type.upper()}:")
        print(f"  Folder: {device_folder}")
        print(f"  Folder exists: {device_folder.exists()}")
        
        if not device_folder.exists():
            print(f"  ⚠ Folder does not exist!")
            return JSONResponse(
                content=[],
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, OPTIONS",
                    "Access-Control-Allow-Headers": "*",
                    "Cache-Control": "no-cache",
                }
            )
        
        files = []
        for f in device_folder.iterdir():
            if f.is_file() and not any([
                f.name.endswith(('.jpg', '.jpeg', '.png', '.webp', '.part', '.ytdl', '.temp')),
                f.name.startswith('.')
            ]):
                files.append(f.name)
                print(f"  - {f.name} ({f.stat().st_size:,} bytes)")
        
        # Sort by modification time (newest first)
        files_with_time = [(f, (device_folder / f).stat().st_mtime) for f in files]
        files_with_time.sort(key=lambda x: x[1], reverse=True)
        
        print(f"  Total files: {len(files_with_time)}")
        
        return JSONResponse(
            content=[f[0] for f in files_with_time],
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, OPTIONS",
                "Access-Control-Allow-Headers": "*",
                "Cache-Control": "no-cache",
            }
        )
        
    except Exception as e:
        print(f"✗ Error listing files: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": str(e)},
            headers={
                "Access-Control-Allow-Origin": "*",
            }
        )

@app.options("/files")
async def files_options():
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        }
    )

@app.api_route("/download-file/{filename:path}", methods=["GET", "HEAD"])
async def download_file(filename: str, request: Request):
    """Download a file from the appropriate device folder"""
    try:
        # Prevent directory traversal
        filename = os.path.basename(filename)
        
        # URL decode the filename first (if it was encoded)
        filename = unquote(filename)
        
        # Get device-specific folder
        device_type = request.state.device_type
        device_folder = request.state.device_folder
        path = device_folder / filename

        print(f"Download requested: {filename} from {device_type.upper()} folder")
        print(f"Full path: {path}")
        print(f"File exists: {path.exists()}")

        if not path.exists():
            # Try the other device folder as fallback
            if device_type == "laptop":
                alt_path = MOBILE_DOWNLOAD_FOLDER / filename
                alt_device = "mobile"
            else:
                alt_path = LAPTOP_DOWNLOAD_FOLDER / filename
                alt_device = "laptop"
                
            if alt_path.exists():
                path = alt_path
                print(f"Found in {alt_device.upper()} folder: {alt_path}")
            else:
                return JSONResponse(
                    status_code=404,
                    content={"error": f"File not found: {filename}"}
                )

        # Get file size for logging
        file_size = path.stat().st_size
        print(f"Serving file: {filename} ({file_size} bytes)")

        # Determine media type
        media_type = None
        if filename.endswith('.mp4'):
            media_type = 'video/mp4'
        elif filename.endswith('.mp3'):
            media_type = 'audio/mpeg'
        elif filename.endswith('.webm'):
            media_type = 'video/webm'
        elif filename.endswith('.jpg') or filename.endswith('.jpeg'):
            media_type = 'image/jpeg'
        elif filename.endswith('.png'):
            media_type = 'image/png'
        else:
            media_type = mimetypes.guess_type(str(path))[0] or 'application/octet-stream'

        # Create response
        response = FileResponse(
            path=path,
            media_type=media_type,
            headers={
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

@app.api_route("/stream/{filename:path}", methods=["GET", "HEAD"])
async def stream_file(filename: str, request: Request):
    """Stream video for mobile playback with range support"""
    try:
        filename = os.path.basename(unquote(filename))
        
        # Get device-specific folder
        device_type = request.state.device_type
        device_folder = request.state.device_folder
        path = device_folder / filename

        if not path.exists():
            # Try the other device folder as fallback
            if device_type == "laptop":
                alt_path = MOBILE_DOWNLOAD_FOLDER / filename
            else:
                alt_path = LAPTOP_DOWNLOAD_FOLDER / filename
                
            if alt_path.exists():
                path = alt_path
            else:
                return JSONResponse(status_code=404, content={"error": "File not found"})

        file_size = path.stat().st_size
        range_header = request.headers.get("range")
        
        # Determine media type
        if filename.endswith('.mp4'):
            media_type = 'video/mp4'
        elif filename.endswith('.mp3'):
            media_type = 'audio/mpeg'
        else:
            media_type = 'video/mp4'

        if range_header:
            # Handle range requests for video streaming
            byte1, byte2 = 0, None
            match = re.search(r'bytes=(\d+)-(\d*)', range_header)
            if match:
                byte1 = int(match.group(1))
                if match.group(2):
                    byte2 = int(match.group(2))
            
            if byte2 is None:
                byte2 = file_size - 1
            
            length = byte2 - byte1 + 1
            
            with open(path, 'rb') as f:
                f.seek(byte1)
                data = f.read(length)
            
            response = Response(
                content=data,
                status_code=206,
                media_type=media_type,
                headers={
                    "Content-Range": f"bytes {byte1}-{byte2}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(length),
                    "Access-Control-Allow-Origin": "*",
                }
            )
            return response
        else:
            # Full file request
            encoded_filename = quote(filename.encode('utf-8'))
            return FileResponse(
                path=path,
                media_type=media_type,
                headers={
                    "Content-Disposition": f"inline; filename*=UTF-8''{encoded_filename}",
                    "Accept-Ranges": "bytes",
                    "Access-Control-Allow-Origin": "*",
                }
            )
            
    except Exception as e:
        print(f"Stream error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

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

@app.get("/device-info")
async def device_info(request: Request):
    """Get device information"""
    device_type = request.state.device_type
    device_folder = request.state.device_folder
    
    # Count files in device folder
    file_count = len([f for f in device_folder.glob("*") if f.is_file() and not f.name.endswith(('.jpg', '.jpeg', '.png', '.webp'))])
    
    # List actual files
    files_list = [f.name for f in device_folder.glob("*") if f.is_file() and not f.name.endswith(('.jpg', '.jpeg', '.png', '.webp', '.part', '.ytdl'))]
    
    return JSONResponse(
        content={
            "device": device_type,
            "folder": str(device_folder),
            "file_count": file_count,
            "files": files_list[:10],  # First 10 files for debugging
            "user_agent": request.headers.get("user-agent", "")[:100]
        },
        headers={
            "Access-Control-Allow-Origin": "*",
        }
    )

@app.get("/thumbnails/{filename}")
async def get_thumbnail(filename: str):
    filename = os.path.basename(filename)
    path = THUMBNAIL_FOLDER / filename
    
    if path.exists():
        return FileResponse(
            path, 
            media_type='image/jpeg',
            headers={
                "Access-Control-Allow-Origin": "*",
            }
        )
    
    return JSONResponse(
        status_code=404,
        content={"error": "Thumbnail not found"},
        headers={
            "Access-Control-Allow-Origin": "*",
        }
    )

@app.get("/file-metadata/{filename}")
async def get_file_metadata_endpoint(filename: str, request: Request):
    """Get metadata including thumbnail for a specific file"""
    filename = os.path.basename(filename)
    
    if filename in file_metadata:
        return JSONResponse(
            content=file_metadata[filename],
            headers={
                "Access-Control-Allow-Origin": "*",
            }
        )
    
    # Try to find by base name without extension
    for key in file_metadata:
        if key.startswith(filename.rsplit('.', 1)[0]):
            return JSONResponse(
                content=file_metadata[key],
                headers={
                    "Access-Control-Allow-Origin": "*",
                }
            )
    
    # Return default if no metadata
    return JSONResponse(
        content={
            'thumbnail': None,
            'title': filename.replace('_', ' ').replace('-', ' ').rsplit('.', 1)[0],
            'uploader': 'Unknown',
            'duration': 'Unknown'
        },
        headers={
            "Access-Control-Allow-Origin": "*",
        }
    )

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "downloads_folder": DOWNLOAD_FOLDER.exists(),
        "laptop_folder": LAPTOP_DOWNLOAD_FOLDER.exists(),
        "mobile_folder": MOBILE_DOWNLOAD_FOLDER.exists(),
        "thumbnails_folder": THUMBNAIL_FOLDER.exists(),
        "ffmpeg_available": check_ffmpeg()
    }

def check_ffmpeg():
    """Check if ffmpeg is available"""
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        return True
    except:
        return False

if __name__ == "__main__":
    import uvicorn
    PORT = int(os.getenv("PORT", 8000))
    print(f"Starting Video Downloader...")
    print(f"Local access: http://127.0.0.1:{PORT}")
    print(f"Network access: http://{LOCAL_IP}:{PORT} (for mobile)")
    print(f"Laptop downloads folder: {LAPTOP_DOWNLOAD_FOLDER}")
    print(f"Mobile downloads folder: {MOBILE_DOWNLOAD_FOLDER}")
    print(f"Thumbnails folder: {THUMBNAIL_FOLDER}")
    print(f"\nDebug routes: http://127.0.0.1:{PORT}/debug/routes")
    print(f"Debug device detection: http://127.0.0.1:{PORT}/debug/device")
    uvicorn.run(app, host="0.0.0.0", port=PORT)