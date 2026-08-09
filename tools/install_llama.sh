#!/bin/bash
set -e

echo "=== Installing llama.cpp build deps ==="
apt-get install -y build-essential cmake 2>&1 | tail -5

echo "=== Cloning llama.cpp ==="
cd /tmp
git clone --depth 1 https://gitclone.com/github.com/ggerganov/llama.cpp.git 2>&1

echo "=== Building llama.cpp ==="
cd llama.cpp
cmake -B build -DGGML_CUDA=OFF -DLLAMA_CURL=OFF 2>&1 | tail -5
cmake --build build --config Release -j$(nproc) --target llama-server 2>&1 | tail -10

echo "=== Installing ==="
cp build/bin/llama-server /usr/local/bin/
echo "llama-server installed: $(which llama-server)"

echo "=== DONE ==="