"""
TDD 测试：Docker 部署配置验证

验证 Dockerfile、docker-compose.yml、nginx.conf 的正确性。
"""
import pytest
from pathlib import Path


def _find_project_root(start: Path) -> Path:
    """Return the project root containing the Dockerfile."""
    for candidate in (start, *start.parents):
        if (candidate / "Dockerfile").is_file():
            return candidate
    raise RuntimeError(f"Could not locate project root (containing Dockerfile) from {start}")


PROJECT_ROOT = _find_project_root(Path(__file__).resolve())


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

    def test_runtime_dependencies_use_exported_requirements_with_pip_mirror(self):
        """生产依赖应通过 uv export + pip 镜像安装，避免 uv.lock 直链卡住"""
        content = self._read()
        assert "uv export --frozen --no-dev --no-hashes --format requirements-txt" in content
        assert "pip install --timeout 20 --retries 1" in content
        assert "-r /tmp/requirements.txt" in content

    def test_multi_target_runtime_images(self):
        """应拆分 app-runtime 和 nginx-runtime target"""
        content = self._read()
        assert "AS app-runtime" in content
        assert "AS nginx-runtime" in content

    def test_buildkit_cache_mounts(self):
        """依赖安装应使用 BuildKit cache mount"""
        content = self._read()
        assert "target=/root/.cache/uv" in content
        assert "--mount=type=cache,target=/root/.npm" in content
        assert "id=interview-boss-uv-cache" in content
        assert "sharing=locked,target=/root/.cache/uv" in content

    def test_uv_sync_has_bounded_network_concurrency(self):
        """测试依赖安装的 uv sync 应限制下载并发和重试"""
        content = self._read()
        assert "UV_CONCURRENT_DOWNLOADS=4" in content
        assert "UV_CONCURRENT_INSTALLS=2" in content
        assert "UV_HTTP_RETRIES=1" in content

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


    def test_app_services_share_explicit_image(self):
        """Backend/Worker 应共用显式 app 镜像"""
        content = self._read()
        assert "image: interview-boss-app:local" in content
        assert "target: app-runtime" in content

    def test_nginx_uses_static_runtime_image(self):
        """Nginx 应使用独立静态镜像，不依赖宿主机 frontend/dist"""
        content = self._read()
        assert "image: interview-boss-nginx:local" in content
        assert "target: nginx-runtime" in content
        assert "./frontend/dist:/usr/share/nginx/html" not in content

    def test_worker_is_profile_gated(self):
        """Worker 应通过 profile 按需启用"""
        content = self._read()
        assert "profiles:" in content
        assert "worker" in content

    def test_huggingface_cache_is_appuser_readable(self):
        """HuggingFace 缓存应挂载到 appuser 可读路径"""
        content = self._read()
        assert "HF_HOME=/home/appuser/.cache/huggingface" in content
        assert "/home/appuser/.cache/huggingface:ro" in content
        assert ":/root/.cache/huggingface" not in content

    def test_inline_cache_configured(self):
        """Compose 应配置 inline cache 和显式镜像名"""
        content = self._read()
        assert "BUILDKIT_INLINE_CACHE" in content
        assert "interview-boss-app:local" in content
        assert "interview-boss-nginx:local" in content

    def test_build_uses_host_network_for_stable_dns(self):
        """BuildKit 构建应使用宿主网络，避免 systemd-resolved stub DNS 触发外部 fallback"""
        content = self._read()
        assert "network: host" in content

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

    def test_test_service_data_volume_is_named_and_isolated(self):
        """test 服务 data 卷应使用独立命名卷 test-data，禁止读写生产 backend/data"""
        content = self._read()
        assert "test-data:/app/backend/data" in content, "test 服务应使用独立命名卷 test-data"
        assert "test-data:" in content, "顶层应声明 test-data 命名卷"
        assert "./backend/data:/app/backend/data" in content, "生产 backend 应保留宿主机数据卷"

    def test_hf_cache_dir_is_parameterized(self):
        """HF 缓存路径应通过 HF_CACHE_DIR 参数化（backend+test），默认保持现状"""
        content = self._read()
        d = "${HF_CACHE_DIR:-/home/ubuntu/.cache/huggingface}"
        assert (d + ":/home/appuser/.cache/huggingface:ro") in content, "backend 缓存挂载应参数化"
        assert (d + "/hub/models--Xenova--bge-small-zh-v1.5/snapshots/main:/app/models/bge-small-zh-v1.5:ro") in content, "backend 模型目录挂载应参数化"
        assert content.count(d + ":/home/appuser/.cache/huggingface:ro") >= 2, "backend+test 两处通用缓存挂载都应参数化"
        assert "/home/ubuntu/.cache/huggingface:/home/appuser/.cache/huggingface:ro" not in content
        assert "/home/ubuntu/.cache/huggingface" in content, "默认缓存路径应保留以维持现有挂载语义"
        assert "HF_HOME=/home/appuser/.cache/huggingface" in content

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
        assert "restart: always" in content or "restart: unless-stopped" in content, "应配置自动重启"

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


    def test_excludes_docker_cache(self):
        """应排除本地 BuildKit cache 目录"""
        content = self._read()
        assert ".docker-cache" in content

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


