#!/usr/bin/env python3
"""
cllm - Web Chat Server
Serves a ChatGPT-like web interface and proxies chat requests to a local llama.cpp server
(llama-server) running the GGUF model from the USB drive.
"""

import os
import sys
import json
import time
import signal
import shutil
import subprocess
import threading
import urllib.request
import urllib.parse
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import Dict, Any, Optional, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.model_manager import ModelManager
from scripts.hardware import get_hardware_info


class LlamaServerManager:
    """Manages a llama-server subprocess for model inference."""

    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.process: Optional[subprocess.Popen] = None
        self.api_port = 8081
        self.model_info: Dict[str, Any] = {}

    def find_llama_server(self) -> Optional[str]:
        """Find llama-server binary: portable runtime > system PATH."""
        hw = get_hardware_info(os.path.join(self.root_dir, "config", "device.json"))
        os_folder = f"{hw.os_name.lower()}-{hw.arch}"

        candidates = [
            os.path.join(self.root_dir, "runtime", os_folder, "llama-server"),
            os.path.join(self.root_dir, "runtime", "llama-server"),
            shutil.which("llama-server"),
            shutil.which("llama-cpp-server"),
        ]

        for path in candidates:
            if path and os.path.exists(path) and os.access(path, os.X_OK):
                return path

        return None

    def find_model(self) -> Optional[Dict[str, Any]]:
        """Find the first available GGUF model on the drive."""
        mm = ModelManager(os.path.join(self.root_dir, "models"))
        models = mm.scan_models()

        if not models:
            return None

        m = models[0]
        self.model_info = {
            "name": m.name,
            "filename": m.filename,
            "full_path": m.full_path,
            "size": m.size_formatted,
            "quantization": m.quantization,
            "context_length": m.context_length,
        }
        return self.model_info

    def start(self) -> bool:
        """Start llama-server with the discovered model."""
        server_bin = self.find_llama_server()
        model = self.find_model()

        if not model:
            print("[Error] No GGUF model found in models/ directory.")
            return False

        if not server_bin:
            print("[Warning] llama-server binary not found. Running in demo mode.")
            print("  Install llama.cpp or run: ./cllm setup")
            return False

        hw = get_hardware_info(os.path.join(self.root_dir, "config", "device.json"))
        threads = max(1, min(8, hw.cpu_cores_physical))
        ctx_size = min(model.get("context_length", 4096), 4096)
        gpu_layers = 0

        if hw.gpu:
            if hw.gpu.cuda_available or hw.gpu.metal_available or hw.gpu.vulkan_available:
                gpu_layers = 99

        cmd = [
            server_bin,
            "-m", model["full_path"],
            "--host", "127.0.0.1",
            "--port", str(self.api_port),
            "-c", str(ctx_size),
            "-t", str(threads),
            "-ngl", str(gpu_layers),
        ]

        print(f"  Starting llama-server on port {self.api_port}...")
        print(f"  Model: {model['name']} ({model['quantization']})")

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            # Wait for server to be ready
            for _ in range(30):
                time.sleep(0.5)
                try:
                    req = urllib.request.Request(f"http://127.0.0.1:{self.api_port}/health")
                    resp = urllib.request.urlopen(req, timeout=1)
                    if resp.status == 200:
                        print("  llama-server is ready.")
                        return True
                except Exception:
                    if self.process.poll() is not None:
                        stderr = self.process.stderr.read().decode() if self.process.stderr else ""
                        print(f"  [Error] llama-server exited: {stderr[:200]}")
                        return False
                    continue

            print("  [Warning] llama-server did not respond in time.")
            return False
        except Exception as e:
            print(f"  [Error] Failed to start llama-server: {e}")
            return False

    def stop(self):
        """Stop the llama-server subprocess."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None


class ChatServerHandler(SimpleHTTPRequestHandler):
    """HTTP handler for the chat web UI and API."""

    llama_manager: LlamaServerManager = None
    demo_mode: bool = False
    shutdown_flag: threading.Event = None

    def __init__(self, *args, **kwargs):
        chat_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui", "chat"
        )
        super().__init__(*args, directory=chat_dir, **kwargs)

    def log_message(self, format, *args):
        pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/model-info":
            info = self.llama_manager.model_info if self.llama_manager else {}
            if not info:
                info = {"name": "No Model", "filename": "", "size": "", "quantization": ""}
            info["demo_mode"] = self.demo_mode
            self._send_json(info)
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/chat":
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length))
            message = body.get("message", "")
            history = body.get("history", [])

            if self.demo_mode:
                self._handle_demo_chat(message, history)
            else:
                self._handle_llama_chat(message, history)

        elif self.path == "/api/shutdown":
            self._send_json({"status": "ok"})
            if self.shutdown_flag:
                self.shutdown_flag.set()
        else:
            self._send_json({"error": "Not found"}, status=404)

    def _handle_llama_chat(self, message: str, history: List[Dict]):
        """Proxy chat to llama-server /v1/chat/completions endpoint with streaming."""
        messages = []
        messages.append({"role": "system", "content": "You are a helpful AI assistant running locally on this device."})
        for h in history:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": message})

        payload = json.dumps({
            "model": "local",
            "messages": messages,
            "stream": True,
            "temperature": 0.7,
            "max_tokens": 2048,
        }).encode("utf-8")

        try:
            api_url = f"http://127.0.0.1:{self.llama_manager.api_port}/v1/chat/completions"
            req = urllib.request.Request(
                api_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=120)

            # Stream SSE to client
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            for line in resp:
                line = line.decode("utf-8").strip()
                if not line:
                    continue
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        self.wfile.write(b'data: {"done": true}\n\n')
                        self.wfile.flush()
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        token = delta.get("content", "")
                        if token:
                            sse_data = json.dumps({"token": token})
                            self.wfile.write(f"data: {sse_data}\n\n".encode("utf-8"))
                            self.wfile.flush()
                    except json.JSONDecodeError:
                        continue

            resp.close()

        except Exception as e:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            error_msg = f"Error communicating with model server: {str(e)}"
            self.wfile.write(f'data: {{"token": "{error_msg}"}}\n\n'.encode("utf-8"))
            self.wfile.write(b'data: {"done": true}\n\n')
            self.wfile.flush()

    def _handle_demo_chat(self, message: str, history: List[Dict]):
        """Generate a demo response when no llama-server is available."""
        model_name = self.llama_manager.model_info.get("name", "cllm") if self.llama_manager else "cllm"

        prompt_lower = message.lower().strip()

        if any(w in prompt_lower for w in ["hello", "hi", "hey"]):
            response = f"Hello! I'm **{model_name}**, running locally on your device. How can I help you today?"
        elif any(w in prompt_lower for w in ["who are you", "what are you"]):
            response = (
                f"I'm **{model_name}**, a language model running entirely on your local machine via the **cllm** portable system. "
                f"No internet connection needed \u2014 everything stays private on this device."
            )
        elif "code" in prompt_lower or "python" in prompt_lower or "example" in prompt_lower:
            response = (
                "Here's a simple Python example:\n\n"
                "```python\ndef greet(name):\n    return f\"Hello, {name}! Welcome to cllm.\"\n\n"
                "print(greet(\"User\"))\n```\n\n"
                "This runs entirely locally \u2014 no cloud APIs involved."
            )
        elif any(w in prompt_lower for w in ["help", "what can you do"]):
            response = (
                "I can help with:\n\n"
                "- **Writing & editing** text, emails, and documents\n"
                "- **Coding** in Python, JavaScript, and more\n"
                "- **Explaining** concepts and answering questions\n"
                "- **Brainstorming** ideas and creative writing\n\n"
                "All running locally and privately on your machine!"
            )
        else:
            response = (
                f"This is a demo response from **{model_name}** (simulation mode). "
                f"The `llama-server` binary was not found, so I'm running in offline demo mode.\n\n"
                f"To enable real inference, run:\n```bash\n./cllm setup\n```\n"
                f"This will download the llama.cpp runtime for your system."
            )

        # Stream the response token-by-token
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        words = response.split(" ")
        for i, word in enumerate(words):
            token = word if i == 0 else " " + word
            sse_data = json.dumps({"token": token})
            self.wfile.write(f"data: {sse_data}\n\n".encode("utf-8"))
            self.wfile.flush()
            time.sleep(0.03)

        self.wfile.write(b'data: {"done": true}\n\n')
        self.wfile.flush()

    def _send_json(self, data: Dict[str, Any], status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))


def run_chat_server(root_dir: str = ".", port: int = 7870, open_browser: bool = True):
    """Launch the chat server with llama-server backend."""
    root_dir = os.path.abspath(root_dir)
    shutdown_flag = threading.Event()

    # Initialize llama-server manager
    manager = LlamaServerManager(root_dir)
    model = manager.find_model()

    if not model:
        print("\n  [Error] No GGUF model found in models/ directory.")
        print("  Flash a model first using: ./cllm-flasher")
        return

    print(f"\n  cllm Chat Server")
    print(f"  Model: {model['name']} ({model['quantization']}, {model['size']})")

    # Try to start llama-server
    demo_mode = not manager.start()

    if demo_mode:
        print("  Mode: Demo (simulation)")
    else:
        print("  Mode: Local inference via llama-server")

    # Configure handler
    ChatServerHandler.llama_manager = manager
    ChatServerHandler.demo_mode = demo_mode
    ChatServerHandler.shutdown_flag = shutdown_flag

    # Start HTTP server
    server_address = ("127.0.0.1", port)
    httpd = HTTPServer(server_address, ChatServerHandler)

    url = f"http://127.0.0.1:{port}"
    print(f"  Chat UI: {url}")
    print(f"  Press Ctrl+C to stop.\n")

    if open_browser:
        threading.Thread(
            target=lambda: (time.sleep(0.8), webbrowser.open(url)), daemon=True
        ).start()

    # Run server until shutdown
    def serve():
        while not shutdown_flag.is_set():
            httpd.handle_request()

    server_thread = threading.Thread(target=serve, daemon=True)
    server_thread.start()

    try:
        shutdown_flag.wait()
    except KeyboardInterrupt:
        pass
    finally:
        print("\n  Shutting down...")
        manager.stop()
        httpd.server_close()
        print("  Chat server stopped.")


if __name__ == "__main__":
    port = 7870
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])
    run_chat_server(".", port)
