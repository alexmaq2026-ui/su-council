/* ═══════════════════════════════════════════════════════
   University Council - Main JavaScript
   Handles: Clock, Alerts, Vote, Audio Recording, Search
═══════════════════════════════════════════════════════ */

'use strict';

// ═══════════════════════════════════════════════════════
// CSRF Helper
// ═══════════════════════════════════════════════════════
function getCsrfToken() {
  return document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
         document.cookie.split(';')
           .find(c => c.trim().startsWith('csrftoken='))
           ?.split('=')[1] || '';
}

// ═══════════════════════════════════════════════════════
// API Helper
// ═══════════════════════════════════════════════════════
async function apiPost(url, data) {
  const resp = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCsrfToken(),
      'X-Requested-With': 'XMLHttpRequest',
    },
    body: JSON.stringify(data),
  });
  return resp.json();
}

async function apiFormPost(url, formData) {
  const resp = await fetch(url, {
    method: 'POST',
    headers: {
      'X-CSRFToken': getCsrfToken(),
      'X-Requested-With': 'XMLHttpRequest',
    },
    body: formData,
  });
  return resp.json();
}

// ═══════════════════════════════════════════════════════
// VOTE SYSTEM
// ═══════════════════════════════════════════════════════
function initVotePanel() {
  const voteBtns = document.querySelectorAll('.vote-btn[data-choice]');
  const notesField = document.getElementById('vote-notes');
  const voteHiddenInput = document.getElementById('vote-choice-input');
  const voteSubmitBtn = document.getElementById('vote-submit-btn');

  if (!voteBtns.length) return;

  let selectedChoice = null;

  voteBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      // Deselect all
      voteBtns.forEach(b => b.classList.remove('selected'));
      // Select this
      btn.classList.add('selected');
      selectedChoice = btn.dataset.choice;
      if (voteHiddenInput) voteHiddenInput.value = selectedChoice;

      // Show notes field for reject/reserve
      if (notesField) {
        const wrapper = document.getElementById('vote-notes-wrapper');
        if (wrapper) {
          if (selectedChoice === 'reserve' || selectedChoice === 'reject') {
            wrapper.style.display = 'block';
            wrapper.style.animation = 'fadeIn 0.3s ease';
          } else {
            wrapper.style.display = 'none';
          }
        }
      }
    });
  });

  // Submit vote
  if (voteSubmitBtn) {
    voteSubmitBtn.addEventListener('click', async () => {
      if (!selectedChoice) {
        showToast('يرجى اختيار أحد خيارات التصويت', 'warning');
        return;
      }

      const topicId = voteSubmitBtn.dataset.topicId;
      const notes = notesField ? notesField.value.trim() : '';

      voteSubmitBtn.disabled = true;
      voteSubmitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>جاري الإرسال...';

      try {
        const data = await apiPost(`/topics/${topicId}/vote/`, {
          choice: selectedChoice,
          notes: notes,
        });

        if (data.success) {
          showToast(data.message || 'تم تسجيل تصويتك بنجاح', 'success');
          if (data.results) updateVoteResults(data.results);
          // Update button state
          voteSubmitBtn.innerHTML = '<i class="bi bi-check-circle me-2"></i>تم التصويت';
          voteSubmitBtn.classList.remove('btn-navy');
          voteSubmitBtn.classList.add('btn-success');
        } else {
          showToast(data.message || 'حدث خطأ في التصويت', 'error');
          voteSubmitBtn.disabled = false;
          voteSubmitBtn.innerHTML = '<i class="bi bi-check2-circle me-2"></i>تأكيد التصويت';
        }
      } catch (err) {
        showToast('خطأ في الاتصال بالخادم', 'error');
        voteSubmitBtn.disabled = false;
        voteSubmitBtn.innerHTML = '<i class="bi bi-check2-circle me-2"></i>تأكيد التصويت';
      }
    });
  }
}

function updateVoteResults(results) {
  const total = results.total || 0;
  if (!total) return;

  const updateBar = (id, count) => {
    const el = document.getElementById(id);
    if (el) el.style.width = `${Math.round((count / total) * 100)}%`;
  };
  const updateCount = (id, count) => {
    const el = document.getElementById(id);
    if (el) el.textContent = count;
  };

  updateBar('bar-approve', results.approve || 0);
  updateBar('bar-reject', results.reject || 0);
  updateBar('bar-reserve', results.reserve || 0);
  updateCount('count-approve', results.approve || 0);
  updateCount('count-reject', results.reject || 0);
  updateCount('count-reserve', results.reserve || 0);
  updateCount('count-total', total);
}

