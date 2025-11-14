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
const fontSizeControl = document.getElementById('fontSizeControl');

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

const DATA_COLUMNS = [
  { key: 'Title', label: 'Title' },
  { key: 'Venue', label: 'Venue' },
  { key: 'Publication year', label: 'Year', className: 'year-col' },
  { key: 'Author list', label: 'Authors', className: 'authors-col' },
  { key: 'Abstract', label: 'Abstract', className: 'abstract-col' },
  { key: 'Representative figure', label: 'Representative figure' },
  { key: 'DOI', label: 'DOI', className: 'doi-col' },
  { key: 'Video', label: 'Video' },
];

const DEFAULT_STATUS = 'Waiting for PDFs…';
const MAX_FILES = 20;
const ERROR_MESSAGES = {
  DOI_NOT_FOUND: 'No DOI detected in this PDF. Make sure you are using the official ACM DL version.',
  CROSSREF_NOT_FOUND: 'Crossref could not find this DOI. It might be very new or unpublished.',
  CROSSREF_RATE_LIMIT: 'Crossref rate limit reached. Wait a few seconds and try again.',
  CROSSREF_SERVER_ERROR: 'Crossref returned a temporary server error. Please retry shortly.',
  CROSSREF_REQUEST_FAILED: 'Could not reach Crossref. Check your connection and try again.',
  PDF_PARSE_FAILED: 'Failed to read the PDF well enough to extract the abstract.',
  UNKNOWN_ERROR: 'Unexpected error while processing this PDF.',
};

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get('content-type') || '';
  const isJson = contentType.includes('application/json');
  const data = isJson ? await response.json().catch(() => null) : null;
  if (!response.ok) {
    const message = (data && (data.message || data.error || data.detail))
      || `Request failed with status ${response.status}`;
    const error = new Error(message);
    error.payload = data;
    error.status = response.status;
    throw error;
  }
  return data ?? {};
}

let selectedFiles = [];
let currentRecords = [];
let dragSourceId = null;
const TOTAL_TABLE_COLUMNS = DATA_COLUMNS.length + 2;
const columnWidths = {
  Title: '320px',
  Venue: '220px',
  'Publication year': '100px',
  'Author list': '240px',
  Abstract: '420px',
  'Representative figure': '160px',
  DOI: '150px',
  Video: '140px',
};
const rowHeights = {};
const columnMinWidths = {
  Title: 220,
  Venue: 180,
  'Publication year': 80,
  'Author list': 200,
  Abstract: 280,
  'Representative figure': 140,
  DOI: 120,
  Video: 120,
};
const MIN_COLUMN_WIDTH = 120;
const MIN_ROW_HEIGHT = 48;
const ROW_RESIZE_HANDLE = 16;
const COLUMN_HANDLE_WIDTH = 18;
const tableWrapper = document.querySelector('.table-wrapper');
let isRowResizing = false;
let rowResizeHover = null;

function setStatus(state, message, code = '') {
  statusMessage.textContent = message;
  statusMessage.className = `status-chip ${state}`;
  statusMessage.dataset.state = state;
  if (code) {
    statusMessage.dataset.code = code;
    statusMessage.title = `${code}: ${message}`;
  } else {
    delete statusMessage.dataset.code;
    statusMessage.removeAttribute('title');
  }
}

function updateFileNameDisplay() {
  if (!selectedFiles.length) {
    fileName.textContent = 'No files selected yet';
    return;
  }

  if (selectedFiles.length === 1) {
    fileName.textContent = selectedFiles[0].name;
    return;
  }

  fileName.textContent = `${selectedFiles[0].name} + ${selectedFiles.length - 1} more`;
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
    previewTitle.textContent = 'No paper yet';
    previewAuthors.textContent = 'Authors will appear after the first upload.';
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
  const fallback = 'Upload failed, please try again later.';
  if (!error) return fallback;
  if (typeof error === 'string') return error;

  if (error.payload) {
    const nested = describeError(error.payload);
    return nested || fallback;
  }

  if (error.code && ERROR_MESSAGES[error.code]) {
    return ERROR_MESSAGES[error.code];
  }

  if (typeof error.message === 'string' && error.message.trim()) {
    return error.message;
  }

  if (typeof error.error === 'string' && error.error.trim()) {
    return error.error;
  }

  if (typeof error.detail === 'string' && error.detail.trim()) {
    return error.detail;
  }

  if (error.detail && typeof error.detail === 'object') {
    const nested = describeError(error.detail);
    if (nested) return nested;
  }

  if (error instanceof Error) {
    return error.message || fallback;
  }

  return fallback;
}

