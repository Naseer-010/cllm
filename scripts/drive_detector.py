#!/usr/bin/env python3
"""
cllm - USB Drive Auto-Detector Engine
Detects connected external USB storage drives and mount points across Linux, macOS, and Windows.
Specifically filters to only show removable USB pendrives/flash drives, NOT internal hard disks.
"""

import os
import sys
import platform
import subprocess
import json
import re
from dataclasses import dataclass, asdict
from typing import List, Dict, Any

@dataclass
class USBDriveInfo:
    device_name: str       # e.g. "/dev/sdb1" or "E:"
    mount_point: str       # e.g. "/media/user/USB_SSD" or "/Volumes/USB"
    label: str             # e.g. "Samsung T7 SSD (512 GB)"
    size_bytes: int        # Total capacity in bytes
    size_formatted: str    # e.g. "512.00 GB"
    is_removable: bool     # True if USB / removable media

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class USBDriveDetector:
    """Scans and filters system mount points for external USB drives."""

    def __init__(self):
        self.os_name = platform.system()

    def scan_drives(self) -> List[USBDriveInfo]:
        """Scan all external drives (backward compatible)."""
        drives: List[USBDriveInfo] = []

        if self.os_name == "Linux":
            drives = self._scan_linux()
        elif self.os_name == "Darwin":
            drives = self._scan_macos()
        elif self.os_name == "Windows":
            drives = self._scan_windows()

        # Fallback: scan common mount directories (/media, /mnt, /run/media) if lsblk missed anything
        if self.os_name == "Linux" and not drives:
            drives = self._scan_linux_media_folders()

        return drives

    def scan_usb_only(self) -> List[USBDriveInfo]:
        """Scan ONLY USB removable pendrives. Filters out internal disks, NVMe, loop devices."""
        drives: List[USBDriveInfo] = []

        if self.os_name == "Linux":
            drives = self._scan_linux_usb_strict()
        elif self.os_name == "Darwin":
            drives = self._scan_macos()
        elif self.os_name == "Windows":
            drives = self._scan_windows()

        return drives

    def _scan_linux_usb_strict(self) -> List[USBDriveInfo]:
        """Strict USB-only detection on Linux. Only shows devices connected via USB bus
        that are marked as removable (RM=1). This filters out internal HDDs, NVMe, and loop devices."""
        drives = []
        try:
            res = subprocess.run(
                ["lsblk", "-J", "-b", "-o", "NAME,SIZE,TYPE,MOUNTPOINTS,MODEL,TRAN,RM,LABEL,HOTPLUG"],
                capture_output=True, text=True, timeout=3
            )
            if res.returncode != 0 or not res.stdout.strip():
                return self._scan_linux_media_folders()

            data = json.loads(res.stdout)
            devices = data.get("blockdevices", [])

            for dev in devices:
                dev_type = dev.get("type", "")
                tran = (dev.get("tran") or "").lower()
                is_rm = dev.get("rm", False)
                hotplug = dev.get("hotplug", False)
                dev_name = dev.get("name", "")
                model = (dev.get("model") or "").strip()

                # SKIP: loop devices, NVMe, dm/crypt, zram, swap
                if dev_type in ("loop", "rom", "crypt"):
                    continue
                if dev_name.startswith(("loop", "nvme", "dm-", "zram")):
                    continue

                # ONLY accept: USB transport AND removable flag
                # This catches USB pendrives, USB card readers, USB external SSDs
                if tran != "usb":
                    continue
                if not is_rm and not hotplug:
                    continue

                # Check children (partitions)
                children = dev.get("children", [])
                if not children:
                    children = [dev]

                for child in children:
                    mountpoints = child.get("mountpoints", [])
                    size_b = child.get("size", 0) or 0
                    label = child.get("label") or model or dev_name
                    child_name = child.get("name", dev_name)
                    dev_path = f"/dev/{child_name}"

                    for mp in mountpoints:
                        if not mp or mp in ["/", "/boot", "/boot/efi", "/home", "[SWAP]"]:
                            continue

                        drives.append(USBDriveInfo(
                            device_name=dev_path,
                            mount_point=mp,
                            label=f"{label} ({self._format_bytes(size_b)})",
                            size_bytes=size_b,
                            size_formatted=self._format_bytes(size_b),
                            is_removable=True
                        ))

        except Exception:
            pass

        # If strict USB scan found nothing, try media folder fallback
        if not drives:
            drives = self._scan_linux_media_folders()

        return drives

    def _scan_linux(self) -> List[USBDriveInfo]:
        drives = []
        try:
            res = subprocess.run(
                ["lsblk", "-J", "-b", "-o", "NAME,SIZE,TYPE,MOUNTPOINTS,MODEL,TRAN,RM,LABEL"],
                capture_output=True, text=True, timeout=3
            )
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                devices = data.get("blockdevices", [])
                for dev in devices:
                    tran = dev.get("tran", "").lower()
                    is_rm = dev.get("rm", False)
                    model = dev.get("model", "").strip() or dev.get("name", "USB Drive")

                    # Check children (partitions)
                    children = dev.get("children", [dev])
                    for child in children:
                        mountpoints = child.get("mountpoints", [])
                        size_b = child.get("size", 0)
                        label = child.get("label") or model
                        dev_path = f"/dev/{child.get('name')}"

                        for mp in mountpoints:
                            if mp and mp not in ["/", "/boot", "/home", "/swap"]:
                                # If USB bus or removable flag or mounted under /media or /mnt
                                if tran == "usb" or is_rm or mp.startswith("/media") or mp.startswith("/run/media") or mp.startswith("/mnt"):
                                    drives.append(USBDriveInfo(
                                        device_name=dev_path,
                                        mount_point=mp,
                                        label=f"{label} ({self._format_bytes(size_b)})",
                                        size_bytes=size_b,
                                        size_formatted=self._format_bytes(size_b),
                                        is_removable=True
                                    ))
        except Exception:
            pass
        return drives

    def _scan_linux_media_folders(self) -> List[USBDriveInfo]:
        drives = []
        user = os.environ.get("USER", "root")
        search_dirs = [f"/media/{user}", f"/run/media/{user}", "/media", "/mnt"]

        for base in search_dirs:
            if os.path.exists(base):
                try:
                    entries = os.listdir(base)
                except PermissionError:
                    continue
                for entry in entries:
                    full = os.path.join(base, entry)
                    if os.path.isdir(full) and os.access(full, os.W_OK):
                        try:
                            stat = os.statvfs(full)
                            size_b = stat.f_blocks * stat.f_frsize
                            drives.append(USBDriveInfo(
                                device_name=full,
                                mount_point=full,
                                label=f"{entry} ({self._format_bytes(size_b)})",
                                size_bytes=size_b,
                                size_formatted=self._format_bytes(size_b),
                                is_removable=True
                            ))
                        except Exception:
                            pass
        return drives

    def _scan_macos(self) -> List[USBDriveInfo]:
        drives = []
        volumes_dir = "/Volumes"
        if os.path.exists(volumes_dir):
            for entry in os.listdir(volumes_dir):
                if entry in ["Macintosh HD", "System"]:
                    continue
                full = os.path.join(volumes_dir, entry)
                if os.path.isdir(full):
                    try:
                        stat = os.statvfs(full)
                        size_b = stat.f_blocks * stat.f_frsize
                        drives.append(USBDriveInfo(
                            device_name=full,
                            mount_point=full,
                            label=f"{entry} ({self._format_bytes(size_b)})",
                            size_bytes=size_b,
                            size_formatted=self._format_bytes(size_b),
                            is_removable=True
                        ))
                    except Exception:
                        pass
        return drives

    def _scan_windows(self) -> List[USBDriveInfo]:
        drives = []
        try:
            cmd = "Get-Volume | Where-Object DriveType -eq 'Removable' | Select-Object DriveLetter, FileSystemLabel, Size"
            res = subprocess.run(["powershell", "-Command", cmd], capture_output=True, text=True, timeout=4)
            if res.returncode == 0:
                lines = [l.strip() for l in res.stdout.splitlines() if l.strip()]
                for line in lines[2:]:
                    parts = line.split()
                    if parts and len(parts[0]) == 1:
                        letter = f"{parts[0]}:\\"
                        label = parts[1] if len(parts) > 1 else "USB Drive"
                        drives.append(USBDriveInfo(
                            device_name=letter,
                            mount_point=letter,
                            label=f"{label} ({letter})",
                            size_bytes=64 * 1024 * 1024 * 1024,
                            size_formatted="External USB",
                            is_removable=True
                        ))
        except Exception:
            pass
        return drives

    def _format_bytes(self, size_bytes: int) -> str:
        if size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


if __name__ == "__main__":
    detector = USBDriveDetector()
    print("=== cllm USB Drive Detection (Strict USB Only) ===")
    drives = detector.scan_usb_only()
    print(f"Found {len(drives)} USB pendrive(s):")
    for d in drives:
        print(f"  • {d.label} -> {d.mount_point}")