// ═══════════════════════════════════════════════════════
// AUDIO RECORDER
// ═══════════════════════════════════════════════════════
class AudioRecorder {
  constructor(topicId) {
    this.topicId = topicId;
    this.mediaRecorder = null;
    this.stream = null;
    this.chunks = [];
    this.startTime = null;
    this.timerInterval = null;
    this.isRecording = false;

    this.btn = document.getElementById('record-btn');
    this.timer = document.getElementById('record-timer');
    this.status = document.getElementById('record-status');
    this.waveform = document.getElementById('record-waveform');
    this.saveForm = document.getElementById('recording-save-form');

    if (this.btn) {
      this.btn.addEventListener('click', () => this.toggle());
    }
  }

  async toggle() {
    if (this.isRecording) {
      this.stop();
    } else {
      await this.start();
    }
  }

  async start() {
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.mediaRecorder = new MediaRecorder(this.stream);
      this.chunks = [];

      this.mediaRecorder.ondataavailable = e => {
        if (e.data.size > 0) this.chunks.push(e.data);
      };

      this.mediaRecorder.onstop = () => this.onStop();
      this.mediaRecorder.start(1000);
      this.isRecording = true;
      this.startTime = Date.now();

      // Update UI
      this.btn.classList.add('recording');
      this.btn.innerHTML = '<i class="bi bi-stop-fill"></i>';
      if (this.status) this.status.textContent = 'جاري التسجيل...';
      if (this.waveform) this.waveform.style.display = 'flex';

      // Start timer
      this.timerInterval = setInterval(() => this.updateTimer(), 1000);

    } catch (err) {
      if (err.name === 'NotAllowedError') {
        showToast('يرجى السماح للمتصفح بالوصول للميكروفون', 'warning');
      } else {
        showToast('تعذر الوصول للميكروفون: ' + err.message, 'error');
      }
    }
  }

  stop() {
    if (this.mediaRecorder && this.isRecording) {
      this.mediaRecorder.stop();
      this.stream.getTracks().forEach(t => t.stop());
      this.isRecording = false;
      clearInterval(this.timerInterval);

      // Reset UI
      this.btn.classList.remove('recording');
      this.btn.innerHTML = '<i class="bi bi-mic-fill"></i>';
      if (this.status) this.status.textContent = 'جاري الحفظ...';
      if (this.waveform) this.waveform.style.display = 'none';
    }
  }

  updateTimer() {
    const elapsed = Math.floor((Date.now() - this.startTime) / 1000);
    const m = Math.floor(elapsed / 60).toString().padStart(2, '0');
    const s = (elapsed % 60).toString().padStart(2, '0');
    if (this.timer) this.timer.textContent = `${m}:${s}`;
  }

  async onStop() {
    const blob = new Blob(this.chunks, { type: 'audio/webm' });
    const duration = Math.floor((Date.now() - this.startTime) / 1000);

    const fd = new FormData();
    fd.append('audio', blob, `recording_${this.topicId}_${Date.now()}.webm`);
    fd.append('duration', duration);

    const labelEl = document.getElementById('recording-label');
    if (labelEl) fd.append('label', labelEl.value);

    try {
      const data = await apiFormPost(`/topics/${this.topicId}/record/save/`, fd);
      if (data && (data.success || data.ok)) {
        showToast('تم حفظ التسجيل بنجاح', 'success');
        if (this.status) this.status.textContent = 'تم الحفظ ✓';
        const recData = data.recording || {
          id: data.recording_id || data.id,
          label: data.label,
          duration: data.duration,
          audio_url: data.audio_url,
          recorded_at: data.recorded_at
        };
        addRecordingToList(recData);
        if (this.timer) this.timer.textContent = '00:00';
        if (labelEl) labelEl.value = '';
      } else {
        showToast((data && (data.error || data.message)) || 'خطأ في حفظ التسجيل', 'error');
        if (this.status) this.status.textContent = 'جاهز للتسجيل';
      }
    } catch (err) {
      showToast('خطأ في رفع التسجيل: ' + (err.message || err), 'error');
      if (this.status) this.status.textContent = 'جاهز للتسجيل';
    }
  }
}

function addRecordingToList(rec) {
  const list = document.getElementById('recordings-list');
  if (!list) return;

  const empty = list.querySelector('.empty-state') || list.querySelector('.empty-state-rec');
  if (empty) empty.remove();

  const audioUrl = rec.audio_url || rec.url || '';
  const dur = rec.duration || rec.duration_display || '00:00';

  const item = document.createElement('div');
  item.className = 'attachment-item';
  item.innerHTML = `
    <div class="d-flex align-items-center gap-2 flex-grow-1">
      <div class="attachment-icon bg-danger text-white"><i class="bi bi-mic-fill"></i></div>
      <div>
        <div class="fw-bold">${rec.label || 'تسجيل نقاش الموضوع'}</div>
        <small class="text-muted">${dur} · ${rec.recorded_at}</small>
      </div>
    </div>
    <div class="d-flex align-items-center gap-2">
      <audio controls src="${audioUrl}" style="height:36px; max-width:200px;"></audio>
      <form method="post" action="/recordings/${rec.id}/delete/" onsubmit="return confirm('حذف هذا التسجيل الصوتي؟')">
        <input type="hidden" name="csrfmiddlewaretoken" value="${getCookie('csrftoken')}">
        <button type="submit" class="btn btn-sm btn-outline-danger btn-icon">
          <i class="bi bi-trash"></i>
        </button>
      </form>
    </div>
  `;
  list.prepend(item);
}

