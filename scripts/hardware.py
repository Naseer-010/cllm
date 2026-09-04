#!/usr/bin/env python3
"""
cllm - Hardware Detection Module
Detects Host CPU, Core Count, RAM, GPU vendor/model, and VRAM across Linux, macOS, and Windows.
"""

import os
import sys
import platform
import subprocess
import json
import re
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any

@dataclass
class GPUInfo:
    vendor: str            # "NVIDIA", "AMD", "Apple", "Intel", or "Unknown"
    name: str              # e.g. "NVIDIA GeForce RTX 4060"
    vram_total_mb: int     # e.g. 8192
    vram_free_mb: int      # e.g. 7600
    cuda_available: bool = False
    metal_available: bool = False
    vulkan_available: bool = False

@dataclass
class HardwareSpec:
    os_name: str           # "Linux", "Darwin", "Windows"
    arch: str              # "x86_64", "arm64", "aarch64"
    cpu_model: str         # "AMD Ryzen 7 7840HS"
    cpu_cores_logical: int
    cpu_cores_physical: int
    ram_total_mb: int
    ram_free_mb: int
    gpu: Optional[GPUInfo] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


class HardwareDetector:
    """System hardware auto-discovery engine."""

    def __init__(self):
        self.os_name = platform.system()
        self.arch = platform.machine().lower()
        if self.arch in ["amd64", "x86-64"]:
            self.arch = "x86_64"
        elif self.arch in ["arm64", "aarch64"]:
            self.arch = "arm64"

    def detect(self) -> HardwareSpec:
        cpu_model, physical_cores, logical_cores = self._detect_cpu()
        ram_total, ram_free = self._detect_ram()
        gpu_info = self._detect_gpu(ram_total)

        spec = HardwareSpec(
            os_name=self.os_name,
            arch=self.arch,
            cpu_model=cpu_model,
            cpu_cores_logical=logical_cores,
            cpu_cores_physical=physical_cores,
            ram_total_mb=ram_total,
            ram_free_mb=ram_free,
            gpu=gpu_info
        )
        return spec

    def _detect_cpu(self) -> tuple[str, int, int]:
        logical_cores = os.cpu_count() or 4
        physical_cores = max(1, logical_cores // 2)
        model_name = f"{self.os_name} {self.arch} CPU"

        try:
            if self.os_name == "Linux":
                if os.path.exists("/proc/cpuinfo"):
                    with open("/proc/cpuinfo", "r") as f:
                        lines = f.readlines()
                    for line in lines:
                        if "model name" in line:
                            model_name = line.split(":", 1)[1].strip()
                            break
                # Try physical cores count via lscpu
                res = subprocess.run(["lscpu"], capture_output=True, text=True, timeout=2)
                if res.returncode == 0:
                    cores_per_socket = re.search(r"Core\(s\) per socket:\s+(\d+)", res.stdout)
                    sockets = re.search(r"Socket\(s\):\s+(\d+)", res.stdout)
                    if cores_per_socket and sockets:
                        physical_cores = int(cores_per_socket.group(1)) * int(sockets.group(1))
            elif self.os_name == "Darwin":
                res = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=2)
                if res.returncode == 0 and res.stdout.strip():
                    model_name = res.stdout.strip()
                else:
                    # Apple Silicon
                    res = subprocess.run(["sysctl", "-n", "hw.model"], capture_output=True, text=True, timeout=2)
                    if res.returncode == 0:
                        model_name = f"Apple Silicon ({res.stdout.strip()})"
                res_phys = subprocess.run(["sysctl", "-n", "hw.physicalcpu"], capture_output=True, text=True, timeout=2)
                if res_phys.returncode == 0 and res_phys.stdout.strip().isdigit():
                    physical_cores = int(res_phys.stdout.strip())
            elif self.os_name == "Windows":
                res = subprocess.run(["wmic", "cpu", "get", "Name"], capture_output=True, text=True, timeout=3)
                if res.returncode == 0:
                    lines = [l.strip() for l in res.stdout.splitlines() if l.strip() and "Name" not in l]
                    if lines:
                        model_name = lines[0]
        except Exception:
            pass

        return model_name, physical_cores, logical_cores

    def _detect_ram(self) -> tuple[int, int]:
        total_mb = 8192
        free_mb = 4096

        try:
            if self.os_name == "Linux":
                if os.path.exists("/proc/meminfo"):
                    mem_dict = {}
                    with open("/proc/meminfo", "r") as f:
                        for line in f:
                            parts = line.split(":")
                            if len(parts) == 2:
                                key = parts[0].strip()
                                val_str = parts[1].strip().split()[0]
                                if val_str.isdigit():
                                    mem_dict[key] = int(val_str) // 1024  # convert kB to MB
                    if "MemTotal" in mem_dict:
                        total_mb = mem_dict["MemTotal"]
                    if "MemAvailable" in mem_dict:
                        free_mb = mem_dict["MemAvailable"]
                    elif "MemFree" in mem_dict:
                        free_mb = mem_dict["MemFree"]
            elif self.os_name == "Darwin":
                res = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=2)
                if res.returncode == 0 and res.stdout.strip().isdigit():
                    total_mb = int(res.stdout.strip()) // (1024 * 1024)
                    free_mb = int(total_mb * 0.6)  # estimate
            elif self.os_name == "Windows":
                res = subprocess.run(["powershell", "-Command", "Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize,FreePhysicalMemory"], capture_output=True, text=True, timeout=4)
                if res.returncode == 0:
                    numbers = re.findall(r"\d+", res.stdout)
                    if len(numbers) >= 2:
                        total_mb = int(numbers[0]) // 1024
                        free_mb = int(numbers[1]) // 1024
        except Exception:
            pass

        return total_mb, free_mb

    def _detect_gpu(self, ram_total_mb: int) -> Optional[GPUInfo]:
        # 1. Try NVIDIA (nvidia-smi)
        try:
            res = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3
            )
            if res.returncode == 0 and res.stdout.strip():
                line = res.stdout.strip().splitlines()[0]
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    gpu_name = parts[0]
                    vram_total = int(parts[1])
                    vram_free = int(parts[2])
                    return GPUInfo(
                        vendor="NVIDIA",
                        name=gpu_name,
                        vram_total_mb=vram_total,
                        vram_free_mb=vram_free,
                        cuda_available=True,
                        vulkan_available=True
                    )
        except Exception:
            pass

        # 2. Try Apple Silicon (Metal Unified Memory)
        if self.os_name == "Darwin" and self.arch == "arm64":
            # On Apple Silicon, unified memory acts as VRAM (up to ~75% usable for Metal)
            metal_vram = int(ram_total_mb * 0.75)
            return GPUInfo(
                vendor="Apple",
                name="Apple Silicon Unified Metal GPU",
                vram_total_mb=metal_vram,
                vram_free_mb=int(metal_vram * 0.8),
                metal_available=True
            )

        # 3. Try AMD (rocm-smi or lspci check)
        try:
            res = subprocess.run(["rocm-smi", "--showid", "--csv"], capture_output=True, text=True, timeout=3)
            if res.returncode == 0 and res.stdout.strip():
                return GPUInfo(
                    vendor="AMD",
                    name="AMD ROCm GPU",
                    vram_total_mb=8192,
                    vram_free_mb=6144,
                    vulkan_available=True
                )
        except Exception:
            pass

        # 4. Try lspci check for Linux
        if self.os_name == "Linux":
            try:
                res = subprocess.run(["lspci"], capture_output=True, text=True, timeout=2)
                if res.returncode == 0:
                    for line in res.stdout.splitlines():
                        if "VGA compatible controller" in line or "3D controller" in line:
                            if "NVIDIA" in line:
                                return GPUInfo(vendor="NVIDIA", name=line.split(":", 2)[-1].strip(), vram_total_mb=4096, vram_free_mb=3072)
                            elif "AMD" in line or "Radeon" in line:
                                return GPUInfo(vendor="AMD", name=line.split(":", 2)[-1].strip(), vram_total_mb=4096, vram_free_mb=3072)
                            elif "Intel" in line:
                                return GPUInfo(vendor="Intel", name=line.split(":", 2)[-1].strip(), vram_total_mb=2048, vram_free_mb=1536)
            except Exception:
                pass

        return None


