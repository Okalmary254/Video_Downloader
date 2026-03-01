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
    // Refresh files when back online
    loadFiles();
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
    const res = await fetch('/device-info', {
      cache: 'no-store',
      headers: {
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache'
      }
    });
    if (res.ok) {
      const info = await res.json();
      console.log(' Device Info:', info);
      return info;
    }
  } catch (err) {
    console.error('Failed to get device info:', err);
  }
  return { device: getDeviceType(), file_count: 0 };
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
let progressRetryCount = 0;
const MAX_RETRIES = 5;
const PROGRESS_INTERVAL = 2000; // 2 seconds for mobile
let lastFileListHash = null; // Track if file list changed

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
    progressRetryCount = 0;
    
    console.log(` Download started - Job ID: ${data.job_id}, Device: ${data.device}`);
    
    showStatus(`Download started on ${data.device}...`, 'info');
    progressBar.style.width = '5%';
    
    // Start polling for progress
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
    // Add timeout for mobile networks
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 15000); // 15 second timeout for mobile
    
    const res = await fetch(`/progress/${currentJob}`, {
      signal: controller.signal,
      cache: 'no-store',
      headers: {
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache'
      }
    });
    
    clearTimeout(timeoutId);
    
    if (!res.ok) throw new Error('Progress fetch failed');
    
    const data = await res.json();
    
    // Log progress for debugging
    console.log(` Progress: ${data.status} - ${data.percent}% (Device: ${data.device})`);
    
    // Reset retry count on successful fetch
    progressRetryCount = 0;
    
    // Update status
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
      
      console.log(` Download finished: ${data.filename} on ${data.device}`);
      
      // Show notification if supported
      if ('Notification' in window && Notification.permission === 'granted') {
        new Notification('Download Complete', {
          body: `${data.title || 'Your video'} has been downloaded!`,
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
      
      // IMPORTANT: Force refresh file list multiple times to ensure mobile sees new files
      console.log(' Refreshing file list...');
      await loadFiles(true); // Force refresh immediately
      
      // Refresh again after 2 seconds (in case file is still being written)
      setTimeout(() => {
        console.log(' Second refresh...');
        loadFiles(true);
      }, 2000);
      
      // And one more time after 5 seconds
      setTimeout(() => {
        console.log(' Final refresh...');
        loadFiles(true);
      }, 5000);
      
      // Reset progress after 3 seconds
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
    
    // Don't give up immediately on mobile
    if (err.name === 'AbortError') {
      console.log('Progress request timeout on mobile');
      // Just retry silently
      return;
    }
    
    // Retry logic for mobile networks
    if (progressRetryCount < MAX_RETRIES) {
      progressRetryCount++;
      console.log(`Retrying progress fetch (${progressRetryCount}/${MAX_RETRIES})...`);
      // Don't show error, just retry
    } else {
      // Max retries reached, but don't completely fail
      showStatus('Download in progress... Check back soon', 'info');
      progressRetryCount = 0;
      
      // Refresh files anyway in case download completed
      setTimeout(() => loadFiles(true), 5000);
    }
  }
}

async function getFileMetadata(filename) {
  try {
    const res = await fetch(`/file-metadata/${encodeURIComponent(filename)}`, {
      cache: 'no-store',
      headers: {
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache'
      }
    });
    if (res.ok) {
      return await res.json();
    }
  } catch (err) {
    console.error('Failed to get metadata:', err);
  }
  return { thumbnail: null, title: filename };
}

async function loadFiles(forceRefresh = false) {
  try {
    const container = document.getElementById('files');
    const deviceInfo = await getDeviceInfo();
    
    console.log(` Loading files for ${deviceInfo.device}...`);
    
    // Try to get from server first with aggressive cache busting
    let files = [];
    try {
      const timestamp = new Date().getTime();
      const res = await fetch(`/files?t=${timestamp}`, {
        cache: 'no-store',
        headers: {
          'Cache-Control': 'no-cache, no-store, must-revalidate',
          'Pragma': 'no-cache',
          'Expires': '0'
        }
      });
      
      if (res.ok) {
        files = await res.json();
        console.log(` Received ${files.length} files from server:`, files);
        
        // Check if file list actually changed
        const newHash = JSON.stringify(files.sort());
        if (!forceRefresh && newHash === lastFileListHash) {
          console.log(' File list unchanged, skipping update');
          return;
        }
        lastFileListHash = newHash;
        
        // Save to IndexedDB for offline access
        for (const file of files) {
          await saveDownloadedFile(file, { synced: true });
        }
      } else {
        console.warn('Failed to fetch files from server:', res.status);
      }
    } catch (err) {
      console.log(' Offline or error - loading from cache:', err.message);
      // If offline, load from IndexedDB
      const cached = await getDownloadedFiles();
      files = cached.map(f => f.filename);
    }
    
    if (files.length === 0) {
      container.innerHTML = `
        <div class="device-indicator">
          <i class="fas fa-${deviceInfo.device === 'mobile' ? 'mobile-alt' : 'laptop'}"></i>
          ${deviceInfo.device.charAt(0).toUpperCase() + deviceInfo.device.slice(1)} Downloads
        </div>
        <div style="text-align:center; opacity:0.7; padding:16px;">
          <i class="fas fa-film"></i> No downloads on this device yet
        </div>
      `;
      console.log(' No files found for this device');
      return;
    }
    
    console.log(` Displaying ${files.length} files`);
    
    container.innerHTML = '';
    
    // Add device indicator with count
    const deviceHeader = document.createElement('div');
    deviceHeader.className = 'device-indicator';
    deviceHeader.innerHTML = `
      <i class="fas fa-${deviceInfo.device === 'mobile' ? 'mobile-alt' : 'laptop'}"></i>
      ${deviceInfo.device.charAt(0).toUpperCase() + deviceInfo.device.slice(1)} Downloads (${files.length})
    `;
    container.appendChild(deviceHeader);
    
    // Load files with their metadata
    for (const filename of files) {
      const metadata = await getFileMetadata(filename);
      
      const div = document.createElement('div');
      div.className = 'history-item';
      
      // Thumbnail image
      const thumbImg = document.createElement('img');
      thumbImg.className = 'thumb-img';
      thumbImg.loading = 'lazy'; // Lazy load images
      
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
      
      // Extract basic info from filename or use metadata
      const nameWithoutExt = filename.replace(/\.[^/.]+$/, "");
      const ext = filename.split('.').pop() || 'mp4';
      const displayTitle = metadata.title || nameWithoutExt;
      
      infoSpan.innerHTML = `
        <div class="filename"><i class="fas fa-video"></i> ${displayTitle.substring(0, 25)}${displayTitle.length > 25 ? '…' : ''}</div>
        <div class="filesize"><i class="fas fa-file-${ext === 'mp3' ? 'audio' : 'video'}"></i> .${ext}</div>
      `;
      
      div.appendChild(infoSpan);
      
      // Download button with device-specific handling
      const btn = document.createElement('button');
      btn.innerHTML = '<i class="fas fa-download"></i> Save';
      
      const isMobile = deviceInfo.device === 'mobile';

      btn.onclick = (e) => {
        e.stopPropagation();
        const encodedFilename = encodeURIComponent(filename);
        
        console.log(` Download clicked: ${filename} (${isMobile ? 'mobile' : 'desktop'})`);
        
        if (isMobile && (filename.endsWith('.mp4') || filename.endsWith('.webm'))) {
          // On mobile, use stream endpoint for better playback
          window.open(`/stream/${encodedFilename}`, '_blank');
        } else {
          // On desktop, download normally
          window.open(`/download-file/${encodedFilename}`, '_blank');
        }
      };
      
      div.appendChild(btn);
      container.appendChild(div);
    }
    
  } catch (err) {
    console.error(' Error loading files:', err);
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
console.log(' App initializing...');
loadFiles(true); // Force initial load

// Auto-preview on page load (if URL exists)
setTimeout(preview, 500);

// Refresh file list more frequently for mobile to catch new downloads
const isMobileDevice = getDeviceType() === 'mobile';
const refreshInterval = isMobileDevice ? 10000 : 15000; // 10s for mobile, 15s for desktop
console.log(` File refresh interval: ${refreshInterval}ms (${isMobileDevice ? 'mobile' : 'desktop'})`);
setInterval(() => loadFiles(false), refreshInterval);

// ==================== EXPOSE PUBLIC API ====================
window.app = {
  preview,
  startDownload,
  loadFiles
};