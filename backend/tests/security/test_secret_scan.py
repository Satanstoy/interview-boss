"""
安全静态扫描测试 — 防止硬编码密钥/公开占位进入仓库

覆盖 tech-audit-2026-08-13 的 🔴 发现：
- D4-1: SiliconFlow API key 硬编码在 4 个实验脚本
- D13-1: JWT_SECRET 公开占位 ship 进 .env.example
- D13-2: OAUTH_SECRET_KEY 公开兜底值在 docker-compose.yml
"""
import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]

EXPERIMENTS_DIR = PROJECT_ROOT / "backend" / "app" / "services" / "clustering" / "experiments"
ENV_EXAMPLE = PROJECT_ROOT / "backend" / ".env.example"
COMPOSE_FILE = PROJECT_ROOT / "docker-compose.yml"

# 已确认泄露的 SiliconFlow key（tech-audit-2026-08-13 D4-1）
LEAKED_SILICONFLOW_KEY = "REDACTED"


class TestD4NoHardcodedApiKey:
    """D4-1: 实验脚本不得硬编码 API key"""

    def test_eval_scripts_have_no_sk_literal(self):
        """experiments 目录所有 .py 不得出现 sk- 字面量"""
        py_files = sorted(EXPERIMENTS_DIR.glob("*.py"))
        assert py_files, f"未找到实验脚本目录: {EXPERIMENTS_DIR}"
        for py in py_files:
            content = py.read_text(encoding="utf-8")
            assert not re.search(r'sk-[A-Za-z0-9]{20,}', content), (
                f"{py.name} 含硬编码 API key 字面量"
            )

    def test_leaked_key_absent_from_repo_sources(self):
        """已知泄露 key 不得出现在后端源码中（排除 git 历史与 data/）"""
        scanned = 0
        for base in (PROJECT_ROOT / "backend" / "app", PROJECT_ROOT / "scripts"):
            for py in base.rglob("*.py"):
                if "node_modules" in py.parts or "experiment_reports" in py.parts:
                    continue
                scanned += 1
                content = py.read_text(encoding="utf-8", errors="ignore")
                assert LEAKED_SILICONFLOW_KEY not in content, f"{py} 含泄露 key"
        assert scanned > 50, f"扫描范围异常（仅 {scanned} 个文件）"


class TestD13JwtSecretPlaceholder:
    """D13-1: .env.example 不得包含可用的 JWT_SECRET 占位"""

    def test_env_example_jwt_secret_not_active(self):
        """JWT_SECRET 行必须被注释或留空，禁止照抄即用的占位值"""
        content = ENV_EXAMPLE.read_text(encoding="utf-8")
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("JWT_SECRET=") and not stripped.startswith("#"):
                value = stripped.split("=", 1)[1].strip().strip('"').strip("'")
                assert not value, (
                    "JWT_SECRET 不得有非空实值（照抄示例会共享已知签名密钥），"
                    "应注释并说明由系统自动生成"
                )


class TestD13OauthSecretFallback:
    """D13-2: docker-compose.yml 不得有 OAUTH_SECRET_KEY 公开兜底值"""

    def test_compose_no_change_me_fallback(self):
        content = COMPOSE_FILE.read_text(encoding="utf-8")
        assert "change-me-in-production" not in content, (
            "OAUTH_SECRET_KEY 不得带公开兜底值（未设变量的部署令牌可被伪造）"
        )

    def test_compose_oauth_secret_uses_env_only(self):
        """OAUTH_SECRET_KEY 只能从 env 注入，空值时应触发 oauth-gateway 自动生成"""
        for line in COMPOSE_FILE.read_text(encoding="utf-8").splitlines():
            if "OAUTH_SECRET_KEY" in line:
                assert ":-" not in line, f"禁止 shell 默认值语法: {line.strip()}"
