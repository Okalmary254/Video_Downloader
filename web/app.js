// ==================== PWA INSTALLATION ====================
let deferredPrompt;
const installButton = document.createElement('div');
installButton.className = 'install-prompt';
installButton.innerHTML = `
  <i class="fas fa-download"></i>
  <span>Install App</span>
`;
installButton.style.display = 'none';
document.body.appendChild(installButton);

// Listen for install prompt
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredPrompt = e;
  installButton.style.display = 'flex';
});

installButton.addEventListener('click', async () => {
  if (!deferredPrompt) return;
  
  deferredPrompt.prompt();
  const { outcome } = await deferredPrompt.userChoice;
  
  if (outcome === 'accepted') {
    console.log('User accepted installation');
    installButton.style.display = 'none';
  }
  deferredPrompt = null;
});

// Detect if app is installed
window.addEventListener('appinstalled', () => {
  console.log('App was installed');
  installButton.style.display = 'none';
});

// ==================== OFFLINE DETECTION ====================
const offlineIndicator = document.createElement('div');
offlineIndicator.className = 'offline-indicator';
offlineIndicator.innerHTML = '<i class="fas fa-wifi-slash"></i> You are offline';
offlineIndicator.style.display = 'none';
document.body.appendChild(offlineIndicator);

window.addEventListener('online', updateOnlineStatus);
window.addEventListener('offline', updateOnlineStatus);

function updateOnlineStatus() {
  if (navigator.onLine) {
    offlineIndicator.style.display = 'none';
    showStatus('Back online!', 'success');
    syncOfflineDownloads();
  } else {
    offlineIndicator.style.display = 'flex';
    showStatus('You are offline. Downloads will be queued.', 'info');
  }
}

// ==================== BACKGROUND SYNC ====================
async function queueOfflineDownload(url, quality) {
  if ('serviceWorker' in navigator && 'SyncManager' in window) {
    const registration = await navigator.serviceWorker.ready;
    
    // Store download in IndexedDB
    const db = await openDB();
    const tx = db.transaction('pendingDownloads', 'readwrite');
    const store = tx.objectStore('pendingDownloads');
    
    await store.add({
      id: Date.now(),
      url,
      quality,
      timestamp: new Date().toISOString()
    });
    
    // Register sync
    await registration.sync.register('sync-downloads');
    showStatus('Download queued for when you\'re back online', 'info');
  }
}

// ==================== INDEXEDDB HELPERS ====================
function openDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('VideoDownloaderDB', 1);
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);
    request.onupgradeneeded = (event) => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains('pendingDownloads')) {
        db.createObjectStore('pendingDownloads', { keyPath: 'id' });
      }
      if (!db.objectStoreNames.contains('downloadedFiles')) {
        db.createObjectStore('downloadedFiles', { keyPath: 'filename' });
      }
    };
  });
}

async function saveDownloadedFile(filename, metadata) {
  const db = await openDB();
  const tx = db.transaction('downloadedFiles', 'readwrite');
  const store = tx.objectStore('downloadedFiles');
  await store.put({ filename, ...metadata, downloadedAt: new Date().toISOString() });
}

async function getDownloadedFiles() {
  const db = await openDB();
  const tx = db.transaction('downloadedFiles', 'readonly');
  const store = tx.objectStore('downloadedFiles');
  return new Promise((resolve, reject) => {
    const request = store.getAll();
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);
  });
}

async function syncOfflineDownloads() {
  const db = await openDB();
  const tx = db.transaction('pendingDownloads', 'readonly');
  const store = tx.objectStore('pendingDownloads');
  const pending = await new Promise((resolve, reject) => {
    const request = store.getAll();
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);
  });
  
  if (pending.length > 0) {
    showStatus(`Syncing ${pending.length} offline downloads...`, 'info');
  }
}

// ==================== THEME TOGGLE ====================
const themeToggle = document.createElement('div');
themeToggle.className = 'theme-toggle';
themeToggle.innerHTML = '<i class="fas fa-moon"></i>';
document.body.appendChild(themeToggle);

// Check for saved theme preference
const savedTheme = localStorage.getItem('theme') || 'light';
if (savedTheme === 'dark') {
  document.documentElement.setAttribute('data-theme', 'dark');
  themeToggle.innerHTML = '<i class="fas fa-sun"></i>';
}

