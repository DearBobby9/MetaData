const uploadForm = document.getElementById('uploadForm');
const pdfInput = document.getElementById('pdfInput');
const dropzone = document.getElementById('dropzone');
const fileName = document.getElementById('fileName');
const statusMessage = document.getElementById('statusMessage');
const resultSection = document.getElementById('resultSection');
const metadataGrid = document.getElementById('metadataGrid');
const previewTitle = document.getElementById('previewTitle');
const previewAuthors = document.getElementById('previewAuthors');
const previewVenue = document.getElementById('previewVenue');
const previewLink = document.getElementById('previewLink');

const FIELD_ORDER = [
  { key: 'Title', label: 'Title', icon: '📄' },
  { key: 'Author list', label: 'Author list', icon: '👤' },
  { key: 'Venue', label: 'Venue', icon: '🏛️' },
  { key: 'Publication year', label: 'Year', icon: '🗓️' },
  { key: 'Abstract', label: 'Abstract', icon: '📝' },
  { key: 'DOI', label: 'DOI', icon: '🔗' },
  { key: 'Representative figure', label: 'Representative figure', icon: '🖼️' },
  { key: 'Video', label: 'Video', icon: '🎞️' },
];

const DEFAULT_STATUS = '等待上传 PDF…';
let selectedFile = null;

function setStatus(state, message) {
  statusMessage.textContent = message;
  statusMessage.className = `status-chip ${state}`;
}

function updateFileNameDisplay(name) {
  fileName.textContent = name || '尚未选择文件';
}

function resetResults() {
  resultSection.classList.add('hidden');
  metadataGrid.innerHTML = '';
}

function getCurrentFile() {
  return selectedFile || pdfInput.files[0] || null;
}

function renderMetadata(row) {
  metadataGrid.innerHTML = '';
  FIELD_ORDER.forEach((field) => {
    const wrapper = document.createElement('article');
    wrapper.className = 'meta-card';

    const icon = document.createElement('div');
    icon.className = 'meta-icon';
    icon.textContent = field.icon;

    const label = document.createElement('div');
    label.className = 'meta-label';
    label.textContent = field.label;

    const value = document.createElement('div');
    value.className = 'meta-value';
    const fieldValue = row[field.key] || 'N/A';
    value.textContent = fieldValue;

    wrapper.append(icon, label, value);
    metadataGrid.appendChild(wrapper);
  });
  resultSection.classList.remove('hidden');
}

function updatePreview(row, debugInfo) {
  previewTitle.textContent = row.Title || 'Untitled paper';
  previewAuthors.textContent = row['Author list'] || 'Unknown authors';
  const venueBits = [row.Venue, row['Publication year']].filter(Boolean);
  previewVenue.textContent = venueBits.join(' · ');

  const doiLink = debugInfo?.source_url;
  if (doiLink) {
    previewLink.href = doiLink;
    previewLink.hidden = false;
  } else {
    previewLink.hidden = true;
  }
}

function describeError(error) {
  if (typeof error === 'string') return error;
  if (error instanceof Error) return error.message;
  return '上传失败，请稍后再试。';
}

function syncSelectedFile(file) {
  selectedFile = file || null;
}

function attachDragHandlers() {
  ['dragenter', 'dragover'].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      event.stopPropagation();
      dropzone.classList.add('dragging');
    });
  });

  ['dragleave', 'dragend'].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      event.stopPropagation();
      dropzone.classList.remove('dragging');
    });
  });

  dropzone.addEventListener('drop', (event) => {
    event.preventDefault();
    dropzone.classList.remove('dragging');
    const { files } = event.dataTransfer || {};
    if (files && files.length > 0) {
      const file = files[0];
      syncSelectedFile(file);
      updateFileNameDisplay(file.name);
      pdfInput.value = '';
    }
  });
}

async function handleSubmit(event) {
  event.preventDefault();
  const file = getCurrentFile();
  if (!file) {
    setStatus('warning', '请先选择一个 PDF。');
    return;
  }

  setStatus('pending', '上传中…');
  resetResults();

  const formData = new FormData();
  formData.append('file', file);

  try {
    const response = await fetch('/api/upload', {
      method: 'POST',
      body: formData,
    });
    const payload = await response.json();

    if (!response.ok || payload.status !== 'ok') {
      throw new Error(payload.error || '服务器返回错误');
    }

    renderMetadata(payload.data);
    updatePreview(payload.data, payload.debug);
    setStatus('success', '提取完成，已填充 Spreadsheet 字段。');
  } catch (error) {
    setStatus('error', describeError(error));
  }
}

function init() {
  attachDragHandlers();
  uploadForm.addEventListener('submit', handleSubmit);
  pdfInput.addEventListener('change', () => {
    const selected = pdfInput.files[0];
    syncSelectedFile(selected || null);
    updateFileNameDisplay(selected ? selected.name : '');
    setStatus('idle', DEFAULT_STATUS);
  });
  setStatus('idle', DEFAULT_STATUS);
}

init();
