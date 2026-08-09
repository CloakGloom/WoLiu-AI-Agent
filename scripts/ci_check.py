"""
CI 辅助脚本 —— 在推送到 main 分支时自动运行
"""
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run(cmd: str, **kwargs):
    print(f"\n> {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=str(PROJECT_ROOT), **kwargs)
    return result.returncode


def main():
    checks = True

    # 1. 语法检查
    print("=" * 60)
    print("1/4 语法检查")
    ret = run(f"{sys.executable} -m compileall agent/ server/ -q")
    checks &= (ret == 0)

    # 2. 导入检查
    print("=" * 60)
    print("2/4 导入检查")
    ret = run(f"{sys.executable} -c \"from agent.config import load; load(); print('config OK'); "
              f"from agent.utils import get_project_root, is_port_open; print('utils OK')\"")
    checks &= (ret == 0)

    # 3. 单元测试
    print("=" * 60)
    print("3/4 单元测试")
    ret = run(f"{sys.executable} -m pytest tests/ -v --tb=short")
    checks &= (ret == 0)

    # 4. Lint（可选 PyLint）
    print("=" * 60)
    print("4/4 代码检查")
    try:
        import pylint
        ret = run(f"{sys.executable} -m pylint agent/ --exit-zero")
    except ImportError:
        print("（跳过，pylint 未安装）")
    checks &= (ret == 0)

    if checks:
        print("\n✓ 所有检查通过！")
    else:
        print("\n✗ 存在未通过的检查")
        sys.exit(1)


if __name__ == "__main__":
    main()
