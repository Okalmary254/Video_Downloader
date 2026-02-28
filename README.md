
---

#  Video Downloader Web App

[![Python](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104.0-green)](https://fastapi.tiangolo.com/)
[![yt-dlp](https://img.shields.io/badge/yt--dlp-latest-orange)](https://github.com/yt-dlp/yt-dlp)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A cross-platform **Video Downloader with Web UI** built using **FastAPI** and **yt-dlp**. Download videos, track progress, and fetch video thumbnails. Launch directly from your CLI with the command:

```bash
vidownloader
```

---

## Features

* Web UI for easy video downloads
* Background download with progress tracking
* Video preview: title, duration, uploader, views, thumbnails
* Automatic cleanup of old downloads and thumbnails
* CLI launcher for one-command startup
* Cross-platform: Windows, macOS, Linux

---


##  Getting Started

### Requirements

* Python 3.8+
* `ffmpeg` installed and available in PATH
* Git
* pip (Python package manager)

---

### 1️ Clone the Repository

```bash
git clone https://github.com/Okalmary254/Video_Downloader.git
cd Video_Downloader
```

---

### 2️ Install Dependencies

**Recommended: Virtual Environment**

```bash
python -m venv venv
# Activate venv
# Linux/macOS
source venv/bin/activate
# Windows (cmd)
venv\Scripts\activate
# Windows (PowerShell)
venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

**Or global installation:**

```bash
pip install -r requirements.txt
```

---

### 3️ Install CLI Command

```bash
pip install -e .
```

Test the CLI:

```bash
vidownloader --help
```

You should see usage instructions for starting the server.

---

## 4️ Running the App

```bash
vidownloader
```

* Opens your default browser at **[http://127.0.0.1:8000](http://127.0.0.1:8000)**
* Press **Ctrl+C** to stop the server

Alternative (without CLI):

```bash
uvicorn src.vidownloader.main:app --reload
```

---

##  Platform-specific Notes

### Linux

```bash
sudo apt update
sudo apt install ffmpeg -y
vidownloader
```

### macOS

```bash
brew install ffmpeg
vidownloader
```

### Windows

1. Download and install [ffmpeg](https://ffmpeg.org/download.html)
2. Add `ffmpeg/bin` to your PATH
3. Open PowerShell and run:

```powershell
vidownloader
```

---

##  Directory Structure

```text
Video_Downloader/
├── src/
│   └── vidownloader/
│       ├── __init__.py
│       ├── main.py          # FastAPI backend
│       └── vidownloader.py  # CLI launcher
├── downloads/               # Downloaded videos
├── thumbnails/              # Video thumbnails
├── index.html               # Web UI
├── app.js                   # Frontend JS
├── styles.css               # Frontend CSS
├── setup.py                 # Package installer & CLI setup
├── requirements.txt         # Dependencies
├── run.py                   # Optional CLI launcher script
└── README.md
```

---

##  Usage Examples

### Download a video

1. Open the Web UI via CLI:

```bash
vidownloader
```

2. Paste video URL
3. Select quality (Best, 1080p, 720p, Audio)
4. Click **Download**
5. Track progress and download file once complete

### Check file metadata

API endpoint:

```text
GET /file-metadata/<filename>
```

Returns JSON including thumbnail URL, title, duration, and uploader.

---

###  Notes

* Files older than **1 hour** are automatically deleted
* Thumbnails might not appear if the video URL is unsupported
* Preview may fail on certain video formats

---

##  License

MIT License © John Mary

---
