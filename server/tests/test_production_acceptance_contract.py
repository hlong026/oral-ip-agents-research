"""Production acceptance wrapper must remain Staging-only and fail closed."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_acceptance_runner_uses_private_manual_results_and_propagates_no_go() -> None:
    script = (ROOT / "deploy/scripts/production-acceptance.sh").read_text(encoding="utf-8")

    assert "Production acceptance must run against DEPLOY_ENVIRONMENT=staging" in script
    assert "STAGING_MANUAL_ACCEPTANCE_RESULTS" in script
    assert "0400 or 0600" in script
    assert "staging-smoke.sh" in script
    assert "acceptance_report.py" in script
    assert "acceptance-cases.json" in script
    assert 'if [ "$status" -eq 3 ]' in script
    assert "Production acceptance decision: NO_GO" in script
    assert "exit 3" in script


def test_manual_results_template_defaults_every_manual_gate_to_pending() -> None:
    cases = __import__("json").loads((ROOT / "deploy/acceptance/acceptance-cases.json").read_text(encoding="utf-8"))[
        "cases"
    ]
    manual = __import__("json").loads(
        (ROOT / "deploy/acceptance/manual-results.example.json").read_text(encoding="utf-8")
    )["results"]

    manual_ids = {case["id"] for case in cases if case["mode"] == "manual" and case["required"] is True}
    assert set(manual) == manual_ids
    assert all(entry["status"] == "manual_pending" for entry in manual.values())
    assert all(entry["evidence"] == [] for entry in manual.values())