// Theme toggle functionality
themeToggle.addEventListener('click', () => {
  const currentTheme = document.documentElement.getAttribute('data-theme');
  if (currentTheme === 'dark') {
    document.documentElement.removeAttribute('data-theme');
    localStorage.setItem('theme', 'light');
    themeToggle.innerHTML = '<i class="fas fa-moon"></i>';
  } else {
    document.documentElement.setAttribute('data-theme', 'dark');
    localStorage.setItem('theme', 'dark');
    themeToggle.innerHTML = '<i class="fas fa-sun"></i>';
  }
});

// ==================== SERVICE WORKER ====================
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js')
    .then(reg => {
      console.log('Service Worker registered:', reg);
      
      // Check for updates
      reg.addEventListener('updatefound', () => {
        const newWorker = reg.installing;
        showStatus('New version available! Refresh to update.', 'info');
      });
    })
    .catch(err => {
      console.log('SW registration failed:', err);
    });
}

// ==================== STATE ====================
let currentJob = null;
let progressInterval = null;
let previewData = null;

// ==================== DOM ELEMENTS ====================
const urlInput = document.getElementById('url');
const qualitySelect = document.getElementById('quality');
const downloadBtn = document.getElementById('downloadBtn');
const progressBar = document.getElementById('progressBar');
const statusDiv = document.getElementById('status');
const previewCard = document.getElementById('previewCard');
const previewThumb = document.getElementById('previewThumb');
const previewTitle = document.getElementById('previewTitle');
const previewMeta = document.getElementById('previewMeta');

// ==================== API CALLS ====================
async function preview() {
  const url = urlInput.value.trim();
  if (!url) {
    showStatus('Please enter a URL', 'error');
    return;
  }

  showStatus('Fetching video info...', 'info');
  
  try {
    const formData = new FormData();
    formData.append('url', url);
    
    const res = await fetch('/preview', {
      method: 'POST',
      body: formData
    });
    
    if (!res.ok) throw new Error('Preview failed');
    
    previewData = await res.json();
    
    // Update preview card
    previewTitle.textContent = previewData.title || 'Unknown title';
    previewMeta.innerHTML = `
      <i class="far fa-clock"></i> ${formatDuration(previewData.duration)} • 
      <i class="fas fa-file"></i> ${previewData.filesize || 'Size unknown'}
    `;
    
    if (previewData.thumbnail) {
      previewThumb.src = previewData.thumbnail;
    } else {
      previewThumb.src = 'https://via.placeholder.com/100x100?text=No+thumb';
    }
    
    previewCard.classList.add('active');
    showStatus('Ready to download', 'success');
    
  } catch (err) {
    console.error(err);
    showStatus('Failed to get video info', 'error');
    previewCard.classList.remove('active');
  }
}

async function startDownload() {
  const url = urlInput.value.trim();
  const quality = qualitySelect.value;
  
  if (!url) {
    showStatus('Please enter a URL', 'error');
    return;
  }

  // Check if offline
  if (!navigator.onLine) {
    await queueOfflineDownload(url, quality);
    return;
  }

  // Disable button during download
  downloadBtn.disabled = true;
  downloadBtn.innerHTML = '<i class="fas fa-spinner fa-pulse"></i> Starting...';
  
  try {
    const formData = new FormData();
    formData.append('url', url);
    formData.append('quality', quality);
    
    const res = await fetch('/start-download', {
      method: 'POST',
      body: formData
    });
    
    if (!res.ok) throw new Error('Failed to start download');
    
    const data = await res.json();
    currentJob = data.job_id;
    
    showStatus('Download started...', 'info');
    progressBar.style.width = '5%';
    
    // Start polling for progress
    if (progressInterval) clearInterval(progressInterval);
    progressInterval = setInterval(trackProgress, 1000);
    
  } catch (err) {
    console.error(err);
    showStatus('Failed to start download', 'error');
    downloadBtn.disabled = false;
    downloadBtn.innerHTML = '<i class="fas fa-cloud-download-alt"></i> Download';
  }
}

