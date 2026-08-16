# 将 GitHub Release 的更新文件（latest.json + NSIS 安装包）同步到 Gitee 仓库的 release/ 目录，
# 并把 latest.json 中的 url 改写为 Gitee 直链，供国内用户直接使用。
#
# 说明：
#   - 更新包签名只覆盖安装包内容、不涉及 url 字段，因此改写 url 是安全的。
#   - Gitee 仓库需要预先创建（可为空仓库），例如 owner/image-to-video-local-releases。
#   - 默认推送到 main 分支，Gitee raw 直链格式：
#       https://gitee.com/{owner}/{repo}/raw/main/release/{文件名}
#
# 用法：
#   ./desktop/scripts/sync-gitee.ps1 -Version "3.0.0-local.9" -GiteeRepo "owner/image-to-video-local-releases" -GiteeToken "<access_token>"
# 可选环境变量：GITHUB_TOKEN（读取 GitHub Release 资产时鉴权，Actions 中自动可用）

param(
  [Parameter(Mandatory = $true)][string]$Version,
  [Parameter(Mandatory = $false)][string]$GiteeRepo = "",
  [Parameter(Mandatory = $false)][string]$GiteeToken = "",
  [string]$WorkDir = "$env:TEMP\gitee-sync-$PID"
)

$ErrorActionPreference = "Stop"

if (-not $GiteeRepo -or -not $GiteeToken) {
  Write-Host "未配置 GITEE_REPO / GITEE_TOKEN，跳过 Gitee 镜像同步（可选功能）。"
  exit 0
}

$owner, $repoName = $GiteeRepo.Split("/", 2)
if (-not $repoName) { throw "GiteeRepo 格式应为 owner/repo" }

$github = "https://github.com/nideyilian/image-to-video-local"
$api = "https://api.github.com/repos/nideyilian/image-to-video-local/releases/tags/v$Version"
$headers = @{ "User-Agent" = "image-to-video-gitee-sync" }
if ($env:GITHUB_TOKEN) { $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN" }

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

Write-Host "==> 读取 GitHub Release v$Version 元数据"
$release = Invoke-RestMethod -Uri $api -Headers $headers -TimeoutSec 60
$latestJsonAsset = $release.assets | Where-Object { $_.name -eq "latest.json" } | Select-Object -First 1
if (-not $latestJsonAsset) { throw "未在 Release v$Version 中找到 latest.json" }

Write-Host "==> 下载 latest.json"
$latestPath = Join-Path $WorkDir "latest.json"
Invoke-WebRequest -Uri $latestJsonAsset.browser_download_url -Headers $headers -OutFile $latestPath -TimeoutSec 120

$manifest = Get-Content -Raw $latestPath | ConvertFrom-Json
if (-not $manifest.url) { throw "latest.json 中缺少 url 字段" }

$installerName = [System.IO.Path]::GetFileName([Uri]::UnescapeDataString($manifest.url))
Write-Host "==> 下载安装包 $installerName"
$installerPath = Join-Path $WorkDir $installerName
Invoke-WebRequest -Uri $manifest.url -Headers $headers -OutFile $installerPath -TimeoutSec 600

# 改写 url 为 Gitee raw 直链（中文文件名做百分号编码）
$encodedName = [Uri]::EscapeDataString($installerName)
$manifest.url = "https://gitee.com/$GiteeRepo/raw/main/release/$encodedName"
$jsonText = $manifest | ConvertTo-Json -Depth 10
[System.IO.File]::WriteAllText($latestPath, $jsonText, [System.Text.UTF8Encoding]::new($false))

Write-Host "==> 同步到 Gitee 仓库 $GiteeRepo"
$cloneDir = Join-Path $WorkDir "gitee-repo"
$authUrl = "https://oauth2:$GiteeToken@gitee.com/$GiteeRepo.git"
git clone --depth 1 $authUrl $cloneDir 2>$null
if ($LASTEXITCODE -ne 0 -or -not (Test-Path (Join-Path $cloneDir ".git"))) {
  Write-Host "    Gitee 仓库为空或克隆失败，尝试本地初始化（请确认仓库已创建且允许推送）"
  New-Item -ItemType Directory -Force -Path $cloneDir | Out-Null
  git -C $cloneDir init 2>$null
  git -C $cloneDir remote remove origin 2>$null
  git -C $cloneDir remote add origin $authUrl
}

$releaseDir = Join-Path $cloneDir "release"
New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
Copy-Item $latestPath $releaseDir -Force
Copy-Item $installerPath $releaseDir -Force

git -C $cloneDir config user.name "image-to-video gitee sync"
git -C $cloneDir config user.email "image-to-video-gitee-sync@users.noreply.github.com"
git -C $cloneDir add release 2>$null
git -C $cloneDir commit -m "同步 v$Version 更新文件到 Gitee 镜像" 2>$null
$branch = git -C $cloneDir symbolic-ref --short HEAD
git -C $cloneDir push origin "HEAD:$branch"
if ($LASTEXITCODE -ne 0) { throw "推送 Gitee 失败，请检查仓库与令牌权限" }

Write-Host "==> 完成：https://gitee.com/$GiteeRepo/raw/main/release/latest.json"
