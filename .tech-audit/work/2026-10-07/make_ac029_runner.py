from pathlib import Path

s = Path("/opt/interview-boss/scripts/real_stack_smoke.sh").read_text()
prefix = s[: s.index('if [ "${REAL_STACK_ONLY_AC016:-0}"')]
prefix = prefix.replace(
    'PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"',
    'PROJECT_DIR="/opt/interview-boss"',
)
start = s.index("# AC-029 seeds a known public canonical")
end = s.index("\nfi\n\n# AC-009:", start)
Path("/tmp/spec-review-ac029.sh").write_text(prefix + "\n" + s[start:end] + "\nexit 0\n")