class TestDockerDeployScript:
    """docker-deploy.sh 磁盘保护验证"""

    def _read(self):
        return (PROJECT_ROOT / "deploy" / "docker-deploy.sh").read_text()

    def test_has_pre_build_disk_guard(self):
        """构建前应检查磁盘并在不足时拒绝部署"""
        content = self._read()
        assert "DEPLOY_MIN_FREE_MB" in content
        assert "ensure_disk_before_build" in content
        assert "拒绝部署以避免磁盘爆满" in content

    def test_has_post_build_cache_prune(self):
        """构建后应按阈值收缩 BuildKit cache"""
        content = self._read()
        assert "DEPLOY_TARGET_FREE_MB" in content
        assert "BUILDKIT_RESERVED_SPACE" in content
        assert "docker builder prune" in content
        assert "cleanup_after_build" in content

    def test_default_thresholds_match_docs(self):
        """默认阈值应与文档一致：2048 / 5120 / 2GB"""
        content = self._read()
        assert "DEPLOY_MIN_FREE_MB:-2048" in content
        assert "DEPLOY_TARGET_FREE_MB:-5120" in content
        assert "BUILDKIT_RESERVED_SPACE:-2GB" in content

    def test_build_commands_are_guarded(self):
        """核心构建和 Worker 构建应走磁盘保护包装"""
        content = self._read()
        assert "guarded_compose_build backend nginx" in content
        assert "guarded_compose_build backend" in content
        # worker-up / worker-restart 应走 guarded_compose_build，
        # 而不是用 docker compose --build 绕过磁盘保护
        assert "--build worker" not in content

    def test_build_commands_use_cached_mirrors_with_healthcheck(self):
        """默认构建应复用缓存镜像源，仅在健康检查失败时刷新"""
        content = self._read()
        assert "DEPLOY_MIRROR_HEALTHCHECK_ON_BUILD:-1" in content
        assert "DEPLOY_SELECT_MIRRORS_ON_BUILD:-0" in content
        assert "maybe_select_mirrors" in content
        assert "ensure_mirrors_selected" not in content
        assert "load_cached_package_mirrors" in content
        assert "check_package_mirrors_healthy" in content

    def test_mirror_refresh_is_explicit_command(self):
        """镜像源刷新应是显式命令，不应绑定每次 update"""
        content = self._read()
        assert "do_mirrors" in content
        assert "mirrors)" in content
        assert "clear_mirror_cache" in content
        assert "DEPLOY_SELECT_MIRRORS_ON_BUILD=1" in content

    def test_docker_dns_configured_when_refreshing_mirrors(self):
        """刷新镜像源时应持久化 Docker DNS，避免 BuildKit fallback 到不可控外部 DNS"""
        content = self._read()
        assert "ensure_docker_dns_config" in content
        assert "DEPLOY_DOCKER_DNS" in content
        assert "223.5.5.5" in content
        assert "119.29.29.29" in content

    def test_update_preflight_blocks_slow_dependency_regressions(self):
        """update 应在长时间 build 前拦截会绕过镜像源的依赖安装回退"""
        content = self._read()
        assert "preflight_update_contract" in content
        assert "guarded_compose_build" in content
        assert "uv export --frozen --no-dev --no-hashes --format requirements-txt" in content
        assert "uv sync --frozen --no-dev --no-install-project" in content
        assert "network: host" in content
        assert "files.pythonhosted.org" in content
        assert "部署预检通过" in content

    def test_cleanup_after_build_never_stops_services(self):
        """cleanup_after_build 绝不能在构建成功后停止/删除运行中服务"""
        content = self._read()
        in_cleanup = False
        for line in content.splitlines():
            if "cleanup_after_build" in line and "()" in line:
                in_cleanup = True
            elif in_cleanup and line.startswith("}") and not line.strip().startswith("#"):
                break
            if in_cleanup:
                # 不应出现 --rmi（会删除刚构建的镜像）
                assert "--rmi" not in line, f"cleanup_after_build 中禁止 --rmi: {line}"

    def test_prune_unused_docker_does_not_force_down(self):
        """prune_unused_docker 不应默认停止运行中的服务"""
        content = self._read()
        # 不应包含无条件的 docker compose down；即使不带 --rmi 也会停止运行服务
        assert "docker compose down" not in content
        assert "docker compose down --rmi local" not in content

    def test_has_diagnose_command(self):
        """应提供 diagnose 命令输出磁盘诊断"""
        content = self._read()
        assert "do_diagnose" in content
        assert "diagnose)" in content
        assert "docker system df" in content

    def test_cleanup_supports_dry_run_and_aggressive(self):
        """cleanup 应支持 --dry-run 和 --aggressive 参数"""
        content = self._read()
        assert "--dry-run" in content
        assert "--aggressive" in content
        assert "DEPLOY_PRUNE_HOST_ARTIFACTS" in content


class TestMirrorSelectionScript:
    """mirrors.sh 镜像缓存验证"""

    def _read(self):
        return (PROJECT_ROOT / "deploy" / "mirrors.sh").read_text()

    def test_mirror_cache_is_versioned(self):
        """镜像源缓存目录应带版本，避免复用旧脚本写下的坏源"""
        content = self._read()
        assert "MIRROR_CACHE_VERSION" in content
        assert "/tmp/interview-boss-mirrors-" in content
        assert "v2" in content
