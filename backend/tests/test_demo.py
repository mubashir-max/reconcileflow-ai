import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]


def test_demo_script_runs_complete_workflow(tmp_path):
    output = tmp_path / "demo-results.csv"
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "run_reconciliation_demo.py"),
            "--output",
            str(output),
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    summary = json.loads(completed.stdout)
    assert output.is_file()
    assert summary["status"] == "SUCCEEDED"
    assert summary["reconciliation_results"] == 8
    assert summary["output_filename"] == "demo-results.csv"
    assert str(tmp_path) not in completed.stdout
