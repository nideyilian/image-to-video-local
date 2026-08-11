param(
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$desktopRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $PythonPath) {
    $PythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python 环境不存在: $PythonPath"
}

& $PythonPath -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "请先安装 PyInstaller: $PythonPath -m pip install pyinstaller"
}

Push-Location $projectRoot
try {
    & $PythonPath -m PyInstaller --clean --noconfirm engine_sidecar.spec
    if ($LASTEXITCODE -ne 0) { throw "Python 引擎打包失败" }

    $hostLine = (& rustc -vV | Select-String "^host:").Line
    if (-not $hostLine) { throw "无法读取 Rust target triple" }
    $targetTriple = $hostLine.Substring(5).Trim()
    $source = Join-Path $projectRoot "dist\image-to-video-engine.exe"
    $binaryDir = Join-Path $desktopRoot "src-tauri\binaries"
    $destination = Join-Path $binaryDir "image-to-video-engine-$targetTriple.exe"
    New-Item -ItemType Directory -Force -Path $binaryDir | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Force
    Write-Output $destination
}
finally {
    Pop-Location
}