def save_hardware_config(spec: HardwareSpec, config_path: str = "config/device.json"):
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(spec.to_dict(), f, indent=2)


def get_hardware_info(config_path: str = "config/device.json", force_refresh: bool = False) -> HardwareSpec:
    detector = HardwareDetector()
    spec = detector.detect()
    save_hardware_config(spec, config_path)
    return spec


if __name__ == "__main__":
    spec = get_hardware_info()
    print("=== cllm Hardware Detection ===")
    print(f"OS Platform      : {spec.os_name} ({spec.arch})")
    print(f"CPU Model        : {spec.cpu_model}")
    print(f"CPU Cores        : {spec.cpu_cores_physical} Physical / {spec.cpu_cores_logical} Logical")
    print(f"System RAM       : {spec.ram_total_mb / 1024:.2f} GB Total ({spec.ram_free_mb / 1024:.2f} GB Available)")
    if spec.gpu:
        print(f"GPU Vendor       : {spec.gpu.vendor}")
        print(f"GPU Name         : {spec.gpu.name}")
        print(f"GPU VRAM         : {spec.gpu.vram_total_mb / 1024:.2f} GB Total ({spec.gpu.vram_free_mb / 1024:.2f} GB Free)")
        print(f"Acceleration     : CUDA={spec.gpu.cuda_available}, Metal={spec.gpu.metal_available}, Vulkan={spec.gpu.vulkan_available}")
    else:
        print("GPU Acceleration : None (CPU Mode)")
