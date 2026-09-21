#!/usr/bin/env pwsh
# 校验四处版本号一致：
#   VERSION
#   desktop/package.json
#   desktop/src-tauri/Cargo.toml
#   desktop/src-tauri/tauri.conf.json
#
# README「打包 Windows 可执行文件」一节要求发布前四处同步。漏改任何一处都不会报错，
# 但会让安装包版本（tauri.conf.json）、Rust crate 版本（Cargo.toml）与仓库记录对不上，
# 只有在出问题倒查时才暴露。所以在这里硬拦一道。
#
# 用法：pwsh -File desktop/scripts/verify-versions.ps1
# 退出码：0 = 四处一致；1 = 不一致或无法解析。

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path

function Get-JsonFileVersion([string]$relativePath) {
    $fullPath = Join-Path $repoRoot $relativePath
    if (-not (Test-Path $fullPath)) {
        throw "找不到文件：$relativePath"
    }
    return (Get-Content -Raw $fullPath | ConvertFrom-Json).version
}

$versions = [ordered]@{}
$versions["VERSION"] = (Get-Content -Raw (Join-Path $repoRoot "VERSION")).Trim()
$versions["desktop/package.json"] = Get-JsonFileVersion "desktop/package.json"
$versions["desktop/src-tauri/tauri.conf.json"] = Get-JsonFileVersion "desktop/src-tauri/tauri.conf.json"

# Cargo.toml 不是 JSON，取 [package] 段的行首 version（依赖项的 version 不在行首，不会误匹配）
$cargoPath = Join-Path $repoRoot "desktop/src-tauri/Cargo.toml"
$cargoMatch = Select-String -Path $cargoPath -Pattern '^\s*version\s*=\s*"([^"]+)"' -List
if (-not $cargoMatch) {
    throw "无法从 desktop/src-tauri/Cargo.toml 解析出版本号"
}
$versions["desktop/src-tauri/Cargo.toml"] = $cargoMatch.Matches[0].Groups[1].Value

$reference = $versions["desktop/src-tauri/tauri.conf.json"]

Write-Output "当前版本号："
foreach ($entry in $versions.GetEnumerator()) {
    Write-Output ("  {0,-32} {1}" -f $entry.Key, $entry.Value)
}

$mismatched = @($versions.GetEnumerator() | Where-Object { $_.Value -ne $reference })
if ($mismatched.Count -gt 0) {
    Write-Output ""
    Write-Output "版本号不一致，请把上面四处改成同一个值（当前基准 tauri.conf.json = $reference）"
    exit 1
}

Write-Output ""
Write-Output "四处版本号一致：$reference"
exit 0
