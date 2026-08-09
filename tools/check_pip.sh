#!/bin/bash
echo "=== Python path ==="
python3 -c 'import sys; print("\n".join(sys.path))'

echo "=== Pip show beautifulsoup4 ==="
pip3 show beautifulsoup4 2>&1

echo "=== Pip show json-repair ==="
pip3 show json-repair 2>&1

echo "=== Installing missing packages ==="
pip3 install --break-system-packages beautifulsoup4 json-repair 2>&1 | tail -5