function getErrorCode(error) {
  if (!error || typeof error === 'string') return '';
  if (typeof error.code === 'string' && error.code) return error.code;
  if (error.payload) return getErrorCode(error.payload);
  if (error.detail && typeof error.detail === 'object') return getErrorCode(error.detail);
  return '';
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
    setStatus('warning', `You can upload up to ${MAX_FILES} files at once (extras were ignored).`);
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
    name.textContent = item.file_name || item?.data?.file_name || item?.data?.Title || 'Unknown file';
    const state = document.createElement('span');
    if (item.status === 'ok') {
      state.textContent = 'Success';
      delete state.dataset.code;
      state.removeAttribute('title');
    } else {
      const message = describeError(item);
      const code = getErrorCode(item);
      state.textContent = message;
      if (code) {
        state.dataset.code = code;
        state.title = code;
      }
    }
    li.append(name, state);
    uploadLog.appendChild(li);
  });
}

async function fetchRecords() {
  try {
    const payload = await api('/api/records');
    currentRecords = Array.isArray(payload.records) ? payload.records : [];
    renderRecordsTable();
  } catch (error) {
    console.error('Failed to load records', error);
    setStatus('warning', describeError(error), getErrorCode(error));
  }
}

function renderRecordsTable() {
  recordCount.textContent = currentRecords.length;
  recordsBody.innerHTML = '';
  clearRowResizeHover();
  isRowResizing = false;
  setRowResizeCursor(false);

  if (!currentRecords.length) {
    const row = document.createElement('tr');
    row.className = 'empty-row';
    const cell = document.createElement('td');
    cell.colSpan = TOTAL_TABLE_COLUMNS;
    cell.textContent = 'No records yet — upload some PDFs first.';
    row.appendChild(cell);
    recordsBody.appendChild(row);
    applyColumnWidths();
    return;
  }

  currentRecords.forEach((record, index) => {
    const tr = document.createElement('tr');
    tr.dataset.id = record.id;
    tr.draggable = true;

    const handleTd = document.createElement('td');
    handleTd.dataset.column = 'order';
    handleTd.className = 'handle-cell';
    handleTd.textContent = index + 1;
    tr.appendChild(handleTd);

    DATA_COLUMNS.forEach((column) => {
      const td = document.createElement('td');
      td.dataset.columnKey = column.key;
      if (column.className) td.classList.add(column.className);
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

    const actionsTd = document.createElement('td');
    actionsTd.dataset.column = 'actions';
    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'row-btn delete-row';
    deleteBtn.dataset.id = record.id;
    deleteBtn.textContent = 'Delete';
    actionsTd.appendChild(deleteBtn);
    tr.appendChild(actionsTd);

    recordsBody.appendChild(tr);
  });
  applyColumnWidths();
  applyRowHeights();
}

recordsBody.addEventListener('click', async (event) => {
  const deleteBtn = event.target.closest('.delete-row');
  if (!deleteBtn) return;
  const recordId = deleteBtn.dataset.id;
  if (!recordId) return;
  if (!confirm('Delete this record?')) return;
  await deleteRecord(recordId);
});

function isInRowResizeZone(row, clientY) {
  const rect = row.getBoundingClientRect();
  return rect.bottom - clientY <= ROW_RESIZE_HANDLE;
}

function setRowResizeCursor(active) {
  if (!tableWrapper) return;
  if (active) {
    tableWrapper.classList.add('row-resize-cursor');
  } else {
    tableWrapper.classList.remove('row-resize-cursor');
  }
}

function clearRowResizeHover() {
  if (rowResizeHover) {
    rowResizeHover.classList.remove('row-resize-hover');
    rowResizeHover = null;
  }
  if (!isRowResizing) {
    setRowResizeCursor(false);
  }
}

function handleRowResizeMouseDown(event) {
  if (isRowResizing) return;
  const row = event.target.closest('tr[data-id]');
  if (!row) return;
  if (!isInRowResizeZone(row, event.clientY)) return;
  event.preventDefault();
  const recordId = row.dataset.id;
  const startY = event.clientY;
  const startHeight = row.getBoundingClientRect().height;
  isRowResizing = true;
  row.classList.add('resizing');
  setRowResizeCursor(true);

  const onMouseMove = (moveEvent) => {
    const delta = moveEvent.clientY - startY;
    const newHeight = Math.max(MIN_ROW_HEIGHT, startHeight + delta);
    rowHeights[recordId] = `${newHeight}px`;
    applyRowHeights();
  };

  const onMouseUp = () => {
    document.removeEventListener('mousemove', onMouseMove);
    document.removeEventListener('mouseup', onMouseUp);
    row.classList.remove('resizing');
    isRowResizing = false;
    clearRowResizeHover();
    setRowResizeCursor(false);
  };

  document.addEventListener('mousemove', onMouseMove);
  document.addEventListener('mouseup', onMouseUp);
}

recordsBody.addEventListener('mousedown', handleRowResizeMouseDown);

recordsBody.addEventListener('mousemove', (event) => {
  if (isRowResizing) return;
  const row = event.target.closest('tr[data-id]');
  if (!row) {
    clearRowResizeHover();
    return;
  }
  if (isInRowResizeZone(row, event.clientY)) {
    if (rowResizeHover && rowResizeHover !== row) {
      rowResizeHover.classList.remove('row-resize-hover');
    }
    rowResizeHover = row;
    row.classList.add('row-resize-hover');
    setRowResizeCursor(true);
  } else if (rowResizeHover === row) {
    clearRowResizeHover();
  }
});

recordsBody.addEventListener('mouseleave', () => {
  if (isRowResizing) return;
  clearRowResizeHover();
});

recordsBody.addEventListener('dragstart', (event) => {
  const row = event.target.closest('tr[data-id]');
  if (!row) return;
  if (isRowResizing) {
    event.preventDefault();
    return;
  }
  dragSourceId = row.dataset.id;
  row.classList.add('dragging');
  event.dataTransfer.effectAllowed = 'move';
});

recordsBody.addEventListener('dragend', (event) => {
  const row = event.target.closest('tr[data-id]');
  if (row) {
    row.classList.remove('dragging');
    row.classList.remove('drag-over');
  }
  dragSourceId = null;
});

recordsBody.addEventListener('dragover', (event) => {
  event.preventDefault();
  if (isRowResizing) return;
  const row = event.target.closest('tr[data-id]');
  if (!row || row.dataset.id === dragSourceId) return;
  row.classList.add('drag-over');
});

recordsBody.addEventListener('dragleave', (event) => {
  const row = event.target.closest('tr[data-id]');
  if (row) {
    row.classList.remove('drag-over');
  }
});

recordsBody.addEventListener('drop', (event) => {
  event.preventDefault();
  if (isRowResizing) return;
  const row = event.target.closest('tr[data-id]');
  if (!row || !dragSourceId || row.dataset.id === dragSourceId) return;
  reorderRecordsLocally(dragSourceId, row.dataset.id);
  row.classList.remove('drag-over');
  persistCurrentOrder();
});

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
    setStatus('warning', 'Pick at least one PDF first.');
    return;
  }

  setStatus('pending', `Uploading ${selectedFiles.length} file(s)…`);
  resetResults();
  renderUploadLog([]);

  const formData = new FormData();
  selectedFiles.forEach((file) => formData.append('files', file));

  try {
    const payload = await api('/api/upload/batch', {
      method: 'POST',
      body: formData,
    });
    const items = Array.isArray(payload.items) ? payload.items : [];
    const successItems = items.filter((item) => item.status === 'ok');
    renderUploadLog(items);

    if (successItems.length) {
      renderMetadata(successItems[0].data);
      updatePreview(successItems[0].data, successItems[0].debug);
      const failed = items.length - successItems.length;
      if (failed > 0) {
        const failedItem = items.find((item) => item.status !== 'ok');
        const failureMessage = failedItem ? describeError(failedItem) : `${failed} failed`;
        const failureCode = failedItem ? getErrorCode(failedItem) : '';
        setStatus(
          'warning',
          `Processed ${successItems.length}/${items.length} — ${failed} failed (${failureMessage})`,
          failureCode,
        );
      } else {
        setStatus('success', `Processed ${successItems.length}/${items.length}`);
      }
    } else {
      resetResults();
      const message = payload.error || describeError(payload) || 'Every file failed — please verify your PDFs.';
      const code = payload.code || getErrorCode(payload);
      setStatus('error', message, code);
    }

    setSelectedFiles([]);
    pdfInput.value = '';
    await fetchRecords();
  } catch (error) {
    console.error('Upload failed', error);
    setStatus('error', describeError(error), getErrorCode(error));
  }
}

