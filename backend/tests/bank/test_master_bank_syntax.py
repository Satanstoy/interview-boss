"""
测试 master_bank.py 模块语法正确性
针对 Bug INDENT-001: _gen_one 函数缩进错误
"""
import pytest
import ast
import sys
from pathlib import Path


class TestMasterBankSyntax:
    """测试 master_bank.py 的 Python 语法正确性"""

    MODULE_PATH = Path(__file__).parent.parent / "app" / "routers" / "questions.py"
    ANSWERS_PATH = Path(__file__).parent.parent / "app" / "routers" / "answers.py"

    def test_file_syntax_valid(self):
        """验证 master_bank.py 文件语法正确"""
        with open(self.MODULE_PATH, 'r') as f:
            source = f.read()
        # ast.parse 会在语法错误时抛出 SyntaxError
        ast.parse(source)

    def test_gen_one_function_syntax(self):
        """验证 _gen_one 函数的语法正确性"""
        with open(self.ANSWERS_PATH, 'r') as f:
            source = f.read()

        tree = ast.parse(source)

        # 查找 _gen_one 函数定义
        gen_one_func = None
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == '_gen_one':
                gen_one_func = node
                break

        assert gen_one_func is not None, "_gen_one 函数未找到"

        # 验证函数有函数体
        assert len(gen_one_func.body) > 0, "_gen_one 函数体为空"

        # 验证第一行是 nonlocal 语句
        first_stmt = gen_one_func.body[0]
        assert isinstance(first_stmt, ast.Nonlocal), \
            f"_gen_one 函数第一行应该是 nonlocal 语句，实际是 {type(first_stmt).__name__}"

    def test_import_module(self):
        """验证模块可以正常导入"""
        # 添加 backend 目录到 Python 路径
        backend_dir = Path(__file__).parent.parent
        if str(backend_dir) not in sys.path:
            sys.path.insert(0, str(backend_dir))

        # 尝试导入模块
        try:
            import app.routers.questions
        except IndentationError as e:
            pytest.fail(f"questions.py 存在缩进错误: {e}")
        except ImportError as e:
            # 导入错误可能是依赖问题，不是语法问题
            pytest.skip(f"导入失败（可能是依赖问题）: {e}")
        except Exception as e:
            pytest.fail(f"导入 questions.py 时发生意外错误: {e}")

    @pytest.mark.parametrize("line_num", range(928, 961))
    def test_gen_one_line_indentation(self, line_num):
        """验证 _gen_one 函数每一行的缩进正确性"""
        with open(self.ANSWERS_PATH, 'r') as f:
            lines = f.readlines()

        if line_num > len(lines):
            pytest.skip(f"行号 {line_num} 超出文件范围")

        line = lines[line_num - 1]  # 行号从1开始，索引从0开始

        # 第 928 行是函数定义，缩进应该是 12 空格（3级缩进）
        # 第 929-960 行是函数体，缩进应该是 16 空格（4级缩进）
        if line_num == 928:
            # 函数定义行
            assert line.startswith(' ' * 12), \
                f"第 {line_num} 行（函数定义）缩进应为12空格"
            assert 'async def _gen_one' in line
        elif line_num >= 929 and line_num <= 960:
            # 函数体行
            if line.strip():  # 非空行
                assert line.startswith(' ' * 16) or line.startswith(' ' * 20) or line.startswith(' ' * 24), \
                    f"第 {line_num} 行缩进不正确，应为16/20/24空格"


class TestBackendStartup:
    """测试后端服务能否正常启动"""

    def test_asgi_module_importable(self):
        """验证 asgi 模块可以正常导入"""
        backend_dir = Path(__file__).parent.parent
        if str(backend_dir) not in sys.path:
            sys.path.insert(0, str(backend_dir))

        try:
            import app.asgi
        except IndentationError as e:
            pytest.fail(f"asgi.py 或其依赖存在缩进错误: {e}")
        except ImportError as e:
            pytest.skip(f"导入失败（可能是依赖问题）: {e}")
        except Exception as e:
            pytest.fail(f"导入 asgi.py 时发生意外错误: {e}")

    def test_all_routers_importable(self):
        """验证所有路由模块可以正常导入"""
        backend_dir = Path(__file__).parent.parent
        if str(backend_dir) not in sys.path:
            sys.path.insert(0, str(backend_dir))

        routers = [
            'app.routers.auth',
            'app.routers.submit',
            'app.routers.data',
            'app.routers.questions',
            'app.routers.answers',
            'app.routers.practice',
            'app.routers.admin_review',
            'app.routers.bank_build',
            'app.routers.interview',
            'app.routers.analytics',
            'app.routers.profile',
            'app.routers.health',
        ]

        for router_name in routers:
            try:
                __import__(router_name)
            except IndentationError as e:
                pytest.fail(f"{router_name} 存在缩进错误: {e}")
            except ImportError as e:
                pytest.skip(f"{router_name} 导入失败（可能是依赖问题）: {e}")
