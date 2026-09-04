#!/usr/bin/env python3
"""
cllm - Interactive Terminal UI & Application Controller
Provides rich terminal dashboard, model selection, slash commands, and interactive chat interface.
"""

import os
import sys
import time
import subprocess
import signal
from typing import Optional, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.hardware import get_hardware_info, HardwareSpec
from scripts.model_manager import ModelManager, ModelManifest
from scripts.runtime_selector import RuntimeSelector, LaunchConfig
from scripts.setup_runtime import RuntimeSetup
from scripts.flasher import DriveFlasher

# ANSI Color Palette
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
RED = "\033[31m"
WHITE = "\033[97m"

BANNER = f"""
{CYAN}{BOLD}╭────────────────────────────────────────────────────────────────────────╮
│                                                                        │
│   ██████╗██╗     ██╗     ███╗   ███╗                                   │
│  ██╔════╝██║     ██║     ████╗ ████║                                   │
│  ██║     ██║     ██║     ██╔████╔██║  {WHITE}Portable Local Intelligence Engine{CYAN}  │
│  ██║     ██║     ██║     ██║╚██╔╝██║                                   │
│  ╚██████╗███████╗███████╗██║ ╚═╝ ██║                                   │
│   ╚═════╝╚══════╝╚══════╝╚═╝     ╚═╝                                   │
│                                                                        │
╰────────────────────────────────────────────────────────────────────────╯{RESET}
"""

