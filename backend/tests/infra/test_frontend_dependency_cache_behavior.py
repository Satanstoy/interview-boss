"""Run the dependency script against disposable Git worktrees and a fake installer."""
import os
from pathlib import Path
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / 'scripts/frontend-deps.sh'


def run(*args, cwd=None, env=None):
    return subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, check=True)


@pytest.fixture
def dependency_worktrees(tmp_path):
    repo = tmp_path / 'repository'
    repo.mkdir()
    frontend = repo / 'frontend'
    frontend.mkdir()
    (frontend / 'package.json').write_text('{"name":"fixture","private":true}')
    (frontend / 'package-lock.json').write_text('{"lockfileVersion":3}')
    run('git', 'init', '-q', str(repo))
    run('git', '-C', str(repo), 'add', 'frontend')
    run('git', '-C', str(repo), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Fixture')
    other = tmp_path / 'other-worktree'
    run('git', '-C', str(repo), 'worktree', 'add', '-qb', 'other', str(other))
    cache = tmp_path / 'cache'
    cache.mkdir()
    commands = tmp_path / 'commands'
    commands.mkdir()
    # Only installation and storage checks are fake. Cache identity, locking,
    # symlinks, Git enumeration and the script's cleanup execute for real.
    stubs = {
        'npm': '#!/bin/bash\nmkdir -p node_modules/.bin\nprintf "#!/bin/bash\\nexit 0\\n" > node_modules/.bin/playwright\nchmod +x node_modules/.bin/playwright\n',
        'findmnt': '#!/bin/bash\necho /dev/disposable-fixture\n',
        'df': '#!/bin/bash\nprintf "Filesystem 1M-blocks Used Available Use%% Mounted on\\nfixture 200000 1000 199000 1%% /fixture\\n"\n',
    }
    for name, body in stubs.items():
        executable = commands / name
        executable.write_text(body)
        executable.chmod(0o755)
    env = {
        **os.environ,
        'PATH': f'{commands}:{os.environ["PATH"]}',
        'FRONTEND_DEPS_CACHE_DIR': str(cache),
        'FRONTEND_DEPS_MAX_VERSIONS': '1',
    }
    def install(project):
        run('bash', str(SCRIPT), env={**env, 'FRONTEND_DEPS_PROJECT_ROOT': str(project)})
        return (project / 'frontend/node_modules').resolve()
    return repo, other, cache, install


def test_identical_lockfiles_share_cache_across_worktrees(dependency_worktrees):
    repo, other, _, install = dependency_worktrees
    first = install(repo)
    second = install(other)
    assert first == second
    assert (first / '.bin/playwright').is_file()


def test_pruning_preserves_a_cache_referenced_by_another_worktree(dependency_worktrees):
    repo, other, cache, install = dependency_worktrees
    active = install(repo)
    (other / 'frontend/package-lock.json').write_text('{"lockfileVersion":3,"fixture":"different"}')
    stale = cache / ('a' * 24)
    stale.mkdir()
    (stale / '.interview-boss-dependency-key').write_text('a' * 24)
    (stale / 'unused').write_text('unused dependency')
    newer = install(other)
    assert newer != active
    assert (repo / 'frontend/node_modules/.bin/playwright').is_file()
    assert (active / '.bin/playwright').is_file()
    assert not stale.exists()