async function trackProgress() {
  if (!currentJob) return;
  
  try {
    const res = await fetch(`/progress/${currentJob}`);
    if (!res.ok) throw new Error('Progress fetch failed');
    
    const data = await res.json();
    
    // Update status
    if (data.status === 'downloading') {
      const percent = parseFloat(data.percent) || 0;
      progressBar.style.width = percent + '%';
      showStatus(`Downloading: ${data.percent}`, 'info');
      
    } else if (data.status === 'processing') {
      showStatus('Processing video...', 'info');
      progressBar.style.width = '90%';
      
    } else if (data.status === 'finished') {
      progressBar.style.width = '100%';
      showStatus('Download complete!', 'success');
      
      // Show notification if supported
      if ('Notification' in window && Notification.permission === 'granted') {
        new Notification('Download Complete', {
          body: 'Your video has been downloaded successfully!',
          icon: '/icons/icon-192x192.png'
        });
      }
      
      // Stop polling
      clearInterval(progressInterval);
      progressInterval = null;
      currentJob = null;
      
      // Re-enable button
      downloadBtn.disabled = false;
      downloadBtn.innerHTML = '<i class="fas fa-cloud-download-alt"></i> Download';
      
      // Refresh file list
      loadFiles();
      
      // Reset progress after 3 seconds
      setTimeout(() => {
        progressBar.style.width = '0%';
      }, 3000);
      
    } else if (data.status === 'error') {
      throw new Error(data.error || 'Download failed');
    }
    
  } catch (err) {
    console.error(err);
    showStatus('Error tracking progress', 'error');
    clearInterval(progressInterval);
    progressInterval = null;
    downloadBtn.disabled = false;
    downloadBtn.innerHTML = '<i class="fas fa-cloud-download-alt"></i> Download';
  }
}

async function getFileMetadata(filename) {
  try {
    const res = await fetch(`/file-metadata/${encodeURIComponent(filename)}`);
    if (res.ok) {
      return await res.json();
    }
  } catch (err) {
    console.error('Failed to get metadata:', err);
  }
  return { thumbnail: null, title: filename };
}

async function loadFiles() {
  try {
    const container = document.getElementById('files');
    
    // Try to get from server first
    let files = [];
    try {
      const res = await fetch('/files');
      if (res.ok) {
        files = await res.json();
        // Save to IndexedDB for offline access
        for (const file of files) {
          await saveDownloadedFile(file, { synced: true });
        }
      }
    } catch (err) {
      console.log('Offline - loading from cache');
      // If offline, load from IndexedDB
      const cached = await getDownloadedFiles();
      files = cached.map(f => f.filename);
    }
    
    if (files.length === 0) {
      container.innerHTML = '<div style="text-align:center; opacity:0.7; padding:16px;"><i class="fas fa-film"></i> No downloads yet</div>';
      return;
    }
    
    container.innerHTML = '';
    
    // Load files with their metadata
    for (const filename of files) {
      const metadata = await getFileMetadata(filename);
      
      const div = document.createElement('div');
      div.className = 'history-item';
      
      // Thumbnail image
      const thumbImg = document.createElement('img');
      thumbImg.className = 'thumb-img';
      
      if (metadata.thumbnail) {
        thumbImg.src = metadata.thumbnail;
        thumbImg.onerror = () => {
          thumbImg.src = 'https://via.placeholder.com/70x70?text=Video';
        };
      } else {
        // Try to get thumbnail from video file (first frame)
        thumbImg.src = await getVideoThumbnail(filename);
      }
      
      thumbImg.alt = 'thumb';
      div.appendChild(thumbImg);
      
      const infoSpan = document.createElement('span');
      infoSpan.className = 'history-info';
      
      // Extract basic info from filename or use metadata
      const nameWithoutExt = filename.replace(/\.[^/.]+$/, "");
      const ext = filename.split('.').pop() || 'mp4';
      const displayTitle = metadata.title || nameWithoutExt;
      
      // Get file size
      let fileSize = 'Size unknown';
      try {
        const statRes = await fetch(`/download-file/${encodeURIComponent(filename)}`, { method: 'HEAD' });
        const size = statRes.headers.get('content-length');
        if (size) {
          const sizeNum = parseInt(size);
          if (sizeNum > 1024 * 1024 * 1024) {
            fileSize = `${(sizeNum / (1024*1024*1024)).toFixed(1)} GB`;
          } else if (sizeNum > 1024 * 1024) {
            fileSize = `${(sizeNum / (1024*1024)).toFixed(1)} MB`;
          } else {
            fileSize = `${(sizeNum / 1024).toFixed(1)} KB`;
          }
        }
      } catch (err) {
        console.error('Failed to get file size:', err);
      }
      
      infoSpan.innerHTML = `
        <div class="filename"><i class="fas fa-video"></i> ${displayTitle.substring(0, 25)}${displayTitle.length > 25 ? '…' : ''}</div>
        <div class="filesize"><i class="fas fa-file-${ext === 'mp3' ? 'audio' : 'video'}"></i> .${ext} • ${fileSize}</div>
      `;
      
      div.appendChild(infoSpan);
      
      // In your loadFiles function, modify the download button to check device
      const btn = document.createElement('button');
      btn.innerHTML = '<i class="fas fa-download"></i> Save';

      // Check if mobile for better playback
      const isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);

      btn.onclick = (e) => {
      e.stopPropagation();
      const filename = encodeURIComponent(file.name);
    
      if (isMobile && file.name.endsWith('.mp4')) {
          // On mobile, open in new tab for better playback
          window.open(`/stream/${filename}`, '_blank');
      } else {
          // On desktop, download normally
          window.open(`/download-file/${filename}`, '_blank');
      }
      };
      
      div.appendChild(btn);
      container.appendChild(div);
    }
    
  } catch (err) {
    console.error(err);
  }
}

