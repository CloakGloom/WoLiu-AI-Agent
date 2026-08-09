"""工具系统单元测试"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_tools_list():
    """测试工具列表不为空"""
    from agent.tools import TOOLS_FOR_LLM, _EXECUTORS
    assert len(TOOLS_FOR_LLM) > 0, "工具列表不应为空"
    assert len(_EXECUTORS) > 0, "执行器映射不应为空"
    print(f"  [PASS] test_tools_list: {len(TOOLS_FOR_LLM)} 个工具, {len(_EXECUTORS)} 个执行器")


def test_builtin_tools():
    """测试内置工具可导入"""
    from agent.tools.builtin import datetime_tool, weather, calculator, migrate, status
    all_modules = [datetime_tool, weather, calculator, migrate, status]
    for mod in all_modules:
        assert hasattr(mod, "SCHEMA"), f"{mod.__name__} 缺少 SCHEMA"
        assert hasattr(mod, "execute"), f"{mod.__name__} 缺少 execute"
    print("  [PASS] test_builtin_tools: 5 个内置工具全部可导入")


def test_hardware_tools():
    """测试硬件工具可导入"""
    from agent.tools.hardware.pc import microphone as pc_mic
    from agent.tools.hardware.pc import speaker as pc_spk
    from agent.tools.hardware.pc import camera as pc_cam
    from agent.tools.hardware.phone import microphone as phone_mic
    from agent.tools.hardware.phone import speaker as phone_spk
    from agent.tools.hardware.phone import camera as phone_cam

    # 测试 PC 端实现
    result = pc_mic.PcMicrophone().record(3)
    assert "电脑" in result
    result = pc_spk.PcSpeaker().play("测试")
    assert "电脑" in result
    result = pc_cam.PcCamera().capture()
    assert "电脑" in result

    # 测试手机端实现
    result = phone_mic.PhoneMicrophone().record(3)
    assert "手机" in result
    result = phone_spk.PhoneSpeaker().play("测试")
    assert "手机" in result
    result = phone_cam.PhoneCamera().capture()
    assert "手机" in result

    print("  [PASS] test_hardware_tools: 6 个硬件实现全部可调用")


def test_tool_execution():
    """测试工具执行入口"""
    from agent.tools import execute_tool, set_current_device
    from config import DEVICE_PC, DEVICE_MOBILE

    # 测试 PC 端硬件
    set_current_device(DEVICE_PC)
    result = execute_tool("use_microphone", {"duration": 5})
    assert "电脑" in result
    result = execute_tool("use_camera", {})
    assert "电脑" in result

    # 测试手机端硬件
    set_current_device(DEVICE_MOBILE)
    result = execute_tool("use_microphone", {"duration": 5})
    assert "手机" in result
    result = execute_tool("use_camera", {})
    assert "手机" in result

    print("  [PASS] test_tool_execution: 设备切换正常")


if __name__ == "__main__":
    test_tools_list()
    test_builtin_tools()
    test_hardware_tools()
    test_tool_execution()
    print("\ntools 测试全部通过!")