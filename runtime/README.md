# cllm Runtime Directory

This directory stores cross-platform precompiled `llama.cpp` binary executables (`llama-cli`).

## Directory Layout
```
runtime/
├── linux-x86_64/
│   └── llama-cli
├── windows-x86_64/
│   └── llama-cli.exe
└── macos-arm64/
    └── llama-cli
```

To download host-appropriate prebuilt binaries automatically, run:
```bash
./cllm setup
```
or
```bash
python3 -m scripts.setup_runtime --download
```