function reorderRecordsLocally(sourceId, targetId) {
  const sourceIndex = currentRecords.findIndex((record) => record.id === sourceId);
  const targetIndex = currentRecords.findIndex((record) => record.id === targetId);
  if (sourceIndex < 0 || targetIndex < 0) return;
  const [moved] = currentRecords.splice(sourceIndex, 1);
  const insertIndex = sourceIndex < targetIndex ? targetIndex - 1 : targetIndex;
  currentRecords.splice(insertIndex, 0, moved);
  renderRecordsTable();
}

async function persistCurrentOrder() {
  try {
    await api('/api/records/reorder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ order: currentRecords.map((record) => record.id) }),
    });
  } catch (error) {
    console.error('Failed to persist order', error);
    setStatus('warning', describeError(error), getErrorCode(error));
  }
}

async function deleteRecord(recordId) {
  try {
    await api(`/api/records/${encodeURIComponent(recordId)}`, {
      method: 'DELETE',
    });
    currentRecords = currentRecords.filter((record) => record.id !== recordId);
    renderRecordsTable();
    setStatus('success', 'Record deleted from library.');
  } catch (error) {
    console.error(error);
    alert(describeError(error));
    setStatus('error', describeError(error), getErrorCode(error));
  }
}

function setTableFontSize(value) {
  const numeric = Number(value);
  const clamped = Math.min(20, Math.max(12, Number.isNaN(numeric) ? 15 : numeric));
  document.documentElement.style.setProperty('--table-font-size', `${clamped}px`);
}

