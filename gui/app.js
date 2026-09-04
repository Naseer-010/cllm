// cllm Flasher - Model-Agnostic BalenaEtcher App Logic

document.addEventListener('DOMContentLoaded', () => {
    let selectedModel = null;
    let selectedDrive = null;
    let isFlashing = false;

    // Elements
    const dropZone = document.getElementById('drop-zone');
    const fileSelectBtn = document.getElementById('file-select-btn');
    const scanLocalBtn = document.getElementById('scan-local-btn');
    const hiddenFileInput = document.getElementById('hidden-file-input');
    const localModelsBox = document.getElementById('local-models-box');
    const localModelsList = document.getElementById('local-models-list');
    const closeScanBtn = document.getElementById('close-scan-btn');
    
    const selectedModelCard = document.getElementById('selected-model-card');
    const modelFilename = document.getElementById('model-filename');
    const specFormat = document.getElementById('spec-format');
    const specSize = document.getElementById('spec-size');
    const specArch = document.getElementById('spec-arch');
    const specQuant = document.getElementById('spec-quant');
    const changeModelBtn = document.getElementById('change-model-btn');

    const driveListContainer = document.getElementById('drive-list');
    const driveSelectedText = document.getElementById('drive-selected-text');
    const customDriveInput = document.getElementById('custom-drive-path');
    const refreshDrivesBtn = document.getElementById('refresh-drives-btn');

    const flashBtn = document.getElementById('flash-btn');
    const flashBtnText = document.getElementById('flash-btn-text');
    const progressBox = document.getElementById('progress-box');
    const progressStatusText = document.getElementById('progress-status-text');
    const progressPercentText = document.getElementById('progress-percent-text');
    const progressBarFill = document.getElementById('progress-bar-fill');
    const progressSubText = document.getElementById('progress-sub-text');
    const completionBox = document.getElementById('completion-box');

    // Initial USB drives scan
    fetchDrives();

    // 1. File Selection & Drag-and-Drop
    fileSelectBtn.addEventListener('click', () => hiddenFileInput.click());

    hiddenFileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            const file = e.target.files[0];
            inspectAndSetModel({
                filename: file.name,
                full_path: file.name, // Local file name
                size_bytes: file.size,
                size_formatted: formatBytes(file.size),
                architecture: inferArch(file.name),
                quantization: inferQuant(file.name)
            });
        }
    });

    // Drag and Drop Events
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('dragover');
    });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        if (e.dataTransfer.files.length > 0) {
            const file = e.dataTransfer.files[0];
            inspectAndSetModel({
                filename: file.name,
                full_path: file.name,
                size_bytes: file.size,
                size_formatted: formatBytes(file.size),
                architecture: inferArch(file.name),
                quantization: inferQuant(file.name)
            });
        }
    });

    // Local Models Scan
    scanLocalBtn.addEventListener('click', () => {
        localModelsBox.classList.remove('hidden');
        localModelsList.innerHTML = '<div style="color:#94A3B8; font-size:0.8rem;">Scanning local directories (~/cllm/models, ./models, ~/Downloads)...</div>';
        
        fetch('/api/scan-local')
            .then(res => res.json())
            .then(data => {
                const models = data.models || [];
                localModelsList.innerHTML = '';
                if (models.length === 0) {
                    localModelsList.innerHTML = '<div style="color:#94A3B8; font-size:0.8rem;">No .gguf files found in local folders.</div>';
                    return;
                }
                models.forEach(m => {
                    const item = document.createElement('div');
                    item.className = 'local-model-item';
                    item.innerHTML = `<span>📄 ${m.filename}</span> <span style="font-family:monospace; color:#00E5FF;">${m.size_formatted}</span>`;
                    item.addEventListener('click', () => {
                        inspectAndSetModel(m);
                        localModelsBox.classList.add('hidden');
                    });
                    localModelsList.appendChild(item);
                });
            })
            .catch(err => console.error(err));
    });

    closeScanBtn.addEventListener('click', () => localModelsBox.classList.add('hidden'));

    changeModelBtn.addEventListener('click', () => {
        selectedModel = null;
        selectedModelCard.classList.add('hidden');
        dropZone.classList.remove('hidden');
        updateFlashButtonState();
    });

    // Drive Selection
    refreshDrivesBtn.addEventListener('click', fetchDrives);

    customDriveInput.addEventListener('input', () => {
        const val = customDriveInput.value.trim();
        if (val) {
            selectedDrive = { mount_point: val, label: `Target Directory (${val})` };
            driveSelectedText.innerText = `Selected: ${val}`;
            document.querySelectorAll('.drive-card').forEach(c => c.classList.remove('selected'));
            updateFlashButtonState();
        }
    });

    // Flashing Action
    flashBtn.addEventListener('click', () => {
        if (!selectedModel || !selectedDrive || isFlashing) return;
        startFlashingProcess();
    });

    function inspectAndSetModel(info) {
        selectedModel = info;
        dropZone.classList.add('hidden');
        selectedModelCard.classList.remove('hidden');

        modelFilename.innerText = info.filename;
        specFormat.innerText = "GGUF";
        specSize.innerText = info.size_formatted || "2.5 GB";
        specArch.innerText = info.architecture || "GGUF Model";
        specQuant.innerText = info.quantization || "Q4_K_M";

        updateFlashButtonState();
    }

    function fetchDrives() {
        fetch('/api/drives')
            .then(res => res.json())
            .then(data => renderDrives(data.drives || []))
            .catch(err => console.error('Failed fetching drives:', err));
    }

    function renderDrives(drives) {
        driveListContainer.innerHTML = '';
        if (drives.length === 0) {
            driveListContainer.innerHTML = `
                <div class="no-drives">
                    No external USB drives detected.<br>Plug in a drive or enter mount path below.
                </div>
            `;
            return;
        }

        drives.forEach((d, idx) => {
            const card = document.createElement('div');
            card.className = 'drive-card';
            card.innerHTML = `
                <div class="drive-title">💾 ${d.label}</div>
                <div class="drive-meta">
                    <span>${d.mount_point}</span> • 
                    <span>${d.size_formatted}</span>
                </div>
            `;
            card.addEventListener('click', () => {
                document.querySelectorAll('.drive-card').forEach(c => c.classList.remove('selected'));
                card.classList.add('selected');
                selectedDrive = d;
                driveSelectedText.innerText = `Selected: ${d.label}`;
                customDriveInput.value = '';
                updateFlashButtonState();
            });
            driveListContainer.appendChild(card);
            if (idx === 0) card.click();
        });
    }

    function updateFlashButtonState() {
        if (selectedModel && selectedDrive && !isFlashing) {
            flashBtn.classList.remove('disabled');
            flashBtn.disabled = false;
        } else {
            flashBtn.classList.add('disabled');
            flashBtn.disabled = true;
        }
    }

    function startFlashingProcess() {
        isFlashing = true;
        flashBtn.classList.add('disabled');
        flashBtn.disabled = true;
        flashBtnText.innerText = 'FLASHING IN PROGRESS...';
        progressBox.classList.remove('hidden');
        completionBox.classList.add('hidden');

        fetch('/api/flash', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target_path: selectedDrive.mount_point,
                model_source: selectedModel.full_path || selectedModel.filename
            })
        })
        .then(res => res.json())
        .then(data => {
            if (data.task_id) pollProgress(data.task_id);
        })
        .catch(err => {
            console.error(err);
            isFlashing = false;
            updateFlashButtonState();
        });
    }

    function pollProgress(taskId) {
        const interval = setInterval(() => {
            fetch(`/api/progress/${taskId}`)
                .then(res => res.json())
                .then(p => {
                    progressPercentText.innerText = `${p.percent}%`;
                    progressBarFill.style.width = `${p.percent}%`;
                    progressStatusText.innerText = p.status || 'Flashing...';
                    progressSubText.innerText = p.subtext || '';

                    if (p.percent >= 100 || p.completed) {
                        clearInterval(interval);
                        isFlashing = false;
                        progressBox.classList.add('hidden');
                        completionBox.classList.remove('hidden');
                        flashBtnText.innerText = 'FLASH COMPLETED!';
                    }
                })
                .catch(err => console.error(err));
        }, 500);
    }

    function formatBytes(bytes) {
        if (!bytes) return "2.5 GB";
        if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + " MB";
        return (bytes / (1024 * 1024 * 1024)).toFixed(2) + " GB";
    }

    function inferArch(filename) {
        const f = filename.lower ? filename.lower() : filename.toLowerCase();
        if (f.includes('qwen')) return 'Qwen';
        if (f.includes('llama')) return 'Llama';
        if (f.includes('mistral')) return 'Mistral';
        if (f.includes('phi')) return 'Phi';
        if (f.includes('deepseek')) return 'DeepSeek';
        if (f.includes('gemma')) return 'Gemma';
        return 'GGUF Model';
    }

    function inferQuant(filename) {
        const match = filename.match(/(Q\d_[K|0-9]_[S|M|L]|Q\d_[0-9]|F16|IQ\d_[S|M])/i);
        return match ? match[0].toUpperCase() : 'Q4_K_M';
    }
});
