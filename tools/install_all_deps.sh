#!/bin/bash
echo "=== Installing ALL dependencies from pyproject.toml ==="
pip3 install --break-system-packages --ignore-installed -i https://pypi.tuna.tsinghua.edu.cn/simple \
  aiohttp \
  aiometer \
  aiofiles \
  arxiv \
  beautifulsoup4 \
  binaryornot \
  colorlog \
  docker \
  fake-useragent \
  fastapi \
  'fastmcp>=2.10.0,<2.14.0' \
  fasttext \
  filelock \
  firecrawl-py \
  func_argparse \
  'gradio>=5.47.2,<6.0' \
  html2image \
  httpx \
  httpx-retries \
  jinja2 \
  json-repair \
  jsonlines \
  langchain_mcp_adapters \
  lxml \
  markitdown \
  mcp \
  mistune \
  'numpy<2.0.0' \
  oaib \
  openai \
  pydantic \
  'pydantic[email]' \
  pydantic-settings \
  playwright \
  python-pptx \
  pyyaml \
  rich \
  tenacity \
  tiktoken \
  tqdm \
  typing-extensions \
  uvicorn \
  websockets \
  2>&1 | tail -30

echo "=== Done ==="