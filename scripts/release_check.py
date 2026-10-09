#!/usr/bin/env python3
"""发布前敏感信息检查（宪法第 VI 条 / tasks.md T014）。

扫描仓库中被版本控制的文本文件，找出疑似泄漏的：
- 完整信用卡号（含 Luhn 校验，降低误报）
- OpenAI / 通用 API key
- 带真实口令的代理 URL
- JWT / 长 session token
- 云厂商密钥

用法::

    python scripts/release_check.py [--root .] [--quiet]

发现可疑内容时返回退出码 1。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

SKIP_DIR_PREFIXES = (
    ".git/",
    "node_modules/",
    ".venv/",
    "dist/",
    "__pycache__/",
    ".reasonix/",
    ".uv-tools/",
    ".uv-bin/",
)
TEXT_SUFFIXES = {
    ".py", ".md", ".json", ".yaml", ".yml", ".toml", ".txt", ".env", ".cfg", ".ini",
    ".ts", ".tsx", ".js", ".jsx", ".sh", ".ps1", ".sql", ".example",
}

#: 占位符白名单（示例配置里的假值不应报警）。
PLACEHOLDER_HINTS = (
    "example", "placeholder", "xxx", "your-", "fake", "dummy", "<", "***",
    "changeme", "todo", "sk-xxxx",
)

#: 显式豁免标记：行内出现该注释即跳过（仅用于测试中的公开假数据）。
IGNORE_MARKER = "release-check: ignore"

_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9._-]{30,}\b")),
    ("proxy_credentials", re.compile(r"https?://[^:/\s@]{1,64}:[^@/\s]{6,}@")),
    ("card_number_candidate", re.compile(r"\b(?:\d[ -]?){15,16}\b")),
]


def luhn_ok(number: str) -> bool:
    """Luhn 校验，过滤掉大多数非卡号数字串。"""

    digits = [int(c) for c in number if c.isdigit()]
    if not (13 <= len(digits) <= 19):
        return False
    total = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _is_placeholder(line: str) -> bool:
    lowered = line.lower()
    return IGNORE_MARKER in lowered or any(hint in lowered for hint in PLACEHOLDER_HINTS)


def _tracked_files(root: Path) -> List[Path]:
    """优先用 git 跟踪列表；不是 git 仓库时退回遍历目录。"""

    try:
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        files = [root / line for line in out.splitlines() if line.strip()]
        if files:
            return files
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return [
        p
        for p in root.rglob("*")
        if p.is_file()
        and not any(str(p.relative_to(root)).startswith(pref) for pref in SKIP_DIR_PREFIXES)
    ]


def _iter_findings(root: Path) -> Iterable[Tuple[Path, int, str, str]]:
    for path in _tracked_files(root):
        rel = path.relative_to(root).as_posix()
        if any(rel.startswith(pref) for pref in SKIP_DIR_PREFIXES):
            continue
        suffix = path.suffix.lower()
        if suffix and suffix not in TEXT_SUFFIXES and path.name != ".env.example":
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _is_placeholder(line):
                continue
            for kind, pattern in _PATTERNS:
                for match in pattern.finditer(line):
                    value = match.group(0)
                    if kind == "card_number_candidate" and not luhn_ok(value):
                        continue
                    yield path, lineno, kind, value


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="发布前敏感信息检查")
    parser.add_argument("--root", default=".", help="仓库根目录")
    parser.add_argument("--quiet", action="store_true", help="只输出结论")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    findings = list(_iter_findings(root))

    if not findings:
        print("release_check: OK — 未发现敏感信息")
        return 0

    print(f"release_check: 发现 {len(findings)} 处疑似敏感信息")
    for path, lineno, kind, value in findings:
        rel = path.relative_to(root).as_posix()
        shown = value if len(value) <= 40 else value[:37] + "..."
        if args.quiet:
            print(f"  {rel}:{lineno} [{kind}]")
        else:
            print(f"  {rel}:{lineno} [{kind}] {shown}")
    print("\n请移除或替换为占位符后重试（宪法第 I 条：凭证零持久化）。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
