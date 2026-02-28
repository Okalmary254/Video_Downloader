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

app = FastAPI()


# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # project root
WEB_DIR = BASE_DIR / "web"
DOWNLOAD_FOLDER = BASE_DIR / "downloads"
THUMBNAIL_FOLDER = BASE_DIR / "thumbnails"

# Create folders if missing
DOWNLOAD_FOLDER.mkdir(exist_ok=True)
THUMBNAIL_FOLDER.mkdir(exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

# Serve index.html
@app.get("/", response_class=HTMLResponse)
async def home():
    return (WEB_DIR / "index.html").read_text(encoding="utf-8")

# Serve JS & CSS explicitly (optional since mounted in /static)
@app.get("/app.js")
async def get_app_js():
    return FileResponse(WEB_DIR / "app.js", media_type="application/javascript")

@app.get("/styles.css")
async def get_styles_css():
    return FileResponse(WEB_DIR / "styles.css", media_type="text/css")

progress_store = {}
file_metadata = {}

AUTO_DELETE_AFTER = 3600


def auto_cleanup():
    while True:
        now = time.time()
        # Clean downloads
        for file in os.listdir(DOWNLOAD_FOLDER):
            path = os.path.join(DOWNLOAD_FOLDER, file)
            if os.path.isfile(path):
                if now - os.path.getmtime(path) > AUTO_DELETE_AFTER:
                    os.remove(path)
        
        # Clean thumbnails
        for thumb in THUMBNAIL_FOLDER.iterdir():
            if thumb.is_file():
                if time.time() - thumb.stat().st_mtime > AUTO_DELETE_AFTER:
                    thumb.unlink()
        
        time.sleep(300)


threading.Thread(target=auto_cleanup, daemon=True).start()


def sanitize_filename(filename):
    """Remove invalid characters from filename"""
    return re.sub(r'[<>:"/\\|?*]', '', filename)


def download_task(job_id, url, format_option):
    progress_store = defaultdict(dict)
    progress_lock = Lock()
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
            
                progress_store[job_id] = {
                    "status": "downloading",
                    "percent": percent,
                    "speed": d.get('_speed_str', 'N/A').strip(),
                    "eta": d.get('_eta_str', 'N/A').strip()
                }
            elif d['status'] == 'finished':
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
        'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
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
        # For video, merge formats using ffmpeg
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
            
            # Get the actual filename that will be created
            video_filename = ydl.prepare_filename(info)
            video_basename = os.path.basename(video_filename)
            
            # Handle audio extension change
            if format_option == "audio":
                video_basename = video_basename.rsplit('.', 1)[0] + '.mp3'
            
            # Update progress with title
            progress_store[job_id]["title"] = info.get('title', 'Unknown')
            
            # Download the video
            ydl.download([url])
            
            # Download and save thumbnail
            if info.get('thumbnail'):
                try:
                    thumb_url = info['thumbnail']
                    thumb_ext = 'jpg'
                    
                    # Create request with headers
                    req = urllib.request.Request(
                        thumb_url,
                        headers={
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                        }
                    )
                    
                    with urllib.request.urlopen(req, timeout=15) as response:
                        # Save thumbnail
                        thumb_filename = f"{job_id}.{thumb_ext}"
                        thumb_path = os.path.join(THUMBNAIL_FOLDER, thumb_filename)
                        
                        with open(thumb_path, 'wb') as f:
                            f.write(response.read())
                        
                        # Store metadata
                        file_metadata[video_basename] = {
                            'thumbnail': f"/thumbnails/{thumb_filename}",
                            'title': info.get('title', 'Unknown'),
                            'uploader': info.get('uploader', 'Unknown'),
                            'duration': info.get('duration', 0)
                        }
                except Exception as e:
                    print(f"Thumbnail download failed: {e}")
            
            # Mark as finished
            progress_store[job_id] = {
                "status": "finished",
                "filename": video_basename,
                "title": info.get('title', 'Unknown')
            }
            
    except Exception as e:
        progress_store[job_id] = {
            "status": "error",
            "error": str(e)
        }
        print(f"Download error: {e}")


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
        if 'entries' in info:
            # It's a playlist - take first entry
            info = info['entries'][0]

        # Format duration
        duration = info.get('duration')
        if duration:
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
            # Get the highest resolution thumbnail
            thumbnails.sort(key=lambda x: x.get('height', 0) or x.get('width', 0) or 0, reverse=True)
            thumbnail = thumbnails[0].get('url')

        # Format view count
        view_count = info.get('view_count', 0)
        if view_count > 1000000:
            view_str = f"{view_count/1000000:.1f}M"
        elif view_count > 1000:
            view_str = f"{view_count/1000:.1f}K"
        else:
            view_str = str(view_count)

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

    progress_store[job_id] = {
        "status": "starting",
        "percent": "0",
        "message": "Initializing download..."
    }

    background_tasks.add_task(download_task, job_id, url.strip(), quality)

    return {"job_id": job_id}


@app.get("/progress/{job_id}")
async def get_progress(job_id: str):
    data = progress_store.get(job_id)
    if not data:
        return {"status": "unknown"}
    return data

    def progress_hook(d):
        with progress_lock:
            if job_id not in progress_store:
                progress_store[job_id] = {"status": "starting", "percent": "0"}

        status = d.get("status")

        if status == "downloading":
            # Always default numeric values
            percent = 0
            try:
                percent_match = re.search(r"(\d+(?:\.\d+)?)", d.get("_percent_str", "0"))
                percent = float(percent_match.group(1)) if percent_match else 0
            except Exception:
                percent = 0

            progress_store[job_id].update({
                "status": "downloading",
                "percent": str(int(percent)),  # frontend expects string or int
                "speed": d.get("_speed_str", "N/A"),
                "eta": d.get("_eta_str", "N/A")
            })

        elif status == "finished":
            filename = os.path.basename(d.get("filename", "unknown.mp4"))
            progress_store[job_id].update({
                "status": "processing",
                "percent": "100",
                "filename": filename
            })

        elif status == "error":
            progress_store[job_id].update({
                "status": "error",
                "percent": "0",
                "error": str(d.get("error", "Unknown error"))
            })



@app.get("/files")
async def list_files():
    try:
        files = os.listdir(DOWNLOAD_FOLDER)
        # Filter out thumbnail and temporary files
        video_files = [f for f in files if not any([
            f.endswith(('.jpg', '.jpeg', '.png', '.webp', '.part', '.ytdl')),
            f.startswith('.')
        ])]
        
        # Get file info
        file_list = []
        for f in video_files:
            path = os.path.join(DOWNLOAD_FOLDER, f)
            if os.path.isfile(path):
                stat = os.stat(path)
                file_list.append({
                    'name': f,
                    'size': stat.st_size,
                    'modified': stat.st_mtime,
                    'metadata': file_metadata.get(f, {})
                })
        
        # Sort by modification time (newest first)
        file_list.sort(key=lambda x: x['modified'], reverse=True)
        return [f['name'] for f in file_list]
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.get("/download-file/{filename}", response_class=FileResponse)
@app.head("/download-file/{filename}", response_class=Response)  # support HEAD
async def download_file(filename: str):
    filename = os.path.basename(filename)
    path = os.path.join(DOWNLOAD_FOLDER, filename)
    
    if not os.path.exists(path):
        return JSONResponse(
            status_code=404,
            content={"error": "File not found"}
        )
    
    return FileResponse(
        path,
        filename=filename,
        media_type='application/octet-stream',
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.get("/file-metadata/{filename}", response_class=JSONResponse)
@app.head("/file-metadata/{filename}", response_class=Response)  # support HEAD
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

@app.get("/thumbnails/{filename}", response_class=FileResponse)
@app.head("/thumbnails/{filename}", response_class=Response)  # support HEAD
async def get_thumbnail(filename: str):
    # Security: prevent directory traversal
    filename = os.path.basename(filename)
    path = os.path.join(THUMBNAIL_FOLDER, filename)
    
    if os.path.exists(path):
        return FileResponse(path, media_type='image/jpeg')
    
    return JSONResponse(
        status_code=404,
        content={"error": "Thumbnail not found"}
    )


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "downloads_folder": os.path.exists(DOWNLOAD_FOLDER),
        "thumbnails_folder": os.path.exists(THUMBNAIL_FOLDER),
        "ffmpeg_available": check_ffmpeg()
    }


def check_ffmpeg():
    """Check if ffmpeg is available"""
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        return True
    except:
        return False
