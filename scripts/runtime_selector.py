#!/usr/bin/env python3
"""
cllm - Hardware-Aware Runtime Selector Module
Resolves host-appropriate llama.cpp runtime binaries and calculates optimal flags (threads, GPU layers, context size).
"""

import os
import sys
import shutil
import subprocess
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

# Allow running directly as script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.hardware import HardwareSpec, GPUInfo, get_hardware_info
from scripts.model_manager import ModelManifest

@dataclass
class LaunchConfig:
    binary_path: str               # Absolute path to runtime binary
    backend: str                   # "CUDA", "Metal", "ROCm", "Vulkan", or "CPU"
    gpu_layers: int                # Number of offloaded GPU layers (-ngl)
    threads: int                   # CPU threads (-t)
    context_size: int              # Context length (-c)
    batch_size: int                # Batch size (-b)
    cmd_args: List[str]            # Complete list of command line arguments for llama-cli
    summary_text: str              # User readable recommendation summary


class RuntimeSelector:
    """Configures hardware-optimal inference parameters."""

    def __init__(self, root_dir: str = "."):
        self.root_dir = os.path.abspath(root_dir)
        self.runtime_dir = os.path.join(self.root_dir, "runtime")

    def resolve_binary(self, hardware: HardwareSpec) -> tuple[str, bool]:
        """
        Locates the appropriate llama-cli binary based on OS and architecture.
        Returns tuple of (binary_path, is_mock).
        """
        os_folder = f"{hardware.os_name.lower()}-{hardware.arch}"
        if hardware.os_name == "Windows":
            binary_name = "llama-cli.exe"
        else:
            binary_name = "llama-cli"

        # 1. Check portable runtime folder
        portable_path = os.path.join(self.runtime_dir, os_folder, binary_name)
        if os.path.exists(portable_path) and os.access(portable_path, os.X_OK):
            return portable_path, False

        # 2. Check general runtime folder
        general_path = os.path.join(self.runtime_dir, binary_name)
        if os.path.exists(general_path) and os.access(general_path, os.X_OK):
            return general_path, False

        # 3. Check system PATH
        system_path = shutil.which("llama-cli") or shutil.which("main") or shutil.which("llama-cpp-cli")
        if system_path:
            return system_path, False

        # 4. Fallback: Mock runtime wrapper (for testing/dry-run without binary)
        return "mock", True

    def calculate_launch_config(self, hardware: HardwareSpec, model: ModelManifest, custom_ctx: Optional[int] = None) -> LaunchConfig:
        binary_path, is_mock = self.resolve_binary(hardware)

        # 1. Determine CPU threads
        # Recommended: physical cores - 1 (min 1, max 8)
        threads = max(1, min(8, hardware.cpu_cores_physical))

        # 2. Determine GPU acceleration & offloaded layers
        gpu_layers = 0
        backend = "CPU"
        gpu = hardware.gpu

        if gpu:
            if gpu.cuda_available:
                backend = f"CUDA ({gpu.name})"
                gpu_layers = self._calculate_offload_layers(model, gpu.vram_free_mb)
            elif gpu.metal_available:
                backend = f"Metal ({gpu.name})"
                gpu_layers = 99  # Metal unified memory offloads full model
            elif gpu.vulkan_available:
                backend = f"Vulkan ({gpu.name})"
                gpu_layers = self._calculate_offload_layers(model, gpu.vram_free_mb)

        # 3. Determine Context Window
        model_max_ctx = model.context_length or 4096
        if custom_ctx:
            ctx_size = custom_ctx
        elif hardware.ram_total_mb < 8192:
            ctx_size = min(2048, model_max_ctx)
        elif hardware.ram_total_mb < 16384:
            ctx_size = min(4096, model_max_ctx)
        else:
            ctx_size = min(8192, model_max_ctx)

        batch_size = 512

        # 4. Assemble command line arguments
        cmd_args = [
            "-m", model.full_path,
            "-c", str(ctx_size),
            "-t", str(threads),
            "-ngl", str(gpu_layers),
            "-b", str(batch_size),
            "--color",
            "-i"  # Interactive chat mode
        ]

        summary = (
            f"Recommended Configuration:\n"
            f"  • Model       : {model.name} ({model.quantization})\n"
            f"  • Execution   : {backend}\n"
            f"  • GPU Layers  : {gpu_layers} layers offloaded\n"
            f"  • CPU Threads : {threads} threads\n"
            f"  • Context Size: {ctx_size} tokens\n"
            f"  • Binary Path : {'[Portable Runtime]' if not is_mock else '[Simulation Mode]'}"
        )

        return LaunchConfig(
            binary_path=binary_path,
            backend=backend,
            gpu_layers=gpu_layers,
            threads=threads,
            context_size=ctx_size,
            batch_size=batch_size,
            cmd_args=cmd_args,
            summary_text=summary
        )

    def _calculate_offload_layers(self, model: ModelManifest, vram_free_mb: int) -> int:
        if vram_free_mb <= 1024:
            return 0
        model_size_mb = model.size_bytes / (1024 * 1024)
        if model_size_mb == 0:
            return 35  # default estimate
        if vram_free_mb >= model_size_mb + 1024:
            return 99  # offload all layers
        else:
            ratio = vram_free_mb / (model_size_mb + 1024)
            return max(1, int(35 * ratio))


if __name__ == "__main__":
    hw = get_hardware_info()
    sample_model = ModelManifest(
        model_id="sample-qwen3-4b",
        name="Qwen 3 4B Q4_K_M",
        filename="qwen3-4b-q4.gguf",
        full_path="/models/qwen3-4b-q4.gguf",
        format="GGUF",
        quantization="Q4_K_M",
        size_bytes=2684354560,  # 2.5 GB
        size_formatted="2.50 GB",
        context_length=8192,
        recommended_vram_gb=3.5,
        runtime="llama.cpp",
        description="Sample Qwen 3 model"
    )

    selector = RuntimeSelector(".")
    config = selector.calculate_launch_config(hw, sample_model)
    print("=== cllm Runtime Selector Test ===")
    print(config.summary_text)
    print("Command args:", " ".join(config.cmd_args))
