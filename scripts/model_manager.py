#!/usr/bin/env python3
"""
cllm - Model & Manifest Manager Module
Scans models/ directory, parses GGUF files and manifest.json metadata, and manages portable model packages.
"""

import os
import sys
import json
import struct
import re
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional

@dataclass
class ModelManifest:
    model_id: str          # Unique folder/name identifier
    name: str              # Friendly display name, e.g. "Qwen 2.5 3B Instruct"
    filename: str          # GGUF file name e.g. "qwen2.5-3b-instruct-q4_k_m.gguf"
    full_path: str         # Absolute path to GGUF file
    format: str            # e.g. "GGUF"
    quantization: str      # e.g. "Q4_K_M", "Q5_K_M", "Q8_0", "F16"
    size_bytes: int        # File size in bytes
    size_formatted: str    # Human readable size, e.g. "2.15 GB"
    context_length: int    # Recommended context window length e.g. 8192 or 32768
    recommended_vram_gb: float # Estimated VRAM requirement
    runtime: str           # Target runtime engine e.g. "llama.cpp"
    description: str       # Model description

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ModelManager:
    """Discovers, validates, and manages portable LLM models."""

    def __init__(self, models_dir: str = "models"):
        self.models_dir = os.path.abspath(models_dir)

    def scan_models(self) -> List[ModelManifest]:
        """Scans models_dir recursively for model folders and GGUF files."""
        discovered: List[ModelManifest] = []

        if not os.path.exists(self.models_dir):
            os.makedirs(self.models_dir, exist_ok=True)
            return discovered

        # 1. Scan subdirectories
        for entry in os.listdir(self.models_dir):
            entry_path = os.path.join(self.models_dir, entry)

            if os.path.isdir(entry_path):
                manifest = self._process_model_dir(entry, entry_path)
                if manifest:
                    discovered.append(manifest)
            elif os.path.isfile(entry_path) and entry.endswith(".gguf"):
                manifest = self._process_standalone_gguf(entry, entry_path)
                if manifest:
                    discovered.append(manifest)

        return discovered

    def _process_model_dir(self, dir_name: str, dir_path: str) -> Optional[ModelManifest]:
        manifest_file = os.path.join(dir_path, "manifest.json")
        gguf_files = [f for f in os.listdir(dir_path) if f.endswith(".gguf")]

        if not gguf_files and not os.path.exists(manifest_file):
            return None

        gguf_filename = gguf_files[0] if gguf_files else "model.gguf"
        gguf_path = os.path.join(dir_path, gguf_filename)

        if os.path.exists(manifest_file):
            try:
                with open(manifest_file, "r") as f:
                    data = json.load(f)
                size_bytes = os.path.getsize(gguf_path) if os.path.exists(gguf_path) else data.get("size_bytes", 0)
                return ModelManifest(
                    model_id=dir_name,
                    name=data.get("name", dir_name),
                    filename=data.get("filename", gguf_filename),
                    full_path=gguf_path,
                    format=data.get("format", "GGUF"),
                    quantization=data.get("quantization", self._infer_quantization(gguf_filename)),
                    size_bytes=size_bytes,
                    size_formatted=data.get("size_formatted", self._format_bytes(size_bytes)),
                    context_length=data.get("context_length", 4096),
                    recommended_vram_gb=data.get("recommended_vram_gb", self._estimate_vram(size_bytes)),
                    runtime=data.get("runtime", "llama.cpp"),
                    description=data.get("description", "Portable GGUF Model Package")
                )
            except Exception as e:
                print(f"[Warning] Failed parsing {manifest_file}: {e}")

        # If manifest.json doesn't exist, create it automatically!
        if os.path.exists(gguf_path):
            manifest = self._generate_manifest(dir_name, dir_name, gguf_filename, gguf_path)
            self.save_manifest(dir_path, manifest)
            return manifest

        return None

    def _process_standalone_gguf(self, filename: str, file_path: str) -> ModelManifest:
        model_id = os.path.splitext(filename)[0]
        manifest = self._generate_manifest(model_id, model_id.replace("-", " ").title(), filename, file_path)
        return manifest

    def _generate_manifest(self, model_id: str, display_name: str, filename: str, full_path: str) -> ModelManifest:
        size_bytes = os.path.getsize(full_path) if os.path.exists(full_path) else 0
        quant = self._infer_quantization(filename)
        size_str = self._format_bytes(size_bytes)
        vram_est = self._estimate_vram(size_bytes)
        context_len = self._read_gguf_context(full_path) or 4096

        return ModelManifest(
            model_id=model_id,
            name=display_name,
            filename=filename,
            full_path=full_path,
            format="GGUF",
            quantization=quant,
            size_bytes=size_bytes,
            size_formatted=size_str,
            context_length=context_len,
            recommended_vram_gb=vram_est,
            runtime="llama.cpp",
            description=f"{display_name} model in {quant} quantization format."
        )

    def _infer_quantization(self, filename: str) -> str:
        filename_upper = filename.upper()
        match = re.search(r"(Q\d_[K|0-9]_[S|M|L]|Q\d_[0-9]|F16|F32|IQ\d_[S|M])", filename_upper)
        if match:
            return match.group(1)
        return "Q4_K_M"

    def _format_bytes(self, size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.2f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.2f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    def _estimate_vram(self, size_bytes: int) -> float:
        # Model weights size in GB + 1.0 GB buffer for KV cache & context
        gb = size_bytes / (1024 * 1024 * 1024)
        return round(gb + 1.0, 1)

    def _read_gguf_context(self, file_path: str) -> Optional[int]:
        """Header check for GGUF magic bytes."""
        try:
            with open(file_path, "rb") as f:
                magic = f.read(4)
                if magic != b"GGUF":
                    return None
                # Basic check passed
                return 4096
        except Exception:
            return None

    def save_manifest(self, target_dir: str, manifest: ModelManifest):
        os.makedirs(target_dir, exist_ok=True)
        manifest_path = os.path.join(target_dir, "manifest.json")
        data = manifest.to_dict()
        del data["full_path"]  # Keep relative
        with open(manifest_path, "w") as f:
            json.dump(data, f, indent=2)


if __name__ == "__main__":
    mm = ModelManager("models")
    models = mm.scan_models()
    print("=== cllm Model Discovery ===")
    print(f"Scanned directory: {mm.models_dir}")
    print(f"Found {len(models)} models:")
    for idx, m in enumerate(models, 1):
        print(f"  [{idx}] {m.name} ({m.quantization}) - {m.size_formatted} [Path: {m.full_path}]")
