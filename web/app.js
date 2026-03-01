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
    installButton.style.display = 'none';
  }
  deferredPrompt = null;
});

window.addEventListener('appinstalled', () => {
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
  } else {
    offlineIndicator.style.display = 'flex';
    showStatus('You are offline. Please check your connection.', 'info');
  }
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
    .then(reg => console.log('Service Worker registered'))
    .catch(err => console.log('SW registration failed:', err));
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
    
    previewTitle.textContent = previewData.title || 'Unknown title';
    previewMeta.innerHTML = `
      <i class="far fa-clock"></i> ${previewData.duration} • 
      <i class="fas fa-file"></i> ${previewData.filesize}
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
    showStatus('You are offline. Please connect to the internet.', 'error');
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
    
    showStatus('Download started...', 'info');
    progressBar.style.width = '5%';
    
    if (progressInterval) clearInterval(progressInterval);
    progressInterval = setInterval(trackProgress, 1500);
    
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
      signal: controller.signal
    });
    
    clearTimeout(timeoutId);
    
    if (!res.ok) throw new Error('Progress fetch failed');
    
    const data = await res.json();
    
    if (data.status === 'downloading') {
      const percent = parseFloat(data.percent) || 0;
      progressBar.style.width = percent + '%';
      showStatus(`Downloading: ${data.percent}%`, 'info');
      
    } else if (data.status === 'processing') {
      showStatus('Processing video...', 'info');
      progressBar.style.width = '90%';
      
    } else if (data.status === 'finished') {
      progressBar.style.width = '100%';
      showStatus('Download complete!', 'success');
      
      // Trigger file download to user's device
      if (data.download_url) {
        window.open(data.download_url, '_blank');
      }
      
      clearInterval(progressInterval);
      progressInterval = null;
      currentJob = null;
      
      downloadBtn.disabled = false;
      downloadBtn.innerHTML = '<i class="fas fa-cloud-download-alt"></i> Download';
      
      setTimeout(() => {
        progressBar.style.width = '0%';
      }, 3000);
      
    } else if (data.status === 'error') {
      throw new Error(data.error || 'Download failed');
    }
    
  } catch (err) {
    console.error('Progress error:', err);
    if (err.name !== 'AbortError') {
      showStatus('Download in progress...', 'info');
    }
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

urlInput.addEventListener('paste', () => setTimeout(preview, 100));
urlInput.addEventListener('blur', preview);

// Hide splash
window.addEventListener('load', () => {
  setTimeout(() => {
    document.getElementById('splash').style.display = 'none';
    document.querySelector('.app').style.display = 'block';
  }, 2000);
  updateOnlineStatus();
});

setTimeout(preview, 500);

// ==================== EXPOSE PUBLIC API ====================
window.app = { preview, startDownload };