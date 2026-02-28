
from setuptools import setup, find_packages

setup(
    name="vidownloader",
    version="1.0.0",
    description="Video Downloader with Web UI",
    author="John Mary",
    py_modules=["vidownloader"],
    install_requires=[
        "click>=8.0.0",
        "fastapi>=0.104.0",
        "uvicorn[standard]>=0.24.0",
        "yt-dlp",
        "python-multipart",
    ],
    entry_points={
        "console_scripts": [
            "vidownloader=vidownloader:main",
        ],
    },
    python_requires=">=3.8",
)