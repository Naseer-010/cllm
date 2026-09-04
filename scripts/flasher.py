#!/usr/bin/env python3
"""
cllm - Portable Drive Flasher & Package Creator (Model-Agnostic Engine)
Initializes and builds self-contained portable 'cllm' USB drives from ANY input GGUF model file.
"""

import os
import sys
import shutil
import json
import hashlib
import urllib.request
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.model_inspector import ModelInspector, GGUFModelInfo

class DriveFlasher:
    """Model-agnostic USB flasher and package creator for cllm."""

    def __init__(self, root_source_dir: str = "."):
        self.root_source_dir = os.path.abspath(root_source_dir)
        self.inspector = ModelInspector()

    def flash_drive(
        self,
        target_path: str,
        model_source: Optional[str] = None,
        include_runtimes: bool = True
    ) -> bool:
        target_dir = os.path.abspath(target_path)
        print("╭──────────────────────────────────────────────────────────╮")
        print("│            cllm BalenaEtcher-Style Drive Flasher         │")
        print("╰──────────────────────────────────────────────────────────╯")
        print(f"Target Drive Mount: {target_dir}")

        if not os.path.exists(target_dir):
            try:
                os.makedirs(target_dir, exist_ok=True)
            except Exception as e:
                print(f"[Error] Failed creating target directory: {e}")
                return False

        # 1. Create portable directory structure
        dirs_to_create = ["bin", "config", "models", "runtime", "scripts"]
        for d in dirs_to_create:
            path = os.path.join(target_dir, d)
            os.makedirs(path, exist_ok=True)

        # 2. Copy core python engine scripts
        scripts_source = os.path.join(self.root_source_dir, "scripts")
        if os.path.exists(scripts_source):
            for item in os.listdir(scripts_source):
                if item.endswith(".py"):
                    src_file = os.path.join(scripts_source, item)
                    dst_file = os.path.join(target_dir, "scripts", item)
                    shutil.copy2(src_file, dst_file)

        # 3. Copy CLI launcher executable
        bin_source = os.path.join(self.root_source_dir, "bin", "cllm")
        bin_target = os.path.join(target_dir, "bin", "cllm")
        if os.path.exists(bin_source):
            shutil.copy2(bin_source, bin_target)
            os.chmod(bin_target, 0o755)

        # 4. Create root USB launcher script (./cllm)
        root_launcher = os.path.join(target_dir, "cllm")
        with open(root_launcher, "w") as f:
            f.write("#!/bin/bash\nexec python3 ./bin/cllm \"$@\"\n")
        os.chmod(root_launcher, 0o755)

        # 5. Copy/Package Runtimes if present
        runtime_source = os.path.join(self.root_source_dir, "runtime")
        if os.path.exists(runtime_source):
            for item in os.listdir(runtime_source):
                s = os.path.join(runtime_source, item)
                d = os.path.join(target_dir, "runtime", item)
                if os.path.isdir(s):
                    if os.path.exists(d):
                        shutil.rmtree(d)
                    shutil.copytree(s, d)

        # 6. Copy / Download Input GGUF Model
        model_info = GGUFModelInfo(
            filename="model.gguf",
            full_path="",
            size_bytes=0,
            size_formatted="0 B",
            architecture="Portable Model",
            quantization="Q4_K_M",
            context_length=4096,
            is_valid_gguf=True,
            sha256=""
        )

        if model_source:
            if model_source.startswith("http://") or model_source.startswith("https://"):
                filename = model_source.split("/")[-1] or "model.gguf"
                gguf_target_path = os.path.join(target_dir, "models", filename)
                print(f"Downloading model from URL: {model_source}...")
                try:
                    req = urllib.request.Request(model_source, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req) as response, open(gguf_target_path, 'wb') as out_file:
                        shutil.copyfileobj(response, out_file)
                    model_info = self.inspector.inspect_file(gguf_target_path)
                except Exception as e:
                    print(f"[Error] Failed to download model: {e}")
            elif os.path.exists(model_source):
                filename = os.path.basename(model_source)
                gguf_target_path = os.path.join(target_dir, "models", filename)
                print(f"Copying model '{filename}' to portable drive...")
                shutil.copy2(model_source, gguf_target_path)
                model_info = self.inspector.inspect_file(gguf_target_path)
            else:
                print(f"[Warning] Model file '{model_source}' not found. Initialized drive shell.")

        # 7. Write standardized drive manifest.json
        manifest_data = {
            "format": "cllm-drive",
            "version": 1,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model": {
                "filename": model_info.filename,
                "architecture": model_info.architecture,
                "quantization": model_info.quantization,
                "size_bytes": model_info.size_bytes,
                "size_formatted": model_info.size_formatted,
                "sha256": model_info.sha256
            },
            "runtime": {
                "engine": "llama.cpp"
            }
        }

        manifest_path = os.path.join(target_dir, "config", "manifest.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest_data, f, indent=2)

        # 8. Write USB README.md
        readme_target = os.path.join(target_dir, "README.md")
        with open(readme_target, "w") as f:
            f.write(f"# cllm Portable LLM Drive\n\nFlashed Model: `{model_info.filename}` ({model_info.architecture} {model_info.quantization})\n\nTo launch on any computer:\n```bash\n./cllm\n```\n")

        print("\n✨ Flashing Complete! Your portable cllm drive is ready.")
        return True


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = sys.argv[1]
        model_src = sys.argv[2] if len(sys.argv) > 2 else None
        flasher = DriveFlasher(".")
        flasher.flash_drive(target, model_src)
    else:
        print("Usage: python3 -m scripts.flasher <target_directory> [model_file_or_url]")
