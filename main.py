from fastapi import FastAPI, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
import yt_dlp
import os
import uuid
import threading
import time
import urllib.request
import urllib.error

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


def download_task(job_id, url, format_option):
    def progress_hook(d):
        if d['status'] == 'downloading':
            percent = d.get("_percent_str", "0%").strip()
            progress_store[job_id] = {
                "status": "downloading",
                "percent": percent
            }
        elif d['status'] == 'finished':
            progress_store[job_id]["status"] = "processing"
            progress_store[job_id]["filename"] = d.get("filename")

    # Format mapping
    format_map = {
        "best": "bestvideo+bestaudio/best",
        "1080": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "720": "bestvideo[height<=720]+bestaudio/best[height<=720]",
        "audio": "bestaudio/best"
    }
    
    actual_format = format_map.get(format_option, "best")

    ydl_opts = {
        'outtmpl': f'{DOWNLOAD_FOLDER}/%(title)s.%(ext)s',
        'format': actual_format,
        'progress_hooks': [progress_hook],
        'writethumbnail': True,  # Download thumbnail
    }

    # For audio only
    if format_option == "audio":
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            # Extract info first to get thumbnail
            info = ydl.extract_info(url, download=True)
            
            # Save thumbnail mapping
            if info.get('thumbnail'):
                thumb_url = info['thumbnail']
                # Get filename without extension for the video
                video_filename = ydl.prepare_filename(info)
                video_basename = os.path.basename(video_filename)
                
                # Download thumbnail using urllib
                try:
                    # Create a request with a user agent
                    req = urllib.request.Request(
                        thumb_url, 
                        headers={'User-Agent': 'Mozilla/5.0'}
                    )
                    
                    with urllib.request.urlopen(req, timeout=10) as response:
                        # Determine thumbnail extension from content-type
                        content_type = response.headers.get('content-type', '')
                        if 'jpeg' in content_type or 'jpg' in content_type:
                            thumb_ext = 'jpg'
                        elif 'png' in content_type:
                            thumb_ext = 'png'
                        elif 'webp' in content_type:
                            thumb_ext = 'webp'
                        else:
                            # Try to get from URL
                            thumb_ext = thumb_url.split('.')[-1].split('?')[0][:4]
                            if thumb_ext not in ['jpg', 'jpeg', 'png', 'webp']:
                                thumb_ext = 'jpg'
                        
                        thumb_filename = f"{job_id}.{thumb_ext}"
                        thumb_path = os.path.join(THUMBNAIL_FOLDER, thumb_filename)
                        
                        # Save the thumbnail
                        with open(thumb_path, 'wb') as f:
                            f.write(response.read())
                        
                        # Store mapping with the actual video filename
                        file_metadata[video_basename] = {
                            'thumbnail': f"/thumbnails/{thumb_filename}",
                            'title': info.get('title', 'Unknown')
                        }
                except Exception as e:
                    print(f"Thumbnail download failed: {e}")
            
            progress_store[job_id]["status"] = "finished"
            
        except Exception as e:
            progress_store[job_id]["status"] = "error"
            progress_store[job_id]["error"] = str(e)


@app.post("/preview")
async def preview_video(url: str = Form(...)):
    ydl_opts = {'quiet': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

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

    return {
        "title": info.get("title"),
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "filesize": filesize_str,
        "uploader": info.get("uploader"),
        "view_count": info.get("view_count")
    }


@app.post("/start-download")
async def start_download(background_tasks: BackgroundTasks,
                         url: str = Form(...),
                         quality: str = Form(...)):

    job_id = str(uuid.uuid4())

    progress_store[job_id] = {"status": "starting", "percent": "0%"}

    background_tasks.add_task(download_task, job_id, url, quality)

    return {"job_id": job_id}


@app.get("/progress/{job_id}")
async def get_progress(job_id: str):
    return progress_store.get(job_id, {"status": "unknown"})


@app.get("/files")
async def list_files():
    files = os.listdir(DOWNLOAD_FOLDER)
    # Filter out thumbnail files and sort by modification time (newest first)
    video_files = [f for f in files if not f.endswith(('.jpg', '.jpeg', '.png', '.webp'))]
    video_files.sort(key=lambda x: os.path.getmtime(os.path.join(DOWNLOAD_FOLDER, x)), reverse=True)
    return video_files


@app.get("/download-file/{filename}")
async def download_file(filename: str):
    path = os.path.join(DOWNLOAD_FOLDER, filename)
    return FileResponse(path)


@app.get("/file-metadata/{filename}")
async def get_file_metadata(filename: str):
    """Get metadata including thumbnail for a specific file"""
    if filename in file_metadata:
        return file_metadata[filename]
    
    # Return default if no metadata
    return {
        'thumbnail': None,
        'title': filename.replace('_', ' ').replace('-', ' ')
    }


@app.get("/thumbnails/{filename}")
async def get_thumbnail(filename: str):
    path = os.path.join(THUMBNAIL_FOLDER, filename)
    if os.path.exists(path):
        return FileResponse(path)
    return JSONResponse({"error": "Thumbnail not found"}, status_code=404)


if __name__ == "__main__":
    import uvicorn
    PORT = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)