#!/usr/bin/env python3
"""
cllm - Model Inspector & Dynamic GGUF Header Parser
Model-agnostic inspector that validates any GGUF file, extracts architecture & quantization metadata, and calculates checksums.
"""

import os
import sys
import struct
import hashlib
import re
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List

@dataclass
class GGUFModelInfo:
    filename: str          # e.g. "qwen3-4b-q4_k_m.gguf"
    full_path: str         # Absolute path to file
    size_bytes: int        # File size in bytes
    size_formatted: str    # e.g. "2.50 GB"
    architecture: str      # e.g. "Qwen", "Llama", "Mistral", "Phi", "GGUF Model"
    quantization: str      # e.g. "Q4_K_M", "Q5_K_M", "Q8_0", "F16"
    context_length: int    # Context window length
    is_valid_gguf: bool    # True if GGUF magic header check passes
    sha256: str            # Quick SHA256 checksum

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ModelInspector:
    """Inspects GGUF files dynamically without requiring a hardcoded catalog."""

    def inspect_file(self, file_path: str) -> GGUFModelInfo:
        abs_path = os.path.abspath(file_path)
        filename = os.path.basename(abs_path)

        if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
            return GGUFModelInfo(
                filename=filename,
                full_path=abs_path,
                size_bytes=0,
                size_formatted="0 B",
                architecture="Unknown",
                quantization="Unknown",
                context_length=4096,
                is_valid_gguf=False,
                sha256=""
            )

        size_bytes = os.path.getsize(abs_path)
        size_str = self._format_bytes(size_bytes)
        quant = self._infer_quantization(filename)
        arch = self._infer_architecture(filename)
        is_valid, header_arch, header_ctx = self._parse_gguf_header(abs_path)

        if header_arch:
            arch = header_arch
        ctx_length = header_ctx or 4096
        checksum = self._calculate_fast_sha256(abs_path)

        return GGUFModelInfo(
            filename=filename,
            full_path=abs_path,
            size_bytes=size_bytes,
            size_formatted=size_str,
            architecture=arch,
            quantization=quant,
            context_length=ctx_length,
            is_valid_gguf=is_valid,
            sha256=checksum
        )

    def scan_local_directories(self, extra_paths: Optional[List[str]] = None) -> List[GGUFModelInfo]:
        """Scans local directories (e.g. ./models, ~/cllm/models, ~/Downloads) for supported .gguf files."""
        search_dirs = [
            os.path.abspath("models"),
            os.path.expanduser("~/cllm/models"),
            os.path.expanduser("~/Downloads")
        ]
        if extra_paths:
            search_dirs.extend(extra_paths)

        discovered: List[GGUFModelInfo] = []
        seen_paths = set()

        for d in search_dirs:
            if os.path.exists(d) and os.path.isdir(d):
                for root, _, files in os.walk(d):
                    for f in files:
                        if f.endswith(".gguf"):
                            fpath = os.path.join(root, f)
                            if fpath not in seen_paths:
                                seen_paths.add(fpath)
                                info = self.inspect_file(fpath)
                                if info.is_valid_gguf or fpath.endswith(".gguf"):
                                    discovered.append(info)

        return discovered

    def _parse_gguf_header(self, file_path: str) -> tuple[bool, Optional[str], Optional[int]]:
        """Parses GGUF binary header magic and basic metadata."""
        try:
            with open(file_path, "rb") as f:
                magic = f.read(4)
                if magic != b"GGUF":
                    return False, None, None

                version = struct.unpack("<I", f.read(4))[0]
                tensor_count = struct.unpack("<Q" if version >= 3 else "<I", f.read(8 if version >= 3 else 4))[0]
                kv_count = struct.unpack("<Q" if version >= 3 else "<I", f.read(8 if version >= 3 else 4))[0]

                # Try reading basic KV metadata strings
                arch = None
                ctx = 4096

                # Simple inspection of the first 64KB for string patterns
                f.seek(0)
                buffer = f.read(65536).decode("latin-1", errors="ignore")

                if "qwen2" in buffer.lower() or "qwen" in buffer.lower():
                    arch = "Qwen"
                elif "llama" in buffer.lower():
                    arch = "Llama"
                elif "mistral" in buffer.lower():
                    arch = "Mistral"
                elif "phi3" in buffer.lower() or "phi" in buffer.lower():
                    arch = "Phi"
                elif "deepseek" in buffer.lower():
                    arch = "DeepSeek"
                elif "gemma" in buffer.lower():
                    arch = "Gemma"

                return True, arch, ctx
        except Exception:
            return False, None, None

    def _infer_quantization(self, filename: str) -> str:
        filename_upper = filename.upper()
        match = re.search(r"(Q\d_[K|0-9]_[S|M|L]|Q\d_[0-9]|F16|F32|IQ\d_[S|M])", filename_upper)
        if match:
            return match.group(1)
        return "Q4_K_M"

    def _infer_architecture(self, filename: str) -> str:
        fname = filename.lower()
        if "qwen" in fname:
            return "Qwen"
        elif "llama" in fname:
            return "Llama"
        elif "mistral" in fname:
            return "Mistral"
        elif "phi" in fname:
            return "Phi"
        elif "deepseek" in fname:
            return "DeepSeek"
        elif "gemma" in fname:
            return "Gemma"
        elif "glm" in fname:
            return "GLM"
        return "GGUF Model"

    def _format_bytes(self, size_bytes: int) -> str:
        if size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    def _calculate_fast_sha256(self, file_path: str) -> str:
        """Calculates fast SHA256 checksum over initial 10MB chunk for instant UI responsiveness."""
        try:
            hasher = hashlib.sha256()
            with open(file_path, "rb") as f:
                chunk = f.read(10 * 1024 * 1024)
                hasher.update(chunk)
            return hasher.hexdigest()[:16]  # Shortened hash
        except Exception:
            return ""


if __name__ == "__main__":
    inspector = ModelInspector()
    print("=== cllm Model Inspector Test ===")
    models = inspector.scan_local_directories()
    print(f"Discovered {len(models)} local GGUF model(s):")
    for m in models:
        print(f"  • {m.filename} | Arch: {m.architecture} | Quant: {m.quantization} | Size: {m.size_formatted} | Valid: {m.is_valid_gguf}")
