"""
BUG-004: E 分类拆分测试
测试 normalize_category 别名映射和 migration 035 分类逻辑
"""
import pytest


class TestNormalizeCategoryAliases:
    """测试 normalize_category 的 taxonomy 别名映射"""

    def test_old_e1_mapped_to_data_structure(self):
        """旧的 E1.算法手撕与数据结构 应映射到 E1.数据结构"""
        from app.services.utils import normalize_category
        assert normalize_category("E1.算法手撕与数据结构") == "E1.数据结构"

    def test_llm_shortened_e1_mapped_to_algorithm(self):
        """LLM 缩写的 E1.算法手撕 应映射到 E2.算法手撕"""
        from app.services.utils import normalize_category
        assert normalize_category("E1.算法手撕") == "E2.算法手撕"

    def test_other_categories_unchanged(self):
        """其他分类不应被修改"""
        from app.services.utils import normalize_category
        assert normalize_category("B1.Agent架构与范式") == "B1.Agent架构与范式"
        assert normalize_category("C3.数据库基础") == "C3.数据库基础"

    def test_new_e1_unchanged(self):
        """新的 E1.数据结构 不应被修改"""
        from app.services.utils import normalize_category
        assert normalize_category("E1.数据结构") == "E1.数据结构"

    def test_new_e2_unchanged(self):
        """新的 E2.算法手撕 不应被修改"""
        from app.services.utils import normalize_category
        assert normalize_category("E2.算法手撕") == "E2.算法手撕"

    def test_empty_input(self):
        """空输入应返回空"""
        from app.services.utils import normalize_category
        assert normalize_category("") == ""
        assert normalize_category(None) is None


class TestClassifyEQuestion:
    """测试 _classify_e_question 关键词分类逻辑"""

    def test_lru_classified_as_data_structure(self):
        """LRU Cache 应归入 E1.数据结构"""
        from app.db.migrations import _classify_e_question
        assert _classify_e_question("手撕：LRU Cache") == "E1.数据结构"
        assert _classify_e_question("算法题：手写 LRU Cache") == "E1.数据结构"

    def test_linked_list_classified_as_data_structure(self):
        """链表题应归入 E1.数据结构"""
        from app.db.migrations import _classify_e_question
        assert _classify_e_question("手撕 分割链表") == "E1.数据结构"
        assert _classify_e_question("算法题：合并两个有序链表") == "E1.数据结构"

    def test_binary_tree_classified_as_data_structure(self):
        """二叉树题应归入 E1.数据结构"""
        from app.db.migrations import _classify_e_question
        assert _classify_e_question("二叉树的层序遍历") == "E1.数据结构"

    def test_dp_classified_as_algorithm(self):
        """动态规划题应归入 E2.算法手撕"""
        from app.db.migrations import _classify_e_question
        assert _classify_e_question("买卖股票 IV") == "E2.算法手撕"

    def test_graph_dfs_classified_as_algorithm(self):
        """图遍历题应归入 E2.算法手撕"""
        from app.db.migrations import _classify_e_question
        assert _classify_e_question("在图中如何判断是否存在环") == "E2.算法手撕"

    def test_design_data_structure_classified_as_data_structure(self):
        """设计数据结构题应归入 E1.数据结构"""
        from app.db.migrations import _classify_e_question
        assert _classify_e_question("算法题：设计一个支持O(1)插入删除和随机获取的数据结构") == "E1.数据结构"

    def test_generic_algorithm_classified_as_algorithm(self):
        """通用算法题应归入 E2.算法手撕"""
        from app.db.migrations import _classify_e_question
        assert _classify_e_question("算法题：口述解题思路") == "E2.算法手撕"


class TestSplitECategoryMigration:
    """测试 migration 035 E 分类拆分"""

    @pytest.fixture
    def mock_db_with_e_categories(self):
        """创建包含 E 分类题目的 mock 数据库"""
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE question_bank (
                id INTEGER PRIMARY KEY,
                question TEXT,
                cat1 TEXT,
                cat2 TEXT,
                frequency INTEGER DEFAULT 1,
                duplicate_of INTEGER,
                deleted_at TIMESTAMP,
                updated_at TIMESTAMP
            );
            CREATE TABLE questions_detail (
                id INTEGER PRIMARY KEY,
                question TEXT,
                cat2 TEXT
            );
        """)
        # E category questions
        conn.execute("INSERT INTO question_bank (id, question, cat1, cat2) VALUES (1, '手撕：LRU Cache', 'E.算法与数据结构', 'E1.算法手撕与数据结构')")
        conn.execute("INSERT INTO question_bank (id, question, cat1, cat2) VALUES (2, '买卖股票 IV', 'E.算法与数据结构', 'E1.算法手撕与数据结构')")
        conn.execute("INSERT INTO question_bank (id, question, cat1, cat2) VALUES (3, '二叉树的遍历', 'E.算法与数据结构', 'E1.算法手撕')")
        conn.execute("INSERT INTO question_bank (id, question, cat1, cat2) VALUES (4, '算法题：动态规划', 'E.算法与数据结构', 'E1.算法手撕')")
        # Non-E question (should not be affected)
        conn.execute("INSERT INTO question_bank (id, question, cat1, cat2) VALUES (5, 'Redis 数据结构', 'C.基础工程能力', 'C2.框架与中间件')")
        # questions_detail
        conn.execute("INSERT INTO questions_detail (id, question, cat2) VALUES (101, '手撕 LRU Cache', 'E1.算法手撕与数据结构')")
        conn.execute("INSERT INTO questions_detail (id, question, cat2) VALUES (102, '排序算法', 'E1.算法手撕')")
        conn.commit()
        return conn

    def test_migration_splits_e_categories(self, mock_db_with_e_categories):
        """migration 应将 E 分类正确拆分"""
        from app.db.migrations import _migration_035_split_e_category
        conn = mock_db_with_e_categories
        _migration_035_split_e_category(conn)

        results = {row['id']: row['cat2'] for row in conn.execute("SELECT id, cat2 FROM question_bank ORDER BY id").fetchall()}
        assert results[1] == "E1.数据结构", f"LRU Cache 应为 E1.数据结构, 实际={results[1]}"
        assert results[2] == "E2.算法手撕", f"买卖股票 应为 E2.算法手撕, 实际={results[2]}"
        assert results[3] == "E1.数据结构", f"二叉树 应为 E1.数据结构, 实际={results[3]}"
        assert results[4] == "E2.算法手撕", f"动态规划 应为 E2.算法手撕, 实际={results[4]}"
        assert results[5] == "C2.框架与中间件", f"非E分类不应被修改, 实际={results[5]}"

    def test_migration_updates_questions_detail(self, mock_db_with_e_categories):
        """migration 应同步更新 questions_detail 表"""
        from app.db.migrations import _migration_035_split_e_category
        conn = mock_db_with_e_categories
        _migration_035_split_e_category(conn)

        details = {row['id']: row['cat2'] for row in conn.execute("SELECT id, cat2 FROM questions_detail ORDER BY id").fetchall()}
        assert details[101] == "E1.数据结构", f"LRU Cache detail 应为 E1.数据结构, 实际={details[101]}"
        assert details[102] == "E2.算法手撕", f"排序算法 detail 应为 E2.算法手撕, 实际={details[102]}"
