"""
TDD 测试：Docker 部署配置验证

验证 Dockerfile、docker-compose.yml、nginx.conf 的正确性。
"""
import pytest
from pathlib import Path

PROJECT_ROOT = Path("/root/sj/interview-boss")


class TestDockerfile:
    """Dockerfile 配置验证"""

    def _read(self):
        return (PROJECT_ROOT / "Dockerfile").read_text()

    def test_multi_stage_build(self):
        """应使用多阶段构建"""
        content = self._read()
        assert content.count("FROM") >= 2, "应至少有 2 个 FROM（多阶段构建）"

    def test_frontend_build_stage(self):
        """应有前端构建阶段"""
        content = self._read()
        assert "npm run build" in content, "缺少前端构建步骤"

    def test_backend_runtime(self):
        """后端运行时应基于 Python"""
        content = self._read()
        assert "python" in content.lower(), "应使用 Python 基础镜像"

    def test_uv_dependency_manager(self):
        """应使用 uv 管理依赖"""
        content = self._read()
        assert "uv" in content, "应使用 uv 管理 Python 依赖"

    def test_expose_port(self):
        """应暴露 8000 端口"""
        content = self._read()
        assert "EXPOSE 8000" in content, "应暴露 8000 端口"

    def test_data_dir_created(self):
        """应创建数据目录"""
        content = self._read()
        assert "mkdir" in content and "data" in content, "应创建数据目录"

    def test_redis_url_env(self):
        """应设置 REDIS_URL 环境变量"""
        content = self._read()
        assert "REDIS_URL" in content, "应设置 REDIS_URL 环境变量"


class TestDockerCompose:
    """docker-compose.yml 配置验证"""

    def _read(self):
        return (PROJECT_ROOT / "docker-compose.yml").read_text()

    def test_has_redis_service(self):
        """应有 Redis 服务"""
        content = self._read()
        assert "redis:" in content

    def test_has_backend_service(self):
        """应有 Backend 服务"""
        content = self._read()
        assert "backend:" in content

    def test_has_worker_service(self):
        """应有 Worker 服务"""
        content = self._read()
        assert "worker:" in content

    def test_has_nginx_service(self):
        """应有 Nginx 服务"""
        content = self._read()
        assert "nginx:" in content

    def test_redis_memory_limit(self):
        """Redis 应有内存限制"""
        content = self._read()
        assert "maxmemory" in content, "Redis 应配置 maxmemory"

    def test_backend_memory_limit(self):
        """Backend 应有内存限制"""
        content = self._read()
        assert "mem_limit" in content, "Backend 应配置 mem_limit"

    def test_worker_memory_limit(self):
        """Worker 应有内存限制"""
        content = self._read()
        assert "mem_limit" in content, "Worker 应配置 mem_limit"

    def test_data_volume_mount(self):
        """SQLite 数据应挂载到宿主机"""
        content = self._read()
        assert "backend/data" in content, "SQLite 数据目录应挂载"

    def test_env_file_config(self):
        """应通过 env_file 注入环境变量"""
        content = self._read()
        assert "env_file" in content, "应使用 env_file 注入环境变量"

    def test_health_checks(self):
        """关键服务应有健康检查"""
        content = self._read()
        assert "healthcheck" in content, "应配置健康检查"

    def test_restart_policy(self):
        """服务应配置自动重启"""
        content = self._read()
        assert "restart: always" in content, "应配置自动重启"

    def test_redis_health_dependency(self):
        """Backend 应等待 Redis 健康后启动"""
        content = self._read()
        assert "service_healthy" in content, "应配置依赖健康检查"


class TestNginxConfig:
    """nginx.conf 配置验证"""

    def _read(self):
        return (PROJECT_ROOT / "nginx" / "nginx.conf").read_text()

    def test_api_proxy(self):
        """应代理 /api/ 到后端"""
        content = self._read()
        assert "proxy_pass" in content and "backend" in content

    def test_spa_fallback(self):
        """应配置 SPA 路由回退"""
        content = self._read()
        assert "try_files" in content and "index.html" in content

    def test_gzip_enabled(self):
        """应启用 Gzip 压缩"""
        content = self._read()
        assert "gzip on" in content

    def test_static_cache(self):
        """静态资源应配置长期缓存"""
        content = self._read()
        assert "immutable" in content

    def test_api_timeout(self):
        """API 代理应配置超时"""
        content = self._read()
        assert "proxy_read_timeout" in content

    def test_security_headers(self):
        """应配置安全头"""
        content = self._read()
        assert "X-Content-Type-Options" in content
        assert "X-Frame-Options" in content

    def test_sse_buffering_off(self):
        """SSE 响应应关闭缓冲"""
        content = self._read()
        assert "proxy_buffering off" in content


class TestDockerIgnore:
    """.dockerignore 配置验证"""

    def _read(self):
        return (PROJECT_ROOT / ".dockerignore").read_text()

    def test_excludes_node_modules(self):
        """应排除 node_modules"""
        content = self._read()
        assert "node_modules" in content

    def test_excludes_venv(self):
        """应排除 Python 虚拟环境"""
        content = self._read()
        assert ".venv" in content

    def test_excludes_git(self):
        """应排除 .git"""
        content = self._read()
        assert ".git" in content

    def test_excludes_env_file(self):
        """应排除 .env 文件"""
        content = self._read()
        assert ".env" in content

    def test_excludes_data_dir(self):
        """应排除数据目录（运行时挂载）"""
        content = self._read()
        assert "backend/data" in content