function initFontSizeControl() {
  if (!fontSizeControl) return;
  setTableFontSize(fontSizeControl.value);
  fontSizeControl.addEventListener('input', () => setTableFontSize(fontSizeControl.value));
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

  initColumnResizers();
  initFontSizeControl();
  setStatus('idle', DEFAULT_STATUS);
  fetchRecords();
}

init();
function getColumnKeyFromElement(el) {
  return el?.dataset?.columnKey || el?.dataset?.column;
}

function getMinColumnWidth(key) {
  return columnMinWidths[key] || MIN_COLUMN_WIDTH;
}

function applyColumnWidths() {
  const headerCells = document.querySelectorAll('th[data-column], th[data-column-key]');
  headerCells.forEach((th) => {
    const key = getColumnKeyFromElement(th);
    if (!key) return;
    const width = columnWidths[key];
    if (width) {
      th.style.width = width;
      th.style.minWidth = width;
      th.style.maxWidth = width;
    }
  });

  recordsBody.querySelectorAll('td[data-column], td[data-column-key]').forEach((td) => {
    const key = getColumnKeyFromElement(td);
    if (!key) return;
    const width = columnWidths[key];
    if (width) {
      td.style.width = width;
      td.style.minWidth = width;
      td.style.maxWidth = width;
    }
  });
}

function applyRowHeights() {
  recordsBody.querySelectorAll('tr[data-id]').forEach((tr) => {
    const id = tr.dataset.id;
    const height = rowHeights[id];
    if (height) {
      tr.style.height = height;
    } else {
      tr.style.height = '';
    }
  });
}

function isWithinColumnHandle(th, clientX) {
  const rect = th.getBoundingClientRect();
  return rect.right - clientX <= COLUMN_HANDLE_WIDTH;
}

function startColumnResize(th, key, startX) {
  const initialWidth = parseInt(columnWidths[key] || th.offsetWidth, 10);
  th.classList.add('col-resizing');
  document.body.style.userSelect = 'none';

  const onMouseMove = (event) => {
    const delta = event.clientX - startX;
    const minWidth = getMinColumnWidth(key);
    const newWidth = Math.max(minWidth, initialWidth + delta);
    columnWidths[key] = `${newWidth}px`;
    applyColumnWidths();
  };

  const onMouseUp = () => {
    document.removeEventListener('mousemove', onMouseMove);
    document.removeEventListener('mouseup', onMouseUp);
    th.classList.remove('col-resizing');
    document.body.style.userSelect = '';
  };

  document.addEventListener('mousemove', onMouseMove);
  document.addEventListener('mouseup', onMouseUp);
}

function initColumnResizers() {
  const headerCells = document.querySelectorAll('th[data-column], th[data-column-key]');
  headerCells.forEach((th) => {
    const key = getColumnKeyFromElement(th);
    if (!key || key === 'order' || key === 'actions') return;
    let resizer = th.querySelector('.col-resizer');
    if (!resizer) {
      resizer = document.createElement('span');
      resizer.className = 'col-resizer';
      th.appendChild(resizer);
    }

    const startResize = (event) => {
      event.preventDefault();
      startColumnResize(th, key, event.clientX);
    };

    resizer.addEventListener('mousedown', startResize);
    th.addEventListener('mousedown', (event) => {
      if (event.target.closest('.col-resizer')) return;
      if (!isWithinColumnHandle(th, event.clientX)) return;
      startResize(event);
    });
    th.addEventListener('mousemove', (event) => {
      if (isWithinColumnHandle(th, event.clientX)) {
        th.classList.add('col-resize-hover');
      } else if (!th.classList.contains('col-resizing')) {
        th.classList.remove('col-resize-hover');
      }
    });
    th.addEventListener('mouseleave', () => {
      if (!th.classList.contains('col-resizing')) {
        th.classList.remove('col-resize-hover');
      }
    });
  });
  applyColumnWidths();
}
