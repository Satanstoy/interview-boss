"""check_secrets.py 门禁脚本测试 — tech-audit-2026-08-13 D8-2。

验证脚本能检出硬编码 API key 字面量（阻断门禁），干净文件放行。
"""
import importlib.util
import os

import pytest

# check_secrets.py 在 backend/scripts/（check_* 运维脚本规范位置，与 test 容器挂载一致）
_script_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts",
    "check_secrets.py",
)
_spec = importlib.util.spec_from_file_location("check_secrets", _script_path)
checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker)


class TestCheckSecrets:
    """secret 扫描脚本行为"""

    def test_api_key_literal_detected(self, tmp_path):
        """sk- 开头 20+ 位字面量必须被检出"""
        f = tmp_path / "leak.py"
        # 分段拼接构造完整 key，避免仓库内出现完整可复制 key 字面量；
        # 扫描器仍能检出该形态（sk- 前缀 + 20+ 位），断言语义不变。
        leaked = "sk-" + "hkaopkqmnstcess" + "lqwxifjiqdffg" + "bpljrixgyssagv" + "gtclym"
        f.write_text(f'KEY = "{leaked}"\n', encoding="utf-8")
        findings = checker.scan_file(f, f.relative_to(tmp_path))
        assert findings, "应检出硬编码 API key"

    def test_clean_file_no_findings(self, tmp_path):
        """无密钥的普通源码不应误报"""
        f = tmp_path / "clean.py"
        f.write_text('print("hello")\\nAPI_KEY = os.environ.get("X", "")\\n', encoding="utf-8")
        findings = checker.scan_file(f, f.relative_to(tmp_path))
        assert findings == []

    def test_env_placeholder_not_flagged_as_assignment(self, tmp_path):
        """API_KEY = os.environ.get(...) / 空串占位不是密钥字面量"""
        f = tmp_path / "cfg.py"
        f.write_text('KEY = ""\\nTOKEN = os.getenv("T")\\n', encoding="utf-8")
        findings = checker.scan_file(f, f.relative_to(tmp_path))
        assert findings == []

    def test_excluded_env_file_skipped(self, tmp_path):
        """.env 文件在排除名单，不应被扫出（避免把真实本地密钥当失败）"""
        (tmp_path / ".env").write_text(
            "OPENAI_API_KEY=sk-real-local-key-0123456789abcdef\\n",
            encoding="utf-8",
        )
        # iter_source_files 基于 PROJECT_ROOT 扫描，此处验证排除规则本身
        assert ".env" in checker.EXCLUDE_NAMES

    def test_main_returns_zero_on_clean_repo(self):
        """对当前仓库运行 main() 应返回 0（已无硬编码密钥）"""
        rc = checker.main()
        assert rc == 0, "当前仓库不应有硬编码密钥（D4-1 修复后）"

    def test_iter_source_files_not_empty(self):
        """迭代器必须产出真实源码文件（回归：排除过滤器恒真短路曾导致产出 0 文件，
        secret 扫描静默失效——tech-audit-2026-08-14 D4）"""
        files = list(checker.iter_source_files())
        assert len(files) > 100, (
            f"iter_source_files 仅产出 {len(files)} 个文件，排除过滤可能短路，"
            "secret 扫描实际未扫描任何文件"
        )
        # 抽查确认为真实源码路径：backend/ 必有覆盖。
        # 注意：test-runtime 容器只挂载 ./backend（frontend 不在容器内），
        # 宿主机运行时才可能覆盖 frontend/——这里只做强约束 backend。
        rels = {str(rel) for _, rel in files}
        assert any(r.startswith("backend/") for r in rels), "应扫描到 backend 源码"
