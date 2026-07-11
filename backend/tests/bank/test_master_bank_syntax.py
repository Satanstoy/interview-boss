"""
测试 master_bank.py 模块语法正确性
针对 Bug INDENT-001: _gen_one 函数缩进错误
"""

import ast
import pytest
import sys
from pathlib import Path


def _find_backend_root(start: Path) -> Path:
    """Return the backend directory containing app/ and tests/."""
    for candidate in (start, *start.parents):
        if (candidate / "app" / "routers").is_dir() and (candidate / "tests").is_dir():
            return candidate
    raise RuntimeError(f"Could not locate backend root from {start}")


BACKEND_ROOT = _find_backend_root(Path(__file__).resolve())


class TestMasterBankSyntax:
    """测试 master_bank.py 的 Python 语法正确性"""

    MODULE_PATH = BACKEND_ROOT / "app" / "routers" / "questions.py"
    ANSWERS_PATH = BACKEND_ROOT / "app" / "routers" / "answers.py"

    def test_file_syntax_valid(self):
        """验证 master_bank.py 文件语法正确"""
        with open(self.MODULE_PATH, "r") as f:
            source = f.read()
        # ast.parse 会在语法错误时抛出 SyntaxError
        ast.parse(source)

    def test_gen_one_function_syntax(self):
        """验证 _gen_one 函数的语法正确性"""
        with open(self.ANSWERS_PATH, "r") as f:
            source = f.read()

        tree = ast.parse(source)

        # 查找 _gen_one 函数定义
        gen_one_func = None
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_gen_one":
                gen_one_func = node
                break

        assert gen_one_func is not None, "_gen_one 函数未找到"

        # 验证函数有函数体
        assert len(gen_one_func.body) > 0, "_gen_one 函数体为空"

        # 验证第一行是 nonlocal 语句
        first_stmt = gen_one_func.body[0]
        assert isinstance(first_stmt, ast.Nonlocal), (
            f"_gen_one 函数第一行应该是 nonlocal 语句，实际是 {type(first_stmt).__name__}"
        )

    def test_import_module(self):
        """验证模块可以正常导入"""
        # 添加 backend 目录到 Python 路径
        backend_dir = BACKEND_ROOT
        if str(backend_dir) not in sys.path:
            sys.path.insert(0, str(backend_dir))

        # 尝试导入模块
        try:
            import app.routers.questions
        except IndentationError as e:
            pytest.fail(f"questions.py 存在缩进错误: {e}")
        except ImportError as e:
            # 导入错误可能是依赖问题，不是语法问题
            pytest.fail(
                f"导入失败（Docker test-runtime 应包含全部依赖，导入失败几乎一定是代码问题）: {e}",
                pytrace=True,
            )
        except Exception as e:
            pytest.fail(f"导入 questions.py 时发生意外错误: {e}")


class TestBackendStartup:
    """测试后端服务能否正常启动"""

    def test_asgi_module_importable(self):
        """验证 asgi 模块可以正常导入"""
        backend_dir = BACKEND_ROOT
        if str(backend_dir) not in sys.path:
            sys.path.insert(0, str(backend_dir))

        try:
            import app.asgi
        except IndentationError as e:
            pytest.fail(f"asgi.py 或其依赖存在缩进错误: {e}")
        except ImportError as e:
            pytest.fail(
                f"导入失败（Docker test-runtime 应包含全部依赖，导入失败几乎一定是代码问题）: {e}",
                pytrace=True,
            )
        except Exception as e:
            pytest.fail(f"导入 asgi.py 时发生意外错误: {e}")

    def test_all_routers_importable(self):
        """验证所有路由模块可以正常导入"""
        backend_dir = BACKEND_ROOT
        if str(backend_dir) not in sys.path:
            sys.path.insert(0, str(backend_dir))

        routers = [
            "app.routers.auth",
            "app.routers.submit",
            "app.routers.data",
            "app.routers.questions",
            "app.routers.answers",
            "app.routers.practice",
            "app.routers.admin_review",
            "app.routers.bank_build",
            "app.routers.interview",
            "app.routers.analytics",
            "app.routers.profile",
            "app.routers.health",
        ]

        failures: list[str] = []
        for router_name in routers:
            try:
                __import__(router_name)
            except IndentationError as e:
                failures.append(f"{router_name} 缩进错误: {e}")
            except ImportError as e:
                failures.append(
                    f"{router_name} 导入失败（Docker test-runtime 含全部依赖，几乎一定是代码问题）: {e}"
                )
            except Exception as e:
                failures.append(f"{router_name} 意外错误: {e}")
        assert not failures, "\n".join(failures)