// ═══════════════════════════════════════════════════════
// TOAST NOTIFICATIONS
// ═══════════════════════════════════════════════════════
function showToast(message, type = 'info') {
  const colors = {
    success: '#1a7a4a', error: '#c0392b', warning: '#d4850a', info: '#0f3460',
  };
  const icons = {
    success: 'bi-check-circle-fill', error: 'bi-x-circle-fill',
    warning: 'bi-exclamation-triangle-fill', info: 'bi-info-circle-fill',
  };

  // Container
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.style.cssText = 'position:fixed;top:80px;left:16px;z-index:9999;display:flex;flex-direction:column;gap:8px;max-width:340px;';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.style.cssText = `
    background:${colors[type] || colors.info};
    color:#fff;
    border-radius:12px;
    padding:12px 16px;
    font-family:'Cairo',Arial,sans-serif;
    font-size:0.9rem;
    font-weight:600;
    display:flex;
    align-items:center;
    gap:10px;
    box-shadow:0 8px 24px rgba(0,0,0,0.25);
    animation:slideIn 0.3s ease;
    direction:rtl;
    text-align:right;
  `;
  toast.innerHTML = `<i class="bi ${icons[type] || icons.info}" style="font-size:1.2rem;flex-shrink:0;"></i><span>${message}</span>`;

  container.appendChild(toast);

  // Auto remove
  setTimeout(() => {
    toast.style.animation = 'fadeOut 0.3s ease forwards';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// Add toast animations
const style = document.createElement('style');
style.textContent = `
  @keyframes slideIn { from { opacity:0; transform:translateX(-20px); } to { opacity:1; transform:translateX(0); } }
  @keyframes fadeOut { to { opacity:0; transform:translateX(-20px); } }
  @keyframes fadeIn  { from { opacity:0; } to { opacity:1; } }
`;
document.head.appendChild(style);

// ═══════════════════════════════════════════════════════
// FILE UPLOAD DRAG & DROP
// ═══════════════════════════════════════════════════════
function initUploadZone() {
  const zone = document.querySelector('.upload-zone');
  if (!zone) return;

  const input = zone.querySelector('input[type=file]');

  zone.addEventListener('click', () => input?.click());

  zone.addEventListener('dragover', e => {
    e.preventDefault();
    zone.classList.add('dragover');
  });

  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));

  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('dragover');
    if (input && e.dataTransfer.files.length) {
      input.files = e.dataTransfer.files;
      updateFileLabel(zone, e.dataTransfer.files);
    }
  });

  if (input) {
    input.addEventListener('change', () => updateFileLabel(zone, input.files));
  }
}

function updateFileLabel(zone, files) {
  const label = zone.querySelector('.upload-label');
  if (label && files.length) {
    label.textContent = files.length === 1
      ? files[0].name
      : `${files.length} ملفات محددة`;
  }
}

// ═══════════════════════════════════════════════════════
// LIVE SEARCH (client-side highlight)
// ═══════════════════════════════════════════════════════
function initLiveSearch() {
  const input = document.getElementById('live-search-input');
  const items = document.querySelectorAll('.searchable-item');
  if (!input || !items.length) return;

  input.addEventListener('input', () => {
    const q = input.value.trim().toLowerCase();
    items.forEach(item => {
      const text = item.textContent.toLowerCase();
      item.style.display = !q || text.includes(q) ? '' : 'none';
    });
  });
}

// ═══════════════════════════════════════════════════════
// CONFIRM DELETE
// ═══════════════════════════════════════════════════════
function confirmDelete(message) {
  return confirm(message || 'هل أنت متأكد من الحذف؟ لا يمكن التراجع.');
}

// ═══════════════════════════════════════════════════════
// INITIALIZE ON DOM READY
// ═══════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {
  initVotePanel();
  initUploadZone();
  initLiveSearch();

  // Init audio recorder if on topic page
  const recordBtn = document.getElementById('record-btn');
  if (recordBtn) {
    const topicId = recordBtn.dataset.topicId;
    if (topicId) window.recorder = new AudioRecorder(topicId);
  }

  // Initialize Bootstrap tooltips
  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
    new bootstrap.Tooltip(el, { trigger: 'hover' });
  });

  // Smooth scroll on hash links
  document.querySelectorAll('a[href^="#"]').forEach(a => {
    a.addEventListener('click', e => {
      const target = document.querySelector(a.getAttribute('href'));
      if (target) {
        e.preventDefault();
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  });
});
