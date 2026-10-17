"""Deployment-specific compliance evidence must be a complete, redacted template."""

from pathlib import Path


MATRIX = (
    Path(__file__).resolve().parents[3]
    / "docs/compliance/deployment-matrix.template.md"
)


def test_compliance_matrix_has_instance_specific_processor_fields():
    source = MATRIX.read_text()

    required_fields = (
        "Deployment instance",
        "Provider legal entity",
        "Processing purpose",
        "Data categories",
        "Region / cross-border transfer mechanism",
        "Retention period",
        "Deletion method",
        "Subprocessor version",
        "Owner",
    )
    assert all(field in source for field in required_fields)
    assert "REDACTED" in source
    assert "secret" in source.lower()


def test_compliance_matrix_distinguishes_self_hosted_and_configurable_endpoints():
    source = MATRIX.read_text()

    assert "self-hosted" in source.lower()
    assert "OpenAI-compatible" in source
    assert "privacy-policy.md" in source
