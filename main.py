from fastapi import FastAPI, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
import yt_dlp
import os
import uuid
import threading
import time
import urllib.request
import urllib.error
import re
import subprocess

app = FastAPI()

DOWNLOAD_FOLDER = "downloads"
THUMBNAIL_FOLDER = "thumbnails"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
os.makedirs(THUMBNAIL_FOLDER, exist_ok=True)

progress_store = {}
file_metadata = {}  # Store thumbnail mapping

AUTO_DELETE_AFTER = 3600  # 1 hour


@app.get("/", response_class=HTMLResponse)
async def home():
    with open("index.html", "r") as f:
        return f.read()


# Serve app.js
@app.get("/app.js", response_class=FileResponse)
async def get_app_js():
    return FileResponse("app.js", media_type="application/javascript")


# Serve styles.css
@app.get("/styles.css", response_class=FileResponse)
async def get_styles_css():
    return FileResponse("styles.css", media_type="text/css")


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
        for thumb in os.listdir(THUMBNAIL_FOLDER):
            path = os.path.join(THUMBNAIL_FOLDER, thumb)
            if os.path.isfile(path):
                if now - os.path.getmtime(path) > AUTO_DELETE_AFTER:
                    os.remove(path)
        
        time.sleep(300)


threading.Thread(target=auto_cleanup, daemon=True).start()


def sanitize_filename(filename):
    """Remove invalid characters from filename"""
    return re.sub(r'[<>:"/\\|?*]', '', filename)


def download_task(job_id, url, format_option):
    def progress_hook(d):
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
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            return JSONResponse(
                status_code=400,
                content={"error": "Could not extract video information"}
            )

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

        # Format duration
        duration = info.get('duration')
        if duration:
            minutes = duration // 60
            seconds = duration % 60
            duration_str = f"{minutes}:{seconds:02d}"
        else:
            duration_str = "Unknown"

        return {
            "title": info.get('title', 'Unknown'),
            "thumbnail": info.get('thumbnail'),
            "duration": duration_str,
            "filesize": filesize_str,
            "uploader": info.get('uploader', 'Unknown'),
            "view_count": info.get('view_count', 0),
            "like_count": info.get('like_count', 0),
            "description": info.get('description', '')[:200] + '...' if info.get('description') else ''
        }
        
    except yt_dlp.utils.DownloadError as e:
        return JSONResponse(
            status_code=400,
            content={"error": f"Download error: {str(e)}"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Preview failed: {str(e)}"}
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
    if job_id in progress_store:
        return progress_store[job_id]
    return {"status": "unknown"}


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


@app.get("/download-file/{filename}")
async def download_file(filename: str):
    # Security: prevent directory traversal
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
        media_type='application/octet-stream'
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


@app.get("/thumbnails/{filename}")
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


if __name__ == "__main__":
    import uvicorn
    PORT = int(os.getenv("PORT", 8000))
    print(f" Starting Video Downloader on http://127.0.0.1:{PORT}")
    print(f" Downloads folder: {os.path.abspath(DOWNLOAD_FOLDER)}")
    print(f"  Thumbnails folder: {os.path.abspath(THUMBNAIL_FOLDER)}")
    print(f" FFmpeg available: {check_ffmpeg()}")
    print(" Press Ctrl+C to stop")
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)