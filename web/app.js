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
    loadFiles(); // Refresh files when back online
  } else {
    offlineIndicator.style.display = 'flex';
    showStatus('You are offline. Downloads will be queued.', 'info');
  }
}

// ==================== BACKGROUND SYNC ====================
async function queueOfflineDownload(url, quality) {
  if ('serviceWorker' in navigator && 'SyncManager' in window) {
    const registration = await navigator.serviceWorker.ready;
    
    const db = await openDB();
    const tx = db.transaction('pendingDownloads', 'readwrite');
    const store = tx.objectStore('pendingDownloads');
    
    await store.add({
      id: Date.now(),
      url,
      quality,
      timestamp: new Date().toISOString()
    });
    
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

// ==================== DEVICE DETECTION ====================
function getDeviceType() {
  const ua = navigator.userAgent.toLowerCase();
  if (/iphone|ipad|ipod|android|mobile/i.test(ua)) {
    return 'mobile';
  }
  return 'laptop';
}

async function getDeviceInfo() {
  try {
    const res = await fetch('/device-info');
    if (res.ok) {
      return await res.json();
    }
  } catch (err) {
    console.error('Failed to get device info:', err);
  }
  return { device: getDeviceType(), file_count: 0, files: [] };
}

// ==================== THEME TOGGLE ====================
const themeToggle = document.createElement('div');
themeToggle.className = 'theme-toggle';
themeToggle.innerHTML = '<i class="fas fa-moon"></i>';
document.body.appendChild(themeToggle);

const savedTheme = localStorage.getItem('theme') || 'light';
if (savedTheme === 'dark') {
  document.documentElement.setAttribute('data-theme', 'dark');
  themeToggle.innerHTML = '<i class="fas fa-sun"></i>';
}

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
      reg.addEventListener('updatefound', () => {
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
let progressRetryCount = 0;
const MAX_RETRIES = 5;
const PROGRESS_INTERVAL = 2000;

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

  if (!navigator.onLine) {
    await queueOfflineDownload(url, quality);
    return;
  }

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
    progressRetryCount = 0;
    
    showStatus(`Download started on ${data.device}...`, 'info');
    progressBar.style.width = '5%';
    
    if (progressInterval) clearInterval(progressInterval);
    progressInterval = setInterval(trackProgress, PROGRESS_INTERVAL);
    
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
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 15000);
    
    const res = await fetch(`/progress/${currentJob}`, {
      signal: controller.signal,
      cache: 'no-store',
      headers: {
        'Cache-Control': 'no-cache'
      }
    });
    
    clearTimeout(timeoutId);
    
    if (!res.ok) throw new Error('Progress fetch failed');
    
    const data = await res.json();
    progressRetryCount = 0;
    
    if (data.status === 'downloading') {
      const percent = parseFloat(data.percent) || 0;
      progressBar.style.width = percent + '%';
      showStatus(`Downloading: ${data.percent}% - ${data.speed || ''}`, 'info');
      
    } else if (data.status === 'processing') {
      showStatus('Processing video...', 'info');
      progressBar.style.width = '90%';
      
    } else if (data.status === 'finished') {
      progressBar.style.width = '100%';
      showStatus('Download complete!', 'success');
      
      if ('Notification' in window && Notification.permission === 'granted') {
        new Notification('Download Complete', {
          body: 'Your video has been downloaded successfully!',
          icon: '/icons/icon-192x192.png'
        });
      }
      
      clearInterval(progressInterval);
      progressInterval = null;
      currentJob = null;
      
      downloadBtn.disabled = false;
      downloadBtn.innerHTML = '<i class="fas fa-cloud-download-alt"></i> Download';
      
      // Force immediate file refresh
      await loadFiles();
      
      setTimeout(() => {
        progressBar.style.width = '0%';
      }, 3000);
      
    } else if (data.status === 'error') {
      throw new Error(data.error || 'Download failed');
    } else if (data.status === 'starting') {
      showStatus('Starting download...', 'info');
      progressBar.style.width = '2%';
    }
    
  } catch (err) {
    console.error('Progress tracking error:', err);
    
    if (err.name === 'AbortError') {
      console.log('Progress request timeout');
      return;
    }
    
    if (progressRetryCount < MAX_RETRIES) {
      progressRetryCount++;
      console.log(`Retrying progress fetch (${progressRetryCount}/${MAX_RETRIES})...`);
    } else {
      showStatus('Download in progress... Check back soon', 'info');
      progressRetryCount = 0;
      setTimeout(() => loadFiles(), 5000);
    }
  }
}

async function getFileMetadata(filename) {
  try {
    const res = await fetch(`/file-metadata/${encodeURIComponent(filename)}`, {
      cache: 'no-store'
    });
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
    const deviceInfo = await getDeviceInfo();
    const deviceType = getDeviceType();
    
    let files = [];
    try {
      const res = await fetch('/files', {
        cache: 'no-store',
        headers: {
          'Cache-Control': 'no-cache'
        }
      });
      
      if (res.ok) {
        files = await res.json();
        console.log(`Loaded ${files.length} files for ${deviceType}`);
        
        // Save to IndexedDB for offline access
        for (const file of files) {
          await saveDownloadedFile(file, { synced: true });
        }
      }
    } catch (err) {
      console.log('Offline - loading from cache');
      const cached = await getDownloadedFiles();
      files = cached.map(f => f.filename);
    }
    
    if (files.length === 0) {
      container.innerHTML = `
        <div class="device-indicator" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white;">
          <i class="fas fa-${deviceType === 'mobile' ? 'mobile-alt' : 'laptop'}"></i>
          ${deviceType.charAt(0).toUpperCase() + deviceType.slice(1)} Downloads
        </div>
        <div style="text-align:center; opacity:0.7; padding:30px 16px; background: rgba(255,255,255,0.05); border-radius: 20px; margin-top: 15px;">
          <i class="fas fa-film" style="font-size: 48px; margin-bottom: 15px; opacity: 0.5;"></i>
          <p>No downloads on this device yet</p>
          <p style="font-size: 12px; margin-top: 10px;">Downloads are saved separately for laptop and mobile</p>
        </div>
      `;
      return;
    }
    
    container.innerHTML = '';
    
    // Device header
    const deviceHeader = document.createElement('div');
    deviceHeader.className = 'device-indicator';
    deviceHeader.style.background = 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)';
    deviceHeader.style.color = 'white';
    deviceHeader.innerHTML = `
      <i class="fas fa-${deviceType === 'mobile' ? 'mobile-alt' : 'laptop'}"></i>
      ${deviceType.charAt(0).toUpperCase() + deviceType.slice(1)} Downloads (${files.length})
    `;
    container.appendChild(deviceHeader);
    
    // Load files with metadata
    for (const filename of files) {
      const metadata = await getFileMetadata(filename);
      
      const div = document.createElement('div');
      div.className = 'history-item';
      
      const thumbImg = document.createElement('img');
      thumbImg.className = 'thumb-img';
      thumbImg.loading = 'lazy';
      
      if (metadata.thumbnail) {
        thumbImg.src = metadata.thumbnail;
        thumbImg.onerror = () => {
          thumbImg.src = 'https://via.placeholder.com/70x70?text=Video';
        };
      } else {
        thumbImg.src = 'https://via.placeholder.com/70x70?text=Video';
      }
      
      thumbImg.alt = 'thumb';
      div.appendChild(thumbImg);
      
      const infoSpan = document.createElement('span');
      infoSpan.className = 'history-info';
      
      const nameWithoutExt = filename.replace(/\.[^/.]+$/, "");
      const ext = filename.split('.').pop() || 'mp4';
      const displayTitle = metadata.title || nameWithoutExt;
      
      infoSpan.innerHTML = `
        <div class="filename"><i class="fas fa-video"></i> ${displayTitle.substring(0, 25)}${displayTitle.length > 25 ? '…' : ''}</div>
        <div class="filesize"><i class="fas fa-file-${ext === 'mp3' ? 'audio' : 'video'}"></i> .${ext}</div>
      `;
      
      div.appendChild(infoSpan);
      
      const btn = document.createElement('button');
      btn.innerHTML = '<i class="fas fa-download"></i> Save';

      btn.onclick = (e) => {
        e.stopPropagation();
        const encodedFilename = encodeURIComponent(filename);
        
        if (deviceType === 'mobile' && (filename.endsWith('.mp4') || filename.endsWith('.webm'))) {
          window.open(`/stream/${encodedFilename}`, '_blank');
        } else {
          window.open(`/download-file/${encodedFilename}`, '_blank');
        }
      };
      
      div.appendChild(btn);
      container.appendChild(div);
    }
    
  } catch (err) {
    console.error('Error loading files:', err);
  }
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
  if (!seconds || seconds === 'Unknown') return 'Unknown duration';
  if (typeof seconds === 'string') return seconds;
  
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

// Platform icon clicks
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

urlInput.addEventListener('paste', () => {
  setTimeout(preview, 100);
});

urlInput.addEventListener('blur', preview);

// Hide splash
window.addEventListener('load', () => {
  setTimeout(() => {
    document.getElementById('splash').style.display = 'none';
    document.querySelector('.app').style.display = 'block';
  }, 2000);
  
  updateOnlineStatus();
});

// Initialize
loadFiles();
setTimeout(preview, 500);

// Refresh file list every 15 seconds
setInterval(loadFiles, 15000);

// ==================== EXPOSE PUBLIC API ====================
window.app = {
  preview,
  startDownload,
  loadFiles
};