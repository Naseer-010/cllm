#!/bin/bash
set -e

echo "=== cllm Setup & Verification ==="
echo "Ensuring file permissions..."
chmod +x ./cllm ./bin/cllm

echo "Detecting host hardware..."
python3 ./scripts/hardware.py

echo "Checking portable models..."
python3 ./scripts/model_manager.py

echo ""
echo "cllm setup completed!"
echo "Run './cllm' to launch interactive mode, or './cllm --dry-run' to test simulation mode."
