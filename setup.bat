@echo off
setlocal enabledelayedexpansion
title WoLiu AI Agent 一键安装

echo ========================================
echo   WoLiu AI Agent — 环境检测与安装
echo ========================================
echo.

cd /d "%~dp0"

:: ──────────────────────────────────────
:: 检查 Python
:: ──────────────────────────────────────
echo [1/5] 检查 Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   [ERROR] 未找到 Python，请先安装 Python 3.11+
    echo   下载: https://www.python.org/downloads/
    pause & exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo   [OK] Python %%v

:: ──────────────────────────────────────
:: 创建虚拟环境
:: ──────────────────────────────────────
echo.
echo [2/5] 配置虚拟环境...

if exist .venv\Scripts\python.exe (
    echo   [OK] .venv 已存在，跳过创建
) else (
    echo   正在创建 .venv ...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo   [ERROR] 虚拟环境创建失败
        pause & exit /b 1
    )
    echo   [OK] .venv 已创建
)

call .venv\Scripts\activate.bat
echo   [OK] 虚拟环境已激活

:: ──────────────────────────────────────
:: 安装 Python 依赖
:: ──────────────────────────────────────
echo.
echo [3/5] 安装 Python 依赖...
python -m pip install --upgrade pip -q 2>nul

if exist requirements.txt (
    pip install -r requirements.txt -q
    if %errorlevel% neq 0 (
        echo   [WARN] 部分依赖安装失败，尝试单独安装...
        pip install -r requirements.txt
    ) else (
        echo   [OK] requirements.txt 安装完成
    )
)

:: 补充依赖
echo   安装 edge-tts ^(语音合成^)...
pip install edge-tts -q 2>nul
if %errorlevel% neq 0 (
    echo   [WARN] edge-tts 安装失败，提醒功能将无语音
) else (
    echo   [OK] edge-tts 已安装
)

echo   安装 modelscope ^(魔搭下载^)...
pip install modelscope -q 2>nul
if %errorlevel% neq 0 (
    echo   [WARN] modelscope 安装失败，模型下载功能受影响
) else (
    echo   [OK] modelscope 已安装
)

:: ──────────────────────────────────────
:: Node.js + agent-browser
:: ──────────────────────────────────────
echo.
echo [4/5] 检查 Node.js ^& 前端工具...

node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   [SKIP] 未找到 Node.js — 浏览器自动化不可用
    echo         安装: https://nodejs.org/
) else (
    for /f "tokens=1" %%v in ('node --version 2^>^&1') do echo   [OK] Node.js %%v
    npm --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo   [WARN] npm 不可用
    ) else (
        if exist node_modules\.bin\agent-browser.cmd (
            echo   [OK] agent-browser 已安装
        ) else (
            echo   安装 agent-browser ^(浏览器自动化^)...
            call npm install agent-browser --save 2>nul
            if %errorlevel% equ 0 (
                echo   [OK] agent-browser 安装完成
            ) else (
                echo   [WARN] agent-browser 安装失败
            )
        )
    )
)

:: ──────────────────────────────────────
:: 创建默认配置
:: ──────────────────────────────────────
echo.
echo [5/5] 检查配置...

if not exist .env (
    echo   创建 .env 模板...
    (
        echo # WoLiu AI Agent 环境变量
        echo # 在设置页 UI 填写或直接编辑此文件
        echo LLM_API_KEY=
        echo VISION_API_KEY=
        echo TTS_API_KEY=
        echo SEARCH_API_KEY=
    ) > .env
    echo   [OK] .env 模板已创建
) else (
    echo   [OK] .env 已存在
)

if not exist config\settings.json (
    echo   创建 settings.json 默认配置...
    python -c "from server.settings_manager import _ensure_file; _ensure_file()" 2>nul
    echo   [OK] 默认配置已生成
) else (
    echo   [OK] settings.json 已存在
)

:: ──────────────────────────────────────
:: 运行环境检测
:: ──────────────────────────────────────
echo.
echo ========================================
echo   环境检测
echo ========================================
python scripts\check_env.py 2>nul
if %errorlevel% neq 0 (
    echo [WARN] check_env.py 未找到，跳过自检
) else (
    echo [OK] 环境检测完成
)

:: ──────────────────────────────────────
:: 完成
:: ──────────────────────────────────────
echo.
echo ========================================
echo   安装完成！
echo ========================================
echo.
echo   启动方式：
echo     方式 1 ^(推荐^): 双击 run_server.py
echo     方式 2: 终端运行 .venv\Scripts\python run_server.py
echo     方式 3: 终端运行 .venv\Scripts\activate ^& python run_server.py
echo.
echo   首次使用请在设置页填写 LLM API Key
echo   或直接编辑 .env 文件
echo.
pause
