#!/bin/bash
echo "=== Installing all missing packages ==="
pip3 install --break-system-packages -i https://pypi.tuna.tsinghua.edu.cn/simple \
  pydantic \
  openai \
  'pydantic[email]' \
  pydantic-settings \
  pydantic-core \
  typing-extensions \
  typing-inspection \
  annotated-types \
  2>&1 | tail -20

echo "=== Done ==="