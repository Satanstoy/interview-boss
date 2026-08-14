from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_oauth_csp_allows_chatgpt_authorization_callback():
    source = (REPO_ROOT / "nginx/nginx.conf").read_text(encoding="utf-8")
    policies = re.findall(
        r'add_header Content-Security-Policy "([^"]+)"', source
    )

    assert policies
    assert all(
        "form-action 'self' https://chatgpt.com" in policy for policy in policies
    )
