# `cllm` — Portable Pendrive LLM System & Flasher

`cllm` is a zero-installation, model-agnostic portable LLM ecosystem designed to run local intelligence directly off portable storage (USB 3.2 NVMe SSD / Flash Drive) or local directories across **Linux**, **macOS**, and **Windows**.

It provides a **BalenaEtcher-style Desktop GUI Flasher** (`cllm-flasher`) to create self-contained portable AI drives, paired with a **Hardware-Aware CLI Launcher** (`cllm`) that auto-tunes inference parameters (GPU layers, threads, context length) to match whichever host machine the drive is plugged into.

---

## 🏗️ System Architecture & Workflow

```
                  ┌──────────────────────────────────────────────┐
                  │              INPUT GGUF MODEL                │
                  │   (Selected via File Picker / Drag & Drop)   │
                  └──────────────────────┬───────────────────────┘
                                         │
                                         ▼
                  ┌──────────────────────────────────────────────┐
                  │                 cllm Flasher                 │
                  │        (BalenaEtcher-Style Desktop GUI)      │
                  └──────────────────────┬───────────────────────┘
                                         │ Flashes Target USB
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                "cllm Drive"                                     │
│                                                                                 │
│  /models/                    Model Weights (.gguf)                              │
│  /runtime/                   Cross-platform Engines (Linux/macOS/Windows)       │
│  /bin/                       Executable Launcher Entrypoint (cllm)              │
│  /config/                    Drive Manifest (manifest.json) & Hardware Cache    │
│  /scripts/                   Python Core Engine Package                         │
│  ./cllm                      Root Shell Executable                              │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │ Plug USB into ANY Computer
                                         ▼
                        ┌─────────────────────────────────┐
                        │          Host Computer          │
                        │                                 │
                        │   CPU, System RAM, GPU, VRAM    │
                        └────────────────┬────────────────┘
                                         │ Auto-Detects Specs & Auto-Tunes
                                         ▼
                        ┌─────────────────────────────────┐
                        │      Hardware-Aware Engine      │
                        │  • Offloads GPU Layers (-ngl)   │
                        │  • Sets CPU Threads (-t)        │
                        │  • Adjusts Context Window (-c)  │
                        └────────────────┬────────────────┘
                                         │
                                         ▼
                        ┌─────────────────────────────────┐
                        │     Interactive Terminal Chat   │
                        └─────────────────────────────────┘
```

---

## 📁 Portable Directory Layout

```
cllm/
├── cllm                         # Root executable launcher wrapper script (./cllm)
├── cllm-flasher                 # BalenaEtcher GUI launcher executable (./cllm-flasher)
├── setup.sh                     # System setup & verification helper
│
├── bin/
│   └── cllm                     # CLI entrypoint executable launcher
├── config/
│   └── device.json              # Cached host hardware spec
├── gui/                         # BalenaEtcher-style Desktop GUI frontend
│   ├── index.html               # Dark glassmorphic HTML layout
│   ├── styles.css               # Modern CSS design system
│   └── app.js                   # Client-side UI & polling logic
├── models/                      # Portable GGUF weight store & metadata
│   ├── llama3.2-3b-instruct/    # Sample model package
│   │   └── manifest.json
│   ├── qwen2.5-coder-3b-instruct/
│   │   └── manifest.json
│   └── README.md
├── runtime/                     # Cross-platform precompiled llama.cpp engines
│   ├── linux-x86_64/
│   ├── windows-x86_64/
│   ├── macos-arm64/
│   └── README.md
├── scripts/                     # Core Python Engine Package
│   ├── __init__.py
│   ├── hardware.py              # Host hardware profiler (CPU, RAM, GPU, VRAM)
│   ├── model_manager.py         # Directory model scanner & manifest parser
│   ├── model_inspector.py       # Dynamic GGUF header parser & SHA256 calculator
│   ├── drive_detector.py        # USB removable storage auto-detector
│   ├── runtime_selector.py      # Hardware-aware flag calculator (threads, GPU layers, ctx)
│   ├── setup_runtime.py         # Auto-fetcher for precompiled llama.cpp releases
│   ├── flasher.py               # Drive packaging & flashing engine
│   ├── flasher_gui.py           # Web API server for BalenaEtcher GUI
│   └── interactive.py           # Rich ANSI terminal dashboard UI & chat loop
└── README.md                    # System documentation
```

---

## 🔄 Detailed Workflows

### Workflow 1: Creating a Portable USB LLM Drive (`cllm-flasher`)

`cllm Flasher` is a **model-agnostic drive creator** designed like BalenaEtcher for portable LLMs. It does not maintain a hardcoded marketplace catalog — you can feed it **ANY** `.gguf` file (e.g. Qwen, Llama, DeepSeek, Phi, Mistral, Gemma, GLM, etc.).

#### Step 1: Launch the Flasher GUI
```bash
./cllm-flasher
```
*or*
```bash
./cllm gui
```
This opens `http://127.0.0.1:7860` in your default browser.

#### Step 2: Select any GGUF Model
- Click **`📁 Select GGUF File`** or drag and drop any `.gguf` file into the UI.
- Or click **`🔍 Scan Local Models`** to discover existing `.gguf` files in `~/cllm/models`, `./models`, or `~/Downloads`.
- The **GGUF Inspector** (`scripts/model_inspector.py`) parses the binary header and displays:
  ```
  MODEL
  ✓ qwen3-4b-q4_k_m.gguf

  Format:       GGUF
  Size:         2.5 GB
  Architecture: Qwen
  Quantization: Q4_K_M
  ```

