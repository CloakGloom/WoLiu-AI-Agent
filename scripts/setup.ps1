# 安装脚本（Windows PowerShell）
# 自动检测并安装 AI Agent 所需的外部依赖

param(
    [switch]$CheckOnly  # 仅检查，不安装
)

$ErrorActionPreference = "Continue"
Write-Host "=== AI Agent 环境检测 ===" -ForegroundColor Cyan

$OK = "✓" ; $FAIL = "✗" ; $WARN = "⚠"

function Test-Command($cmd) {
    $r = Get-Command $cmd -ErrorAction SilentlyContinue
    return $r -ne $null
}

function Test-Dir($path) {
    return Test-Path $path -PathType Container
}

function Test-File($path) {
    return Test-Path $path -PathType Leaf
}


# ── Python ──
Write-Host "`n[Python]" -ForegroundColor Yellow
if (Test-Command python) {
    $ver = python --version 2>&1
    Write-Host "  $OK  Python: $ver"
} else {
    Write-Host "  $FAIL  Python 未安装"
    Write-Host "       → 安装: winget install Python.Python.3.12"
}

# ── ffmpeg ──
Write-Host "`n[ffmpeg]" -ForegroundColor Yellow
if (Test-Command ffmpeg) {
    Write-Host "  $OK  ffmpeg 可用"
} else {
    Write-Host "  $WARN  ffmpeg 未找到（某些功能需要）"
    Write-Host "       → winget install Gyan.FFmpeg"
}

# ── ComfyUI ──
Write-Host "`n[ComfyUI]" -ForegroundColor Yellow
$cfy = "side-projects/ComfyUI_windows_portable/ComfyUI"
if (Test-Dir $cfy) {
    Write-Host "  $OK  ComfyUI 安装目录: $cfy"
} else {
    Write-Host "  $WARN  ComfyUI 未安装（需手动放置）"
}

# ── Git ──
Write-Host "`n[Git]" -ForegroundColor Yellow
if (Test-Command git) {
    $v = git --version 2>&1
    Write-Host "  $OK  $v"
} else {
    Write-Host "  $FAIL  Git 未安装"
    Write-Host "       → winget install Git.Git"
}

# ── Docker ──
Write-Host "`n[Docker]" -ForegroundColor Yellow
if (Test-Command docker) {
    Write-Host "  $OK  Docker 可用（Ollama 可容器化）"
} else {
    Write-Host "  $WARN  Docker 未安装（可选，用于 Ollama 等外部服务）"
}

Write-Host "`n=== 检测完成 ===" -ForegroundColor Cyan

if (-not $CheckOnly) {
    Write-Host "`n安装依赖..." -ForegroundColor Cyan
    pip install -r requirements.txt
    Write-Host "依赖安装完成！" -ForegroundColor Green
}