// Function to extract thumbnail from video file using canvas
async function getVideoThumbnail(filename) {
  return new Promise((resolve) => {
    const video = document.createElement('video');
    video.preload = 'metadata';
    video.crossOrigin = 'anonymous';
    
    video.onloadeddata = () => {
      video.currentTime = 0.1;
    };
    
    video.onseeked = () => {
      const canvas = document.createElement('canvas');
      canvas.width = video.videoWidth || 160;
      canvas.height = video.videoHeight || 90;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      
      const thumbnailUrl = canvas.toDataURL('image/jpeg', 0.7);
      video.remove();
      resolve(thumbnailUrl);
    };
    
    video.onerror = () => {
      resolve('https://via.placeholder.com/70x70?text=Video');
    };
    
    video.src = `/download-file/${encodeURIComponent(filename)}`;
    video.load();
    
    setTimeout(() => {
      if (!video.ended && !video.paused) {
        video.pause();
        resolve('https://via.placeholder.com/70x70?text=Video');
      }
    }, 3000);
  });
}

// ==================== HELPER FUNCTIONS ====================
function showStatus(message, type = 'info') {
  const icon = {
    'info': '<i class="fas fa-circle-info"></i>',
    'success': '<i class="fas fa-check-circle"></i>',
    'error': '<i class="fas fa-exclamation-circle"></i>'
  }[type] || '<i class="fas fa-circle-info"></i>';
  
  statusDiv.innerHTML = `${icon} ${message}`;
  statusDiv.className = type === 'error' ? 'status-error' : (type === 'success' ? 'status-success' : '');
}

function formatDuration(seconds) {
  if (!seconds) return 'Unknown duration';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m ${s}s`;
}

// ==================== NOTIFICATION PERMISSION ====================
if ('Notification' in window && Notification.permission === 'default') {
  Notification.requestPermission();
}

// ==================== EVENT LISTENERS ====================

// Platform icon clicks - fill with example URLs
document.querySelectorAll('.platform-item').forEach(item => {
  item.addEventListener('click', () => {
    const examples = {
      'tiktok': 'https://www.tiktok.com/@example/video/123456789',
      'instagram': 'https://www.instagram.com/p/Cxample/',
      'facebook': 'https://www.facebook.com/watch/?v=123456789',
      'twitter': 'https://twitter.com/example/status/123456789',
      'youtube': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
      'pinterest': 'https://www.pinterest.com/pin/123456789'
    };
    
    const platform = item.dataset.url;
    if (examples[platform]) {
      urlInput.value = examples[platform];
      preview();
    }
  });
});

// URL input - auto preview on paste
urlInput.addEventListener('paste', () => {
  setTimeout(preview, 100);
});

// Also preview on blur (when user leaves input)
urlInput.addEventListener('blur', preview);

// Hide splash
window.addEventListener('load', () => {
  setTimeout(() => {
    document.getElementById('splash').style.display = 'none';
    document.querySelector('.app').style.display = 'block';
  }, 2000);
  
  // Check online status
  updateOnlineStatus();
});

// Initialize
loadFiles();

// Auto-preview on page load (if URL exists)
setTimeout(preview, 500);

// Refresh file list every 30 seconds
setInterval(loadFiles, 30000);

// ==================== EXPOSE PUBLIC API ====================
window.app = {
  preview,
  startDownload,
  loadFiles
};