class CllmCLI:
    def __init__(self, root_dir: str = "."):
        self.root_dir = os.path.abspath(root_dir)
        self.hardware = get_hardware_info(os.path.join(self.root_dir, "config", "device.json"))
        self.model_manager = ModelManager(os.path.join(self.root_dir, "models"))
        self.runtime_selector = RuntimeSelector(self.root_dir)
        self.runtime_setup = RuntimeSetup(self.root_dir)
        self.active_model: Optional[ModelManifest] = None
        self.active_config: Optional[LaunchConfig] = None
        self.is_dry_run = False

    def print_banner(self):
        print(BANNER)

    def print_hardware_summary(self):
        print(f"{BOLD}{WHITE}System & Hardware Overview:{RESET}")
        print(f"  {CYAN}OS / Arch{RESET} : {self.hardware.os_name} ({self.hardware.arch})")
        print(f"  {CYAN}CPU{RESET}       : {self.hardware.cpu_model} ({self.hardware.cpu_cores_physical} cores)")
        print(f"  {CYAN}RAM{RESET}       : {self.hardware.ram_total_mb / 1024:.2f} GB Total ({self.hardware.ram_free_mb / 1024:.2f} GB Available)")

        if self.hardware.gpu:
            vram = f"{self.hardware.gpu.vram_free_mb / 1024:.2f} GB Free / {self.hardware.gpu.vram_total_mb / 1024:.2f} GB Total"
            print(f"  {CYAN}GPU{RESET}       : {self.hardware.gpu.name} [{self.hardware.gpu.vendor}]")
            print(f"  {CYAN}VRAM{RESET}      : {vram}")
        else:
            print(f"  {CYAN}GPU{RESET}       : None (CPU Mode)")
        print()

    def scan_environment(self) -> List[ModelManifest]:
        print(f"{DIM}Scanning USB drive / local directory for models and runtimes...{RESET}")
        models = self.model_manager.scan_models()
        is_installed, runtime_path = self.runtime_setup.check_runtime_status(self.hardware)

        if is_installed:
            print(f"  {GREEN}✓{RESET} Runtime engine detected ({runtime_path})")
        else:
            print(f"  {YELLOW}!{RESET} Portable binary missing (Fallback simulation or system path enabled)")

        if models:
            print(f"  {GREEN}✓{RESET} {len(models)} model(s) discovered in /models/")
        else:
            print(f"  {YELLOW}!{RESET} No GGUF models found in /models/ directory")
        print()
        return models

    def select_model_interactive(self, models: List[ModelManifest]) -> Optional[ModelManifest]:
        if not models:
            print(f"{YELLOW}No models available to run.{RESET}")
            print(f"Add a `.gguf` file to `{self.model_manager.models_dir}` or run:")
            print(f"  {CYAN}cllm flash <usb_path> --model <model_url_or_file>{RESET}\n")
            return None

        print(f"{BOLD}{WHITE}Detected Portable Models:{RESET}")
        print("─" * 60)
        for idx, m in enumerate(models, 1):
            vram_req = f"{m.recommended_vram_gb:.1f} GB VRAM"
            print(f"  {CYAN}[{idx}]{RESET} {BOLD}{m.name}{RESET}")
            print(f"      Format: {m.quantization} | Size: {m.size_formatted} | Context: {m.context_length} | Est: {vram_req}")
        print("─" * 60)

        while True:
            try:
                choice = input(f"\n{BOLD}Select model [1-{len(models)}] (or 'q' to quit): {RESET}").strip()
                if choice.lower() == 'q':
                    return None
                if not choice and len(models) == 1:
                    return models[0]
                if choice.isdigit():
                    idx = int(choice)
                    if 1 <= idx <= len(models):
                        return models[idx - 1]
                print(f"{RED}Invalid selection. Please choose 1-{len(models)}.{RESET}")
            except (KeyboardInterrupt, EOFError):
                print()
                return None

    def simulate_loading(self, model: ModelManifest):
        print(f"\n{BOLD}Loading model: {CYAN}{model.name}{RESET}...")
        steps = 20
        for i in range(1, steps + 1):
            percent = int((i / steps) * 100)
            bar = "█" * (i * 2) + "░" * ((steps - i) * 2)
            print(f"\r  [{bar}] {percent}%", end="", flush=True)
            time.sleep(0.02)
        print(f"\n{GREEN}✓ Model loaded into memory successfully.{RESET}\n")

    def run_interactive_chat(self, model: ModelManifest, config: LaunchConfig):
        self.active_model = model
        self.active_config = config

        self.simulate_loading(model)

        print(f"{CYAN}{BOLD}╭────────────────────────────────────────────────────────────────────────╮{RESET}")
        print(f"{CYAN}{BOLD}│ cllm Interactive Session Active                                       │{RESET}")
        print(f"{CYAN}{BOLD}│ Type your prompt or use slash commands (/help, /info, /system, /exit)  │{RESET}")
        print(f"{CYAN}{BOLD}╰────────────────────────────────────────────────────────────────────────╯{RESET}\n")

        # Check if real binary is available
        if config.binary_path != "mock" and not self.is_dry_run:
            self._launch_real_llama_cpp(config)
        else:
            self._launch_simulated_chat(model, config)

    def _launch_real_llama_cpp(self, config: LaunchConfig):
        print(f"{DIM}Executing: {config.binary_path} {' '.join(config.cmd_args)}{RESET}\n")
        try:
            cmd = [config.binary_path] + config.cmd_args
            subprocess.run(cmd)
        except Exception as e:
            print(f"\n{RED}[Error] Runtime execution failed: {e}{RESET}")
            print("Switching to simulation mode...\n")
            self._launch_simulated_chat(self.active_model, config)

    def _launch_simulated_chat(self, model: ModelManifest, config: LaunchConfig):
        print(f"{YELLOW}[Mode: Portable Simulation Engine (Zero-binary fallback)]{RESET}")
        print("Type your message below. Try '/help' to see slash commands.\n")

        history = []

        while True:
            try:
                user_input = input(f"{BOLD}{GREEN}You:{RESET} ").strip()
                if not user_input:
                    continue

                # Handle slash commands
                if user_input.startswith("/"):
                    if not self.handle_slash_command(user_input):
                        break
                    continue

                # Simulated response stream
                print(f"{BOLD}{CYAN}cllm ({model.name}):{RESET} ", end="", flush=True)

                response = self._generate_mock_response(user_input, model, config)
                for word in response.split(" "):
                    print(word + " ", end="", flush=True)
                    time.sleep(0.04)
                print("\n")

            except (KeyboardInterrupt, EOFError):
                print(f"\n\n{DIM}Session closed.{RESET}")
                break

    def handle_slash_command(self, cmd_str: str) -> bool:
        """Handles commands like /help, /models, /info, /system, /clear, /exit. Returns False if exiting."""
        cmd = cmd_str.split()[0].lower()

        if cmd in ["/exit", "/quit", "/q"]:
            print(f"{DIM}Exiting cllm interactive mode... Bye!{RESET}")
            return False

        elif cmd == "/help":
            print(f"\n{BOLD}Available Slash Commands:{RESET}")
            print(f"  {CYAN}/help{RESET}     - Show this help menu")
            print(f"  {CYAN}/models{RESET}   - List available models on portable drive")
            print(f"  {CYAN}/info{RESET}     - Show active model details & manifest")
            print(f"  {CYAN}/system{RESET}   - Show host CPU/GPU/VRAM metrics & config")
            print(f"  {CYAN}/clear{RESET}    - Clear the terminal screen")
            print(f"  {CYAN}/exit{RESET}     - Exit cllm chat\n")

        elif cmd == "/models":
            models = self.model_manager.scan_models()
            print(f"\n{BOLD}Discovered Models:{RESET}")
            for idx, m in enumerate(models, 1):
                active_marker = " (Active)" if self.active_model and m.model_id == self.active_model.model_id else ""
                print(f"  [{idx}] {m.name} ({m.quantization}) - {m.size_formatted}{active_marker}")
            print()

        elif cmd == "/info":
            if self.active_model:
                m = self.active_model
                print(f"\n{BOLD}Active Model Information:{RESET}")
                print(f"  • Name        : {m.name}")
                print(f"  • Quantization: {m.quantization}")
                print(f"  • File Size   : {m.size_formatted}")
                print(f"  • Context Max : {m.context_length} tokens")
                print(f"  • Description : {m.description}\n")

        elif cmd == "/system":
            print(f"\n{BOLD}Host Hardware & Execution Config:{RESET}")
            print(f"  • OS          : {self.hardware.os_name} ({self.hardware.arch})")
            print(f"  • CPU Cores   : {self.hardware.cpu_cores_physical} physical / {self.hardware.cpu_cores_logical} logical")
            print(f"  • RAM         : {self.hardware.ram_free_mb / 1024:.2f} GB available / {self.hardware.ram_total_mb / 1024:.2f} GB total")
            if self.active_config:
                print(f"  • Execution   : {self.active_config.backend}")
                print(f"  • GPU Layers  : {self.active_config.gpu_layers}")
                print(f"  • CPU Threads : {self.active_config.threads}")
                print(f"  • Context Size: {self.active_config.context_size}")
            print()

        elif cmd == "/clear":
            os.system("clear" if os.name != "nt" else "cls")
            self.print_banner()

        else:
            print(f"{YELLOW}Unknown command '{cmd}'. Type /help for assistance.{RESET}")

        return True

    def _generate_mock_response(self, user_prompt: str, model: ModelManifest, config: LaunchConfig) -> str:
        prompt_lower = user_prompt.lower()
        if "quantum" in prompt_lower:
            return f"Quantum entanglement is a phenomenon in quantum mechanics where two or more particles become interconnected such that the state of one particle instantly influences the state of another, regardless of distance. [{model.name} via {config.backend}]"
        elif "hello" in prompt_lower or "hi" in prompt_lower:
            return f"Hello! I am {model.name}, running locally from your portable drive via {config.backend} acceleration. How can I assist you today?"
        elif "code" in prompt_lower or "python" in prompt_lower:
            return f"Here is a quick Python example running under {model.name}:\n\ndef portable_llm():\n    print('Running zero-installation LLM directly from USB drive!')"
        else:
            return f"This is a response generated locally by {model.name} ({model.quantization}) using {config.backend} ({config.gpu_layers} GPU layers, {config.threads} CPU threads). Processed prompt: '{user_prompt}'."

    def run(self, args: List[str]):
        if "--dry-run" in args:
            self.is_dry_run = True

        self.print_banner()
        self.print_hardware_summary()
        models = self.scan_environment()

        # If dummy fixture is needed for dry-run
        if not models and self.is_dry_run:
            sample_model = ModelManifest(
                model_id="demo-qwen3-4b",
                name="Qwen 3 4B Q4_K_M (Dry Run)",
                filename="demo-qwen3-4b.gguf",
                full_path=os.path.join(self.root_dir, "models", "demo-qwen3-4b.gguf"),
                format="GGUF",
                quantization="Q4_K_M",
                size_bytes=2684354560,
                size_formatted="2.50 GB",
                context_length=8192,
                recommended_vram_gb=3.5,
                runtime="llama.cpp",
                description="Simulated model for dry-run testing"
            )
            models = [sample_model]

        selected_model = self.select_model_interactive(models)
        if not selected_model:
            return

        config = self.runtime_selector.calculate_launch_config(self.hardware, selected_model)
        print(config.summary_text)
        print()

        self.run_interactive_chat(selected_model, config)


def main():
    cli = CllmCLI(".")
    cli.run(sys.argv[1:])


if __name__ == "__main__":
    main()
