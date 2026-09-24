#!/usr/bin/env python3
"""
cllm - Model-Agnostic Flasher GUI Server Engine
API server for GGUF file inspection, USB drive auto-detection, HuggingFace model downloads,
and portable drive flashing.
"""

import os
import sys
import json
import time
import uuid
import threading
import urllib.parse
import urllib.request
import webbrowser
import shutil
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import Dict, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.drive_detector import USBDriveDetector
from scripts.model_inspector import ModelInspector
from scripts.flasher import DriveFlasher

PROGRESS_STORE: Dict[str, Dict[str, Any]] = {}
DOWNLOAD_STORE: Dict[str, Dict[str, Any]] = {}

# Directory to cache downloaded models
MODELS_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
os.makedirs(MODELS_CACHE_DIR, exist_ok=True)


class ModelAgnosticFlasherHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        gui_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui")
        super().__init__(*args, directory=gui_dir, **kwargs)

    def log_message(self, format, *args):
        """Suppress default HTTP request logging to keep console clean."""
        pass

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/scan-local":
            inspector = ModelInspector()
            models = [m.to_dict() for m in inspector.scan_local_directories()]
            self.send_json_response({"models": models})

        elif self.path.startswith("/api/inspect"):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            file_path = query.get("file", [""])[0]
            inspector = ModelInspector()
            info = inspector.inspect_file(file_path)
            self.send_json_response(info.to_dict())

        elif self.path == "/api/drives":
            detector = USBDriveDetector()
            drives = [d.to_dict() for d in detector.scan_usb_only()]
            self.send_json_response({"drives": drives})

        elif self.path.startswith("/api/progress/"):
            task_id = self.path.split("/")[-1]
            progress = PROGRESS_STORE.get(task_id, {"percent": 0, "status": "Initializing...", "completed": False})
            self.send_json_response(progress)

        elif self.path.startswith("/api/download-progress/"):
            task_id = self.path.split("/")[-1]
            progress = DOWNLOAD_STORE.get(task_id, {"percent": 0, "status": "Starting...", "completed": False})
            self.send_json_response(progress)

        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/flash":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body)
                target_path = data.get("target_path")
                model_source = data.get("model_source")

                task_id = str(uuid.uuid4())
                PROGRESS_STORE[task_id] = {
                    "percent": 5,
                    "status": "Initializing USB layout structure...",
                    "subtext": f"Target: {target_path}",
                    "completed": False
                }

                thread = threading.Thread(
                    target=self._async_flash_worker,
                    args=(task_id, target_path, model_source),
                    daemon=True
                )
                thread.start()

                self.send_json_response({"status": "started", "task_id": task_id})
            except Exception as e:
                self.send_json_response({"error": str(e)}, status=400)

        elif self.path == "/api/download-hf":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body)
                repo = data.get("repo")
                filename = data.get("filename")

                if not repo or not filename:
                    self.send_json_response({"error": "Missing repo or filename"}, status=400)
                    return

                task_id = str(uuid.uuid4())
                DOWNLOAD_STORE[task_id] = {
                    "percent": 0,
                    "status": "Starting download...",
                    "completed": False,
                    "local_path": ""
                }

                thread = threading.Thread(
                    target=self._async_download_hf,
                    args=(task_id, repo, filename),
                    daemon=True
                )
                thread.start()

                self.send_json_response({"status": "started", "task_id": task_id})
            except Exception as e:
                self.send_json_response({"error": str(e)}, status=400)

    def send_json_response(self, data: Dict[str, Any], status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def _async_download_hf(self, task_id: str, repo: str, filename: str):
        """Download a GGUF model from HuggingFace Hub."""
        local_path = os.path.join(MODELS_CACHE_DIR, filename)

        # Check if already downloaded
        if os.path.exists(local_path) and os.path.getsize(local_path) > 1024 * 1024:
            DOWNLOAD_STORE[task_id].update({
                "percent": 100,
                "status": "Model already cached locally",
                "completed": True,
                "local_path": local_path
            })
            return

        # Construct HuggingFace download URL
        url = f"https://huggingface.co/{repo}/resolve/main/{filename}"

        try:
            DOWNLOAD_STORE[task_id].update({
                "percent": 2,
                "status": f"Connecting to HuggingFace..."
            })

            req = urllib.request.Request(url, headers={"User-Agent": "cllm-flasher/1.0"})
            response = urllib.request.urlopen(req)
            total_size = int(response.headers.get("Content-Length", 0))

            downloaded = 0
            chunk_size = 1024 * 1024  # 1MB chunks

            with open(local_path + ".part", "wb") as f:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)

                    if total_size > 0:
                        percent = min(int((downloaded / total_size) * 100), 99)
                    else:
                        percent = min(int(downloaded / (1024 * 1024)), 99)

                    size_mb = downloaded / (1024 * 1024)
                    total_mb = total_size / (1024 * 1024) if total_size > 0 else 0

                    DOWNLOAD_STORE[task_id].update({
                        "percent": percent,
                        "status": f"Downloading... {size_mb:.0f} / {total_mb:.0f} MB" if total_mb else f"Downloading... {size_mb:.0f} MB"
                    })

            # Rename .part to final file
            shutil.move(local_path + ".part", local_path)

            DOWNLOAD_STORE[task_id].update({
                "percent": 100,
                "status": "Download complete",
                "completed": True,
                "local_path": local_path
            })

        except Exception as e:
            # Clean up partial download
            part_file = local_path + ".part"
            if os.path.exists(part_file):
                os.remove(part_file)

            DOWNLOAD_STORE[task_id].update({
                "percent": 0,
                "status": f"Download failed: {str(e)}",
                "completed": False,
                "error": str(e)
            })

    def _async_flash_worker(self, task_id: str, target_path: str, model_source: str):
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        flasher = DriveFlasher(root_dir)

        # Step 1: Create layout
        time.sleep(0.4)
        PROGRESS_STORE[task_id].update({"percent": 25, "status": "Creating directory structure..."})

        # Step 2: Copy Runtimes & Scripts
        time.sleep(0.4)
        PROGRESS_STORE[task_id].update({"percent": 50, "status": "Packaging runtime engines..."})

        # Step 3: Copy Model & Write Manifest
        time.sleep(0.4)
        fname = os.path.basename(model_source) if model_source else "model.gguf"
        PROGRESS_STORE[task_id].update({"percent": 75, "status": f"Copying model '{fname}'..."})

        flasher.flash_drive(target_path, model_source)

        # Step 4: Verify & Complete
        time.sleep(0.4)
        PROGRESS_STORE[task_id].update({
            "percent": 100,
            "status": "Flash completed successfully!",
            "subtext": "Root launcher ./cllm ready on USB drive",
            "completed": True
        })


def run_flasher_gui(port: int = 7860, open_browser: bool = True):
    server_address = ("127.0.0.1", port)
    httpd = HTTPServer(server_address, ModelAgnosticFlasherHandler)

    url = f"http://127.0.0.1:{port}"
    print(f"\n  cllm Flasher GUI running at {url}")
    print(f"  Press Ctrl+C to stop.\n")

    if open_browser:
        threading.Thread(target=lambda: (time.sleep(0.5), webbrowser.open(url)), daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping cllm Flasher server.")


if __name__ == "__main__":
    port = 7860
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])
    run_flasher_gui(port)
