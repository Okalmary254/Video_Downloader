from email.quoprimime import quote
from pathlib import Path
from fastapi import FastAPI, Form, BackgroundTasks, Response, Request
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
from urllib.parse import unquote

app = FastAPI()

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # project root
WEB_DIR = BASE_DIR / "web"
DOWNLOAD_FOLDER = BASE_DIR / "downloads"
THUMBNAIL_FOLDER = BASE_DIR / "thumbnails"

print(f"BASE_DIR: {BASE_DIR}")
print(f"WEB_DIR: {WEB_DIR}")
print(f"DOWNLOAD_FOLDER: {DOWNLOAD_FOLDER}")

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
                         url: str = Form(...),
                         quality: str = Form(...)):

    # Validate URL
    if not url or not url.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "URL is required"}
        )

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
            return progress_store[job_id]
    return {"status": "unknown"}

@app.get("/files")
async def list_files():
    try:
        files = []
        for f in DOWNLOAD_FOLDER.glob("*"):
            if f.is_file() and not any([
                f.name.endswith(('.jpg', '.jpeg', '.png', '.webp', '.part', '.ytdl')),
                f.name.startswith('.')
            ]):
                files.append(f.name)
        
        # Sort by modification time (newest first)
        files_with_time = [(f, (DOWNLOAD_FOLDER / f).stat().st_mtime) for f in files]
        files_with_time.sort(key=lambda x: x[1], reverse=True)
        
        return [f[0] for f in files_with_time]
        
    except Exception as e:
        print(f"Error listing files: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.api_route("/download-file/{filename:path}", methods=["GET", "HEAD"])
async def download_file(filename: str, request: Request):
    """Download a file with proper headers for all devices"""
    try:
        # Prevent directory traversal
        filename = os.path.basename(filename)
        
        # URL decode the filename first (if it was encoded)
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

        # Determine media type for mobile playback
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

        # For the Content-Disposition header, handle different scenarios
        user_agent = request.headers.get("user-agent", "").lower()
        is_mobile = any(device in user_agent for device in ['iphone', 'android', 'mobile'])
        
        # On mobile, we want to play the video inline, not download
        if is_mobile and media_type.startswith('video/'):
            disposition_type = "inline"
        else:
            disposition_type = "attachment"
        
        # Create a safe filename for the header - FIXED VERSION
        # Instead of iterating character by character, use encode/decode
        try:
            # Try to encode as ASCII, replacing non-ASCII chars
            ascii_filename = filename.encode('ascii', 'replace').decode('ascii')
            # Replace the replacement character with underscore
            ascii_filename = ascii_filename.replace('?', '_').replace('�', '_')
        except:
            # If that fails, use a simple approach with regex
            ascii_filename = re.sub(r'[^\x00-\x7F]+', '_', filename)
        
        if not ascii_filename or ascii_filename.strip() == '':
            # If we end up with empty string, use a default
            if filename.endswith('.mp4'):
                ascii_filename = 'video.mp4'
            elif filename.endswith('.mp3'):
                ascii_filename = 'audio.mp3'
            else:
                ascii_filename = 'file.mp4'
        
        # Ensure the extension is preserved
        if not ascii_filename.endswith(('.mp4', '.mp3', '.jpg', '.jpeg', '.png')):
            # Add the original extension
            ext = Path(filename).suffix
            if ext:
                ascii_filename = Path(ascii_filename).stem + ext
        
        # Encode for header
        encoded_filename = quote(filename.encode('utf-8'))
        
        # Create response with proper headers for mobile
        response = FileResponse(
            path=path,
            media_type=media_type,
            headers={
                "Content-Disposition": f"{disposition_type}; filename=\"{ascii_filename}\"; filename*=UTF-8''{encoded_filename}",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
                "Access-Control-Allow-Headers": "*",
                "Content-Length": str(file_size),
                "Cache-Control": "no-cache",
                "Accept-Ranges": "bytes",
                "Content-Transfer-Encoding": "binary",
            }
        )
        
        return response
        
    except Exception as e:
        print(f"Download error: {e}")
        import traceback
        traceback.print_exc()
        
        # Fallback to a simple file serving without fancy headers
        try:
            # Last resort - serve the file with minimal headers
            path = DOWNLOAD_FOLDER / os.path.basename(unquote(filename))
            if path.exists():
                return FileResponse(
                    path=path,
                    media_type='application/octet-stream',
                    headers={
                        "Access-Control-Allow-Origin": "*",
                    }
                )
        except:
            pass
            
        return JSONResponse(
            status_code=500,
            content={"error": f"Download failed: {str(e)}"}
        )

# Also add the streaming endpoint
@app.api_route("/stream/{filename:path}", methods=["GET", "HEAD"])
async def stream_file(filename: str, request: Request):
    """Stream video for mobile playback with range support"""
    try:
        filename = os.path.basename(unquote(filename))
        path = DOWNLOAD_FOLDER / filename

        if not path.exists():
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
            # Full file request - use inline for mobile
            user_agent = request.headers.get("user-agent", "").lower()
            is_mobile = any(device in user_agent for device in ['iphone', 'android', 'mobile'])
            
            disposition = "inline" if is_mobile else "attachment"
            encoded_filename = quote(filename.encode('utf-8'))
            
            return FileResponse(
                path=path,
                media_type=media_type,
                headers={
                    "Content-Disposition": f"{disposition}; filename*=UTF-8''{encoded_filename}",
                    "Accept-Ranges": "bytes",
                    "Access-Control-Allow-Origin": "*",
                }
            )
            
    except Exception as e:
        print(f"Stream error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
    
    
# Also add a streaming endpoint for better mobile support
@app.api_route("/stream/{filename:path}", methods=["GET", "HEAD"])
async def stream_file(filename: str, request: Request):
    """Stream video for mobile playback with range support"""
    try:
        filename = os.path.basename(unquote(filename))
        path = DOWNLOAD_FOLDER / filename

        if not path.exists():
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
            encoded_filename = quote(filename)
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
                from urllib.parse import quote
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

@app.get("/thumbnails/{filename}")
async def get_thumbnail(filename: str):
    # Security: prevent directory traversal
    filename = os.path.basename(filename)
    path = THUMBNAIL_FOLDER / filename
    
    if path.exists():
        return FileResponse(path, media_type='image/jpeg')
    
    return JSONResponse(
        status_code=404,
        content={"error": "Thumbnail not found"}
    )

@app.get("/file-metadata/{filename}")
async def get_file_metadata_endpoint(filename: str):
    """Get metadata including thumbnail for a specific file"""
    filename = os.path.basename(filename)
    
    if filename in file_metadata:
        return file_metadata[filename]
    
    # Try to find by base name without extension
    for key in file_metadata:
        if key.startswith(filename.rsplit('.', 1)[0]):
            return file_metadata[key]
    
    # Return default if no metadata
    return {
        'thumbnail': None,
        'title': filename.replace('_', ' ').replace('-', ' ').rsplit('.', 1)[0],
        'uploader': 'Unknown',
        'duration': 'Unknown'
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "downloads_folder": DOWNLOAD_FOLDER.exists(),
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
    print(f"Downloads folder: {DOWNLOAD_FOLDER}")
    print(f"Thumbnails folder: {THUMBNAIL_FOLDER}")
    print(f"\nDebug routes: http://127.0.0.1:{PORT}/debug/routes")
    uvicorn.run(app, host="0.0.0.0", port=PORT)