const uploadForm = document.getElementById('uploadForm');
const pdfInput = document.getElementById('pdfInput');
const dropzone = document.getElementById('dropzone');
const fileName = document.getElementById('fileName');
const statusMessage = document.getElementById('statusMessage');
const uploadLog = document.getElementById('uploadLog');
const resultSection = document.getElementById('resultSection');
const metadataGrid = document.getElementById('metadataGrid');
const previewTitle = document.getElementById('previewTitle');
const previewAuthors = document.getElementById('previewAuthors');
const previewVenue = document.getElementById('previewVenue');
const previewLink = document.getElementById('previewLink');
const navButtons = document.querySelectorAll('[data-view-target]');
const viewSections = document.querySelectorAll('.view-section');
const recordsBody = document.getElementById('recordsBody');
const recordCount = document.getElementById('recordCount');
const refreshRecordsBtn = document.getElementById('refreshRecords');

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

const TABLE_COLUMNS = [
  { key: 'Title', label: 'Title' },
  { key: 'Venue', label: 'Venue' },
  { key: 'Publication year', label: 'Year' },
  { key: 'Author list', label: 'Authors' },
  { key: 'Abstract', label: 'Abstract' },
  { key: 'Representative figure', label: 'Representative figure' },
  { key: 'DOI', label: 'DOI' },
  { key: 'Video', label: 'Video' },
];

const DEFAULT_STATUS = '等待上传 PDF…';
const MAX_FILES = 20;
let selectedFiles = [];

function setStatus(state, message) {
  statusMessage.textContent = message;
  statusMessage.className = `status-chip ${state}`;
}

function updateFileNameDisplay() {
  if (!selectedFiles.length) {
    fileName.textContent = '尚未选择文件';
    return;
  }

  if (selectedFiles.length === 1) {
    fileName.textContent = selectedFiles[0].name;
    return;
  }

  fileName.textContent = `${selectedFiles[0].name} 等 ${selectedFiles.length} 个文件`;
}

function resetResults() {
  resultSection.classList.add('hidden');
  metadataGrid.innerHTML = '';
}

function renderMetadata(row) {
  if (!row) {
    resetResults();
    return;
  }

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
    value.textContent = row[field.key] || 'N/A';

    wrapper.append(icon, label, value);
    metadataGrid.appendChild(wrapper);
  });
  resultSection.classList.remove('hidden');
}

function updatePreview(row, debugInfo) {
  if (!row) {
    previewTitle.textContent = '暂无论文';
    previewAuthors.textContent = '上传后会展示作者列表。';
    previewVenue.textContent = '';
    previewLink.hidden = true;
    return;
  }

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

function setSelectedFiles(filesArray) {
  selectedFiles = filesArray;
  updateFileNameDisplay();
}

function handleFileSelection(fileList) {
  const arr = Array.from(fileList || []);
  if (!arr.length) {
    setSelectedFiles([]);
    return;
  }

  if (arr.length > MAX_FILES) {
    setStatus('warning', `一次最多上传 ${MAX_FILES} 个文件，已自动截断。`);
  }
  setSelectedFiles(arr.slice(0, MAX_FILES));
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
    const files = event.dataTransfer?.files;
    if (files && files.length) {
      handleFileSelection(files);
      pdfInput.value = '';
    }
  });
}

function renderUploadLog(items) {
  if (!uploadLog) return;
  uploadLog.innerHTML = '';
  if (!items || !items.length) return;

  items.forEach((item) => {
    const li = document.createElement('li');
    li.className = item.status === 'ok' ? 'ok' : 'error';
    const name = document.createElement('span');
    name.textContent = item.file_name || item?.data?.file_name || item?.data?.Title || '未知文件';
    const state = document.createElement('span');
    state.textContent = item.status === 'ok' ? '成功' : (item.error || '失败');
    li.append(name, state);
    uploadLog.appendChild(li);
  });
}

async function fetchRecords() {
  try {
    const response = await fetch('/api/records');
    const payload = await response.json();
    renderRecordsTable(Array.isArray(payload.records) ? payload.records : []);
  } catch (error) {
    console.error('Failed to load records', error);
  }
}

function renderRecordsTable(records) {
  recordCount.textContent = records.length;
  recordsBody.innerHTML = '';

  if (!records.length) {
    const row = document.createElement('tr');
    row.className = 'empty-row';
    const cell = document.createElement('td');
    cell.colSpan = TABLE_COLUMNS.length;
    cell.textContent = '暂无数据，先去上传一些 PDF 吧。';
    row.appendChild(cell);
    recordsBody.appendChild(row);
    return;
  }

  records.forEach((record) => {
    const tr = document.createElement('tr');
    TABLE_COLUMNS.forEach((column) => {
      const td = document.createElement('td');
      if (column.key === 'DOI' && record.source_url) {
        const link = document.createElement('a');
        link.href = record.source_url;
        link.target = '_blank';
        link.rel = 'noreferrer';
        link.textContent = record[column.key] || 'N/A';
        td.appendChild(link);
      } else {
        td.textContent = record[column.key] || 'N/A';
      }
      tr.appendChild(td);
    });
    recordsBody.appendChild(tr);
  });
}

function switchView(targetId) {
  viewSections.forEach((section) => {
    if (section.id === targetId) {
      section.classList.remove('hidden');
    } else {
      section.classList.add('hidden');
    }
  });

  navButtons.forEach((button) => {
    button.classList.toggle('active', button.dataset.viewTarget === targetId);
  });

  if (targetId === 'libraryView') {
    fetchRecords();
  }
}

async function handleSubmit(event) {
  event.preventDefault();
  if (!selectedFiles.length) {
    setStatus('warning', '请先选择至少一个 PDF。');
    return;
  }

  setStatus('pending', `上传中（${selectedFiles.length} 个文件）…`);
  resetResults();
  renderUploadLog([]);

  const formData = new FormData();
  selectedFiles.forEach((file) => formData.append('files', file));

  try {
    const response = await fetch('/api/upload/batch', {
      method: 'POST',
      body: formData,
    });
    const payload = await response.json();

    if (!response.ok) {
      throw new Error(payload.error || '服务器返回错误');
    }

    const items = Array.isArray(payload.items) ? payload.items : [];
    const successItems = items.filter((item) => item.status === 'ok');
    renderUploadLog(items);

    if (successItems.length) {
      renderMetadata(successItems[0].data);
      updatePreview(successItems[0].data, successItems[0].debug);
      const failed = items.length - successItems.length;
      const suffix = failed > 0 ? `，${failed} 篇失败` : '';
      setStatus('success', `成功处理 ${successItems.length}/${items.length} 篇${suffix}`);
    } else {
      resetResults();
      setStatus('error', payload.error || '所有文件均处理失败，请检查 PDF。');
    }

    setSelectedFiles([]);
    pdfInput.value = '';
    await fetchRecords();
  } catch (error) {
    setStatus('error', describeError(error));
  }
}

function init() {
  attachDragHandlers();
  uploadForm.addEventListener('submit', handleSubmit);
  pdfInput.addEventListener('change', () => {
    handleFileSelection(pdfInput.files);
    pdfInput.value = '';
    setStatus('idle', DEFAULT_STATUS);
  });

  navButtons.forEach((button) => {
    button.addEventListener('click', () => switchView(button.dataset.viewTarget));
  });

  if (refreshRecordsBtn) {
    refreshRecordsBtn.addEventListener('click', fetchRecords);
  }

  setStatus('idle', DEFAULT_STATUS);
  fetchRecords();
}

init();
