"""测试 API 连接"""
import sys
sys.path.insert(0, ".")

from config import API_KEY, API_BASE_URL, MODEL_NAME
from openai import OpenAI

print(f"BASE_URL: {repr(API_BASE_URL)}")
print(f"API_KEY: {repr(API_KEY[:20])}...")
print(f"MODEL: {repr(MODEL_NAME)}")

try:
    client = OpenAI(base_url=API_BASE_URL, api_key=API_KEY)
    completion = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": "say hi"}],
        max_tokens=10,
    )
    print(f"SUCCESS: {completion.choices[0].message.content}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")