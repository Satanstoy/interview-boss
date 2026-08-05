"""
TDD 测试 — 用户简历上传与管理服务

红灯阶段：resume_service 模块尚不存在，测试应 FAIL
"""
import pytest
from unittest.mock import patch, MagicMock


class TestResumeService:
    """简历 CRUD 操作测试"""

    def test_save_resume_stores_text_and_filename(self, test_db):
        """T-001: 保存简历应存储 raw_text 和 filename"""
        from app.services import resume_service

        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('test_user', 'hash', 0)")
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = 'test_user'").fetchone()[0]

        resume_id = resume_service.save_resume(user_id, "resume.pdf", "张三\n软件工程师\n3年经验")

        assert resume_id > 0
        resume = resume_service.get_resume(user_id)
        assert resume is not None
        assert resume["filename"] == "resume.pdf"
        assert "张三" in resume["raw_text"]

    def test_get_resume_returns_none_when_no_resume(self, test_db):
        """T-003: 无简历时 get_resume 应返回 None"""
        from app.services import resume_service

        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('test_user2', 'hash', 0)")
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = 'test_user2'").fetchone()[0]

        result = resume_service.get_resume(user_id)
        assert result is None

    def test_delete_resume_removes_resume(self, test_db):
        """T-004: 删除简历后 has_resume 应返回 False"""
        from app.services import resume_service

        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('test_user3', 'hash', 0)")
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = 'test_user3'").fetchone()[0]

        resume_service.save_resume(user_id, "resume.pdf", "简历内容")
        assert resume_service.has_resume(user_id) is True

        result = resume_service.delete_resume(user_id)
        assert result is True
        assert resume_service.has_resume(user_id) is False

    def test_save_resume_overwrites_previous(self, test_db):
        """T-005: 重复上传应覆盖旧简历，仅保留最新一份"""
        from app.services import resume_service

        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('test_user4', 'hash', 0)")
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = 'test_user4'").fetchone()[0]

        resume_service.save_resume(user_id, "old_resume.pdf", "旧简历内容")
        resume_service.save_resume(user_id, "new_resume.pdf", "新简历内容")

        resume = resume_service.get_resume(user_id)
        assert resume["filename"] == "new_resume.pdf"
        assert "新简历内容" in resume["raw_text"]

    def test_has_resume_returns_correctly(self, test_db):
        """T-007: has_resume 应正确判断有/无简历"""
        from app.services import resume_service

        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('test_user5', 'hash', 0)")
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('test_user6', 'hash', 0)")
        conn.commit()
        user_with = conn.execute("SELECT id FROM users WHERE username = 'test_user5'").fetchone()[0]
        user_without = conn.execute("SELECT id FROM users WHERE username = 'test_user6'").fetchone()[0]

        resume_service.save_resume(user_with, "resume.pdf", "有简历")

        assert resume_service.has_resume(user_with) is True
        assert resume_service.has_resume(user_without) is False


class TestPDFExtraction:
    """PDF 文本提取测试"""

    def test_extract_pdf_text_from_bytes(self):
        """T-006: 从 PDF 字节流提取文本"""
        from app.services.resume_service import extract_pdf_text

        # 创建一个简单的 PDF 字节流用于测试
        # pypdf 可以创建简单的 PDF
        from pypdf import PdfWriter
        from io import BytesIO

        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        buf = BytesIO()
        writer.write(buf)
        pdf_bytes = buf.getvalue()

        # 空白页应该返回空字符串但不抛异常
        result = extract_pdf_text(pdf_bytes)
        assert isinstance(result, str)

    def test_extract_pdf_text_rejects_non_pdf(self):
        """非 PDF 字节应抛出异常"""
        from app.services.resume_service import extract_pdf_text

        with pytest.raises(ValueError, match="PDF"):
            extract_pdf_text(b"this is not a pdf file")


class TestResumeOptimizationStorage:
    """优化结果存取（migration 061 新列）"""

    def test_save_and_get_optimization(self, test_db):
        """T-101: save_optimization 后 get_optimization 能取回全部字段"""
        from app.services import resume_service

        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('opt_user', 'hash', 0)")
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = 'opt_user'").fetchone()[0]
        resume_service.save_resume(user_id, "resume.pdf", "张三\n软件工程师\n3年经验")

        assert resume_service.save_optimization(
            user_id,
            position="后端工程师",
            points=["量化项目成果", "补充技术栈关键词"],
            optimized_text="# 张三\n## 教育背景\n...",
        ) is True

        opt = resume_service.get_optimization(user_id)
        assert opt is not None
        assert opt["position"] == "后端工程师"
        assert opt["points"] == ["量化项目成果", "补充技术栈关键词"]
        assert "教育背景" in opt["optimized_text"]
        assert opt["optimized_at"]

    def test_get_optimization_returns_none_when_absent(self, test_db):
        """T-102: 未优化过应返回 None"""
        from app.services import resume_service

        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('opt_user2', 'hash', 0)")
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = 'opt_user2'").fetchone()[0]

        assert resume_service.get_optimization(user_id) is None

    def test_save_optimization_overwrites_previous(self, test_db):
        """T-103: 重复优化覆盖旧结果，只保留最新一份"""
        from app.services import resume_service

        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('opt_user3', 'hash', 0)")
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = 'opt_user3'").fetchone()[0]
        resume_service.save_resume(user_id, "r.pdf", "内容")

        assert resume_service.save_optimization(user_id, "岗位A", ["要点1"], "版本1") is True
        assert resume_service.save_optimization(user_id, "岗位B", ["要点2"], "版本2") is True

        opt = resume_service.get_optimization(user_id)
        assert opt["position"] == "岗位B"
        assert opt["points"] == ["要点2"]
        assert opt["optimized_text"] == "版本2"

    def test_save_optimization_without_resume_returns_false(self, test_db):
        """T-104: 无简历行时 save_optimization 应返回 False"""
        from app.services import resume_service

        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('opt_user4', 'hash', 0)")
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = 'opt_user4'").fetchone()[0]

        assert resume_service.save_optimization(user_id, "岗位A", ["要点1"], "版本1") is False
