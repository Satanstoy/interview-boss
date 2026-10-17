"""Document the same first-run administrator defaults used by migrations."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_admin_username_defaults_match_seed_and_example_env():
    seed = (ROOT / "backend/app/db/migrations/auth.py").read_text()
    operations = (ROOT / "backend/app/db/operations.py").read_text()
    view = (ROOT / "backend/app/db/migrations/view.py").read_text()
    env_example = (ROOT / "backend/.env.example").read_text()
    readme = (ROOT / "README.md").read_text()

    for source in (seed, operations, view):
        assert 'os.getenv("ADMIN_USERNAME", "sj")' in source
    assert "ADMIN_USERNAME=sj" in env_example
    assert "| `ADMIN_USERNAME` | 种子管理员用户名 | `sj` |" in readme
    assert "JWT_SECRET" in readme


def test_example_env_explains_production_jwt_requirement():
    env_example = (ROOT / "backend/.env.example").read_text()

    assert "生产" in env_example
    assert "JWT_SECRET=" in env_example
    assert "自动生成" not in env_example