#### Step 3: Select Target USB Drive
- Connected USB drives (USB SSDs, Flash Drives) are auto-detected via `scripts/drive_detector.py` showing drive capacity and mount path (e.g. `/media/user/CLLM` or `/Volumes/USB`).

#### Step 4: Click `FLASH CLLM DRIVE`
- The flasher copies the `.gguf` file to `USB/models/`.
- Packages cross-platform runtimes to `USB/runtime/`.
- Generates standardized drive manifest `USB/config/manifest.json`.
- Writes root `./cllm` executable script.

---

### Workflow 2: Running LLMs on Any Host Computer (`./cllm`)

When you plug your portable drive into any computer (Linux, macOS, or Windows):

```bash
./cllm
```

#### What happens behind the scenes:
1. **Hardware Profiling (`scripts/hardware.py`)**:
   - Detects OS platform (`Linux`, `Darwin`, `Windows`) and Architecture (`x86_64`, `arm64`).
   - Counts physical CPU cores and logical threads.
   - Measures total and available System RAM.
   - Detects GPU acceleration (NVIDIA CUDA, Apple Metal, AMD ROCm/Vulkan, Intel Arc) and available VRAM.

2. **Model & Manifest Scanning (`scripts/model_manager.py`)**:
   - Scans `/models/` for `.gguf` weights and directory manifests.

3. **Hardware-Aware Auto-Tuning (`scripts/runtime_selector.py`)**:
   - **GPU Offloading (`-ngl`)**: Offloads 100% of layers (`-ngl 99`) if VRAM >= model size; calculates proportional offload layers if VRAM is constrained.
   - **CPU Threads (`-t`)**: Auto-selects optimal thread count (`min(8, physical_cores)`).
   - **Context Window (`-c`)**: Adjusts context size safely based on available memory.

4. **Interactive Dashboard & Session (`scripts/interactive.py`)**:
   - Displays hardware metrics summary.
   - Presents an interactive model picker menu.
   - Launches interactive chat loop with real-time text streaming.

---

### Workflow 3: Command-Line Drive Flashing (`./cllm flash`)

For headless or CLI-driven drive flashing:

```bash
# Flash local GGUF model file to USB drive
./bin/cllm flash /media/user/USB_SSD /path/to/my_model.gguf

# Flash directly from a HuggingFace GGUF URL
./bin/cllm flash /media/user/USB_SSD "https://huggingface.co/Qwen/Qwen2.5-Coder-3B-Instruct-GGUF/resolve/main/qwen2.5-coder-3b-instruct-q4_k_m.gguf"
```

---

## 💬 Slash Commands (Interactive Mode)

During an active `./cllm` chat session, type slash commands to inspect system state:

| Command | Description |
|---|---|
| `/help` | Show list of available slash commands |
| `/models` | List all discovered models on portable drive |
| `/info` | Show active model metadata, format, & quantization specs |
| `/system` | Display host CPU, RAM, GPU, VRAM, and calculated execution parameters |
| `/clear` | Clear terminal screen |
| `/exit` | Exit `cllm` interactive chat |

---

## ⚙️ Core Engine Modules Reference

| Module | Responsibility |
|---|---|
| `scripts/hardware.py` | Detects host CPU cores, physical threads, RAM, NVIDIA/AMD/Apple/Intel GPUs, and VRAM. |
| `scripts/model_inspector.py` | Dynamic GGUF binary header parser (magic `GGUF`, architecture, quantization, sha256). |
| `scripts/drive_detector.py` | Auto-detects connected USB removable storage drives (`lsblk`, `/media`, `/Volumes`, `PowerShell`). |
| `scripts/model_manager.py` | Scans `models/` directory, parses manifests, and auto-generates missing metadata. |
| `scripts/runtime_selector.py` | Resolves cross-platform binaries and auto-tunes `-ngl`, `-t`, `-c`, `-b` flags. |
| `scripts/setup_runtime.py` | Automatically fetches official precompiled `llama.cpp` release binaries. |
| `scripts/flasher.py` | CLI drive bundler, directory structure replicator, and manifest generator. |
| `scripts/flasher_gui.py` | Lightweight Web API server (`http.server`) powering the BalenaEtcher GUI. |
| `scripts/interactive.py` | Rich ANSI terminal dashboard UI, animated model loader, and chat prompt engine. |

---

## 🧪 Testing & Verification Guide

### Test 1: Immediate Dry-Run / Simulation Mode
Test the complete launcher UI, hardware detection, model selection, and slash commands without downloading any 4GB model weights or GPU binaries:
```bash
./cllm --dry-run
```

### Test 2: Verify Hardware Auto-Discovery
```bash
python3 scripts/hardware.py
```

### Test 3: Verify Dynamic GGUF Model Inspector
```bash
python3 scripts/model_inspector.py
```

### Test 4: Verify USB Drive Auto-Detector
```bash
python3 scripts/drive_detector.py
```

### Test 5: Verify Flasher GUI Backend Server
```bash
python3 scripts/flasher_gui.py 7860
```

---

## 📄 Manifest & Configuration Schema (`config/manifest.json`)

Standardized drive manifest specification written to every flashed `cllm` portable drive:

```json
{
  "format": "cllm-drive",
  "version": 1,
  "created_at": "2026-09-04T02:40:00Z",
  "model": {
    "filename": "qwen3-4b-q4_k_m.gguf",
    "architecture": "Qwen",
    "quantization": "Q4_K_M",
    "size_bytes": 2684354560,
    "size_formatted": "2.50 GB",
    "sha256": "e3b0c44298fc1c14"
  },
  "runtime": {
    "engine": "llama.cpp"
  }
}
```
