document.addEventListener('DOMContentLoaded', () => {
    // State
    let state = {
        activeTab: 'hf-tab',
        modelSource: null, // Holds {type: 'hf', data: {...}} or {type: 'local', data: File}
        selectedDrivePath: null,
        isFlashing: false
    };

    // DOM Elements
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    const hfModelSelect = document.getElementById('hf-model-select');
    const hfInfo = document.getElementById('hf-info');
    
    const fileDropZone = document.getElementById('file-drop-zone');
    const localFileInput = document.getElementById('local-file-input');
    const browseBtn = document.getElementById('browse-btn');
    const localInfo = document.getElementById('local-info');

    const drivesContainer = document.getElementById('drives-container');
    const refreshDrivesBtn = document.getElementById('refresh-drives-btn');

    const flashBtn = document.getElementById('flash-btn');
    const progressContainer = document.getElementById('progress-container');
    const progressStatus = document.getElementById('progress-status');
    const progressPercent = document.getElementById('progress-percent');
    const progressBarFill = document.getElementById('progress-bar-fill');
    const progressSubtext = document.getElementById('progress-subtext');
    const successMessage = document.getElementById('success-message');
    const errorMessage = document.getElementById('error-message');

    // Init
    fetchDrives();

    // ----------------- TABS -----------------
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            if (state.isFlashing) return;

            tabBtns.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));

            btn.classList.add('active');
            const targetId = btn.getAttribute('data-target');
            document.getElementById(targetId).classList.add('active');
            
            state.activeTab = targetId;
            updateFlashButton();
        });
    });

    // ----------------- HF MODEL SELECT -----------------
    hfModelSelect.addEventListener('change', (e) => {
        if (!e.target.value) return;
        
        try {
            const data = JSON.parse(e.target.value);
            state.modelSource = { type: 'hf', data: data };
            hfInfo.textContent = `Will download ~${data.size} from HuggingFace`;
            hfInfo.style.display = 'block';
            updateFlashButton();
        } catch (err) {
            console.error('Failed to parse model data', err);
        }
    });

    // ----------------- LOCAL FILE UPLOAD -----------------
    browseBtn.addEventListener('click', () => localFileInput.click());

    localFileInput.addEventListener('change', (e) => {
        handleFiles(e.target.files);
    });

    fileDropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        fileDropZone.classList.add('drag-over');
    });

    fileDropZone.addEventListener('dragleave', () => {
        fileDropZone.classList.remove('drag-over');
    });

    fileDropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        fileDropZone.classList.remove('drag-over');
        handleFiles(e.dataTransfer.files);
    });

    function handleFiles(files) {
        if (files.length === 0) return;
        const file = files[0];
        
        if (!file.name.endsWith('.gguf')) {
            alert('Please select a .gguf file.');
            return;
        }

        const sizeInMB = (file.size / (1024 * 1024)).toFixed(2);
        let sizeStr = sizeInMB > 1024 ? (sizeInMB / 1024).toFixed(2) + ' GB' : sizeInMB + ' MB';

        state.modelSource = { type: 'local', data: file };
        localInfo.textContent = `Selected: ${file.name} (${sizeStr})`;
        localInfo.style.display = 'block';
        updateFlashButton();
    }

    // ----------------- USB DRIVES -----------------
    refreshDrivesBtn.addEventListener('click', fetchDrives);

    async function fetchDrives() {
        if (state.isFlashing) return;
        
        drivesContainer.innerHTML = '<p class="muted">Scanning for USB drives...</p>';
        state.selectedDrivePath = null;
        updateFlashButton();

        try {
            const response = await fetch('/api/drives');
            if (!response.ok) throw new Error('Network response was not ok');
            const data = await response.json();

            drivesContainer.innerHTML = '';
            
            if (!data.drives || data.drives.length === 0) {
                drivesContainer.innerHTML = '<p class="muted">No USB drives detected. Please plug in a USB drive.</p>';
                return;
            }

            data.drives.forEach((drive, index) => {
                const card = document.createElement('div');
                card.className = 'drive-card';
                card.dataset.path = drive.mount_point;

                card.innerHTML = `
                    <input type="radio" name="drive" class="drive-radio" id="drive-${index}" value="${drive.mount_point}">
                    <div class="drive-info">
                        <div class="drive-name">${drive.label || drive.device_name}</div>
                        <div class="drive-meta muted">${drive.mount_point} • ${drive.size_formatted || formatBytes(drive.size_bytes)}</div>
                    </div>
                `;

                card.addEventListener('click', () => {
                    if (state.isFlashing) return;
                    
                    document.querySelectorAll('.drive-card').forEach(c => c.classList.remove('selected'));
                    card.classList.add('selected');
                    card.querySelector('input').checked = true;
                    
                    state.selectedDrivePath = drive.mount_point;
                    updateFlashButton();
                });

                drivesContainer.appendChild(card);
            });

        } catch (error) {
            console.error('Error fetching drives:', error);
            drivesContainer.innerHTML = '<p class="muted" style="color: #dc2626;">Error fetching drives. Please try again.</p>';
        }
    }

    function formatBytes(bytes) {
        if (!bytes) return 'Unknown size';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    // ----------------- FLASH ACTION -----------------
    function updateFlashButton() {
        const hasModel = state.activeTab === 'hf-tab' 
            ? (state.modelSource && state.modelSource.type === 'hf')
            : (state.modelSource && state.modelSource.type === 'local');
            
        const hasDrive = !!state.selectedDrivePath;
        
        flashBtn.disabled = !(hasModel && hasDrive) || state.isFlashing;
    }

    flashBtn.addEventListener('click', async () => {
        if (flashBtn.disabled) return;
        
        state.isFlashing = true;
        updateFlashButton();
        
        // Disable UI
        document.querySelectorAll('input, select, button').forEach(el => {
            if (el.id !== 'flash-btn') el.disabled = true;
        });
        
        progressContainer.style.display = 'block';
        successMessage.style.display = 'none';
        errorMessage.style.display = 'none';
        
        try {
            let modelPath = '';
            
            // Step 1: Handle Model Source
            if (state.activeTab === 'hf-tab') {
                updateProgress(0, 'Downloading Model...', 'Starting download from HuggingFace');
                modelPath = await downloadHFModel(state.modelSource.data);
            } else {
                updateProgress(0, 'Preparing Local File...', 'Using local file');
                // For local files, if the backend accepts file paths or if it's a browser uploading,
                // we assume here we can just pass the name or it's handled differently.
                // Depending on actual implementation, you might need a FormData upload.
                // But per instructions: model_source string.
                modelPath = state.modelSource.data.name || state.modelSource.data.path; 
            }

            // Step 2: Flash Drive
            updateProgress(0, 'Flashing Drive...', 'Initializing flash process');
            await flashDrive(modelPath, state.selectedDrivePath);
            
            // Success
            progressContainer.style.display = 'none';
            successMessage.style.display = 'block';
            
        } catch (error) {
            progressContainer.style.display = 'none';
            errorMessage.textContent = `Error: ${error.message}`;
            errorMessage.style.display = 'block';
        } finally {
            state.isFlashing = false;
            document.querySelectorAll('input, select, button').forEach(el => el.disabled = false);
            updateFlashButton();
        }
    });

    async function downloadHFModel(hfData) {
        const res = await fetch('/api/download-hf', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repo: hfData.repo, filename: hfData.file })
        });
        
        if (!res.ok) throw new Error('Failed to start download');
        const data = await res.json();
        
        return await pollTask(data.task_id, '/api/download-progress/', (progress) => {
            updateProgress(progress.percent, 'Downloading Model...', progress.status || 'Downloading...');
        });
    }

    async function flashDrive(modelSource, targetPath) {
        const res = await fetch('/api/flash', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_path: targetPath, model_source: modelSource })
        });
        
        if (!res.ok) throw new Error('Failed to start flashing');
        const data = await res.json();
        
        return await pollTask(data.task_id, '/api/progress/', (progress) => {
            updateProgress(progress.percent, 'Flashing Drive...', progress.subtext || progress.status || 'Flashing...');
        });
    }

    function pollTask(taskId, endpointPrefix, onProgress) {
        return new Promise((resolve, reject) => {
            const interval = setInterval(async () => {
                try {
                    const res = await fetch(`${endpointPrefix}${taskId}`);
                    if (!res.ok) throw new Error('Failed to get progress');
                    const progress = await res.json();
                    
                    onProgress(progress);
                    
                    if (progress.completed) {
                        clearInterval(interval);
                        // download-hf returns local_path
                        resolve(progress.local_path || true);
                    } else if (progress.error) {
                        clearInterval(interval);
                        reject(new Error(progress.error));
                    }
                } catch (error) {
                    clearInterval(interval);
                    reject(error);
                }
            }, 1000);
        });
    }

    function updateProgress(percent, status, subtext) {
        progressPercent.textContent = `${percent}%`;
        progressBarFill.style.width = `${percent}%`;
        progressStatus.textContent = status;
        progressSubtext.textContent = subtext;
    }
});
