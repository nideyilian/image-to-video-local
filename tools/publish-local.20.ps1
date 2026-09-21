# 发布 v3.0.0-local.20 到 GitHub Release
# 用法: 设置 $env:GH_TOKEN 后运行本脚本
$ErrorActionPreference = "Stop"

$relDir = "D:\AAA\image-to-video\releases\3.0.0-local.20"
$tag = "v3.0.0-local.20"
$repo = "nideyilian/image-to-video-local"
$installer = "图转视频极速版_3.0.0-local.20_x64-setup.exe"
$latestJson = "latest.json"

# 走 clash 代理访问 GitHub
$env:HTTPS_PROXY = "http://127.0.0.1:7897"
$env:HTTP_PROXY = "http://127.0.0.1:7897"

if (-not $env:GH_TOKEN) {
  Write-Error "请先设置 \$env:GH_TOKEN"
  exit 1
}

Push-Location $relDir
try {
  Write-Host "==> 创建 Release $tag (draft)"
  gh release create $tag `
    --repo $repo `
    --title "图转视频极速版 v3.0.0-local.20" `
    --draft `
    "$installer" `
    "$installer.sig" `
    "$latestJson"
  if ($LASTEXITCODE -ne 0) { throw "gh release create 失败" }
  Write-Host "==> Release 已创建（草稿）"
}
finally {
  Pop-Location
}
