from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_compose_separates_edge_and_data_networks():
    content = (PROJECT_ROOT / "docker-compose.yml").read_text()
    assert "edge-network:" in content
    assert "data-network:" in content
    assert "app-network:" not in content


def test_compose_redis_requires_secret_and_does_not_publish_ports():
    content = (PROJECT_ROOT / "docker-compose.yml").read_text()
    assert "redis_password:" in content
    assert "--requirepass" in content
    assert '"127.0.0.1:6379' not in content
    assert '"6379:6379' not in content


def test_oauth_secret_is_not_overridden_by_empty_host_interpolation():
    content = (PROJECT_ROOT / "docker-compose.yml").read_text()
    assert "OAUTH_SECRET_KEY=${OAUTH_SECRET_KEY}" not in content
    assert "env_file: backend/.env" in content


def test_runtime_redis_secret_is_excluded_from_docker_context():
    content = (PROJECT_ROOT / ".dockerignore").read_text()
    assert "backend/.redis-password" in content


def test_nginx_bounds_unauthenticated_oauth_bodies():
    content = (PROJECT_ROOT / "nginx/nginx.conf").read_text()
    assert "client_max_body_size 64k" in content


def test_nginx_normalizes_forwarded_client_ip_before_proxying():
    content = (PROJECT_ROOT / "nginx/nginx.conf").read_text()
    assert "real_ip_recursive on;" in content
    assert "limit_req_zone $binary_remote_addr" in content
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for" not in content
