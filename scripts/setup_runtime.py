#!/usr/bin/env python3
"""
cllm - Runtime Setup & Downloader Helper
Fetches and manages prebuilt llama.cpp binaries for Linux, macOS, and Windows.
"""

import os
import sys
import platform
import urllib.request
import tarfile
import zipfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.hardware import get_hardware_info, HardwareSpec

# Official llama.cpp release artifact URLs (or fallback mirror links)
LLAMA_CPP_RELEASES = {
    "linux-x86_64": "https://github.com/ggerganov/llama.cpp/releases/download/b3600/llama-b3600-bin-ubuntu-x64.zip",
    "windows-x86_64": "https://github.com/ggerganov/llama.cpp/releases/download/b3600/llama-b3600-bin-win-x64.zip",
    "macos-arm64": "https://github.com/ggerganov/llama.cpp/releases/download/b3600/llama-b3600-bin-macos-arm64.zip"
}

class RuntimeSetup:
    def __init__(self, root_dir: str = "."):
        self.root_dir = os.path.abspath(root_dir)
        self.runtime_dir = os.path.join(self.root_dir, "runtime")

    def check_runtime_status(self, hw: HardwareSpec) -> tuple[bool, str]:
        os_folder = f"{hw.os_name.lower()}-{hw.arch}"
        binary_name = "llama-cli.exe" if hw.os_name == "Windows" else "llama-cli"
        target_path = os.path.join(self.runtime_dir, os_folder, binary_name)

        if os.path.exists(target_path):
            return True, target_path

        # Check system path as fallback
        sys_bin = shutil.which("llama-cli") or shutil.which("main")
        if sys_bin:
            return True, f"{sys_bin} (System PATH)"

        return False, target_path

    def download_runtime(self, target_platform: str = None) -> bool:
        hw = get_hardware_info()
        plat_key = target_platform or f"{hw.os_name.lower()}-{hw.arch}"

        if plat_key not in LLAMA_CPP_RELEASES:
            print(f"[Error] Unsupported platform key: {plat_key}")
            return False

        url = LLAMA_CPP_RELEASES[plat_key]
        dest_dir = os.path.join(self.runtime_dir, plat_key)
        os.makedirs(dest_dir, exist_ok=True)

        zip_path = os.path.join(dest_dir, "llama_runtime.zip")
        print(f"Downloading llama.cpp prebuilt runtime for {plat_key}...")
        print(f"URL: {url}")

        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response, open(zip_path, 'wb') as out_file:
                shutil.copyfileobj(response, out_file)
            print("Download completed. Extracting runtime binaries...")

            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(dest_dir)

            os.remove(zip_path)

            # Make executables runnable
            for root, _, files in os.walk(dest_dir):
                for file in files:
                    if not file.endswith(".dll") and not file.endswith(".so") and not file.endswith(".dylib"):
                        fpath = os.path.join(root, file)
                        os.chmod(fpath, 0o755)

            print(f"✓ Runtime successfully installed in: {dest_dir}")
            return True
        except Exception as e:
            print(f"[Error] Runtime download failed: {e}")
            print("Note: You can also place pre-compiled 'llama-cli' binary directly in runtime/<os>-<arch>/ folder.")
            return False

if __name__ == "__main__":
    setup = RuntimeSetup(".")
    hw = get_hardware_info()
    installed, path = setup.check_runtime_status(hw)
    print("=== cllm Runtime Status ===")
    print(f"Platform Target: {hw.os_name.lower()}-{hw.arch}")
    print(f"Installed      : {installed}")
    print(f"Location       : {path}")
    if not installed and "--download" in sys.argv:
        setup.download_runtime()
