# cllm Models Directory

This directory stores portable model packages and `.gguf` weights.

## Directory Structure
Each model can either be stored in its own folder with a `manifest.json` metadata file:

```
models/
├── qwen2.5-coder-3b-instruct/
│   ├── model.gguf (or qwen2.5-coder-3b-instruct-q4_k_m.gguf)
│   └── manifest.json
└── llama3.2-3b-instruct/
    ├── model.gguf
    └── manifest.json
```

Or placed directly as a standalone GGUF file:
```
models/
└── my-custom-model.gguf
```

When `cllm` is executed, it automatically scans all subdirectories and `.gguf` files, inspects quantizations, and generates missing manifests on the fly.
