"""Source-only audit evidence; does not import the application or open its DB."""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
NAMES = {
    "build_thread_id", "save_stage_result", "get_stage_result",
    "record_resolution", "match_outcomes", "aggregate_status",
    "reserve_llm_call", "claim_job_with_generation", "assert_job_fence",
    "publish_items_with_resolutions", "refresh_public_interview_projection",
    "normalize_extracted_questions", "restore_upload",
}
evidence = {name: {"definitions": [], "calls": []} for name in sorted(NAMES)}
for path in sorted((ROOT / "backend/app").rglob("*.py")):
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in NAMES:
            evidence[node.name]["definitions"].append(f"{path.relative_to(ROOT)}:{node.lineno}")
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", getattr(node.func, "attr", None))
            if name in NAMES:
                evidence[name]["calls"].append(f"{path.relative_to(ROOT)}:{node.lineno}")
output = {
    "reviewed_head": "8c810733",
    "method": "AST direct-name calls within backend/app only; dynamic dispatch and aliases require manual review",
    "symbols": evidence,
}
Path(__file__).with_name("callsite-evidence.json").write_text(
    json.dumps(output, ensure_ascii=False, indent=2) + "\n"
)
for name, data in evidence.items():
    print(f"{name}: definitions={len(data['definitions'])} direct_calls={len(data['calls'])}")
