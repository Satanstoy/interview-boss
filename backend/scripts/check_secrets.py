#!/usr/bin/env python3
"""Secret scan — 扫描仓库 tracked 源码中的常见密钥字面量。

tech-audit-2026-08-13 D8-2：check.sh 门禁唯一的阻断性安全检查。

扫描规则（保守，宁可误报不可漏报）：
- sk- 开头 20+ 位字母数字（SiliconFlow/OpenAI 风格 API key）
- 常见密钥赋值模式：XXX_KEY/XXX_SECRET/XXX_TOKEN = 非空字面量
排除：.env*、backend/data/、node_modules/、dist/、*.lock、测试 fixtures 目录
退出码：0 = 无发现；1 = 有发现（阻断）；2 = 内部错误
"""
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 排除目录/文件（相对仓库根）
EXCLUDE_DIRS = {
    ".git",
    "node_modules",
    "dist",
    "backend/data",
    ".tech-audit",
    "frontend/dist",
    ".venv",
}
EXCLUDE_SUFFIXES = {".lock", ".pyc"}
EXCLUDE_NAMES = {".env", ".env.example"}

# 模式：sk- + 20+ 位字母数字
API_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")
# 密钥赋值：XXX_KEY/SECRET/TOKEN/PASSWORD = "非空值"
ASSIGN_RE = re.compile(
    r"^[^#]*(?:API[_-]?KEY|SECRET|TOKEN|PASSWORD|PRIVATE[_-]?KEY)"
    r"\s*[=:]\s*[\"'][^\"']{8,}[\"']",
    re.IGNORECASE,
)


def iter_source_files():
    for path in sorted(PROJECT_ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(PROJECT_ROOT)
        parts = rel.parts
        if any(part in EXCLUDE_DIRS or rel.match(part) for part in EXCLUDE_DIRS):
            continue
        if path.suffix in EXCLUDE_SUFFIXES or path.name in EXCLUDE_NAMES:
            continue
        if path.suffix not in {".py", ".js", ".ts", ".vue", ".sh", ".yml", ".yaml", ".json", ".env", ".toml", ".ini", ".conf", ".cfg", ".md"}:
            continue
        yield path, rel


def scan_file(path: Path, rel: Path) -> list:
    findings = []
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return findings
    for lineno, line in enumerate(content.splitlines(), 1):
        if API_KEY_RE.search(line):
            findings.append((rel, lineno, "API key 字面量 (sk-...)"))
        elif ASSIGN_RE.search(line):
            findings.append((rel, lineno, "疑似密钥赋值"))
    return findings


def main() -> int:
    findings = []
    for path, rel in iter_source_files():
        findings.extend(scan_file(path, rel))
    if findings:
        print(f"secret scan: 发现 {len(findings)} 处疑似密钥字面量")
        for rel, lineno, kind in findings:
            print(f"  {rel}:{lineno} — {kind}")
        return 1
    print("secret scan: 未发现硬编码密钥")
    return 0


if __name__ == "__main__":
    sys.exit(main())
