#!/bin/bash
echo "=== Force installing with ignore-installed ==="
pip3 install --break-system-packages --ignore-installed -i https://pypi.tuna.tsinghua.edu.cn/simple \
  typing-extensions \
  pydantic \
  pydantic-core \
  pydantic-settings \
  'pydantic[email]' \
  openai \
  annotated-types \
  typing-inspection \
  2>&1 | tail -15

echo "=== Done ==="