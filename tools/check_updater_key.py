# -*- coding: utf-8 -*-
"""核对自动更新的签名密钥是否配对。

Tauri 更新时用「应用内置的公钥」验证「安装包签名」，两者必须是同一对密钥。
仓库里只改了公钥、没换 GitHub 上的签名私钥，就会导致所有用户的自动更新
报「安装包签名校验失败」—— 而且每版都失败、重试也没用。

本脚本做三件事：
1. 读出 tauri.conf.json 里配置的公钥 keyid；
2. 扫描项目根目录下的 minisign 密钥文件（*.pub / 无后缀私钥），列出各自 keyid，
   指出配置的公钥在本机有没有配对的私钥；
3. 联网比对 GitHub 上最新 Release 的 latest.json 签名 keyid ——
   这一项是硬证据：能直接看出 CI 实际拿哪把私钥签的名。

用法：
    python tools/check_updater_key.py
    python tools/check_updater_key.py --offline   # 跳过联网检查
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONF = ROOT / "desktop" / "src-tauri" / "tauri.conf.json"
REPO = "nideyilian/image-to-video-local"


def _keyid_from_public_key(pubkey_b64: str) -> str:
    """公钥（base64 后的 minisign 文本）→ keyid。"""
    text = base64.b64decode(pubkey_b64).decode("utf-8")
    comment = text.splitlines()[0]
    return comment.rsplit(":", 1)[-1].strip()


def _keyid_from_sig_file(path: Path) -> str | None:
    """Tauri 导出的 .sig（整体 base64）→ 签名 keyid。"""
    try:
        inner = base64.b64decode(path.read_text(encoding="utf-8").strip()).decode("utf-8")
        lines = [line for line in inner.splitlines() if line.strip()]
        return base64.b64decode(lines[1])[2:10][::-1].hex().upper()
    except Exception:
        return None


def _keyid_from_secret_key(path: Path) -> str | None:
    """minisign 加密私钥 → keyid。

    私钥二进制结构在不同实现里字段偏移有差异，直接猜偏移容易给出**错误但看似合理**的
    keyid。所以这里只在解析结果能与同名 ``.pub`` 对上时才返回，否则宁可说"未能确认"。
    """
    try:
        inner = base64.b64decode(path.read_text(encoding="utf-8").strip()).decode("utf-8")
        lines = [line for line in inner.splitlines() if line.strip()]
        raw = base64.b64decode(lines[1])
    except Exception:
        return None

    pub = Path(str(path) + ".pub")
    if not pub.is_file():
        return None
    try:
        expected = _keyid_from_public_key(pub.read_text(encoding="utf-8").strip())
    except Exception:
        return None

    candidates = [raw[offset:offset + 8][::-1].hex().upper() for offset in (6, 2, 10)]
    return expected if expected in candidates else None


def main() -> int:
    offline = "--offline" in sys.argv
    config = json.loads(CONF.read_text(encoding="utf-8"))
    configured = _keyid_from_public_key(config["plugins"]["updater"]["pubkey"])
    print(f"配置的公钥 keyid      : {configured}")

    print("\n本机密钥文件：")
    paired: list[str] = []
    for path in sorted(ROOT.glob("_updater*")):
        if path.suffix == ".pub":
            keyid = _keyid_from_public_key(path.read_text(encoding="utf-8").strip())
            kind = "公钥"
        else:
            keyid = _keyid_from_secret_key(path)
            kind = "私钥"
        shown = keyid or "（未能确认，见同名 .pub）"
        mark = "  ← 与配置配对" if keyid == configured else ""
        if keyid == configured:
            paired.append(path.name)
        print(f"  {path.name:<26} {kind}  {shown}{mark}")

    print()
    if paired:
        print(f"本机存在配对密钥：{'、'.join(paired)}")
        print("  ⚠️ 这只是必要条件 —— GitHub 上的 TAURI_SIGNING_PRIVATE_KEY 必须也是同一把。")
    else:
        print("❌ 本机没有与配置公钥配对的私钥。")

    if offline:
        return 0

    print("\n已发布产物的签名（GitHub 最新 Release）：")
    url = f"https://github.com/{REPO}/releases/latest/download/latest.json"
    proc = subprocess.run(
        ["curl", "-sL", "--ssl-no-revoke", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        data = json.loads(proc.stdout)
    except Exception:
        print("  取不到 latest.json（离线或网络受限），跳过")
        return 0

    version = data.get("version", "?")
    platforms = data.get("platforms") or {}
    print(f"  最新版本：{version}")
    bad = 0
    for name, item in platforms.items():
        sig = item.get("signature", "")
        try:
            inner = base64.b64decode(sig).decode("utf-8")
            lines = [line for line in inner.splitlines() if line.strip()]
            keyid = base64.b64decode(lines[1])[2:10][::-1].hex().upper()
        except Exception:
            keyid = "解析失败"
        verdict = "配对 ✓" if keyid == configured else "不配对 ✗"
        if keyid != configured:
            bad += 1
        print(f"    {name:<20} 签名 keyid = {keyid}  {verdict}")

    if bad:
        print("\n❌ 已发布的安装包不是用「配置公钥对应的私钥」签名的 —— 用户点自动更新会报签名校验失败：")
        print("   要么 GitHub 上的 TAURI_SIGNING_PRIVATE_KEY 换成了对应的私钥，")
        print("   要么把这里的公钥改回与 CI 私钥配对的那把。")
        return 1
    print("\n✅ 配置公钥与已发布产物的签名配对。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
