from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_preview_restart_script_has_explicit_18080_safety_guards() -> None:
    script = (ROOT / "scripts" / "restart_preview_control_plane.ps1").read_text(
        encoding="utf-8"
    )

    assert "[switch]$Apply" in script
    assert "$Port -eq 8080" in script
    assert "Get-NetTCPConnection" in script
    assert "Win32_Process" in script
    assert "function Test-PreviewProcessChain" in script
    assert "[object]$Process" in script
    assert "ParentProcessId" in script
    assert "Stop-Process" in script
    assert "New-ScheduledTaskAction" in script
    assert "run_control_plane.py" in script
    assert "Start-ScheduledTask" in script
    assert "Invoke-WebRequest" in script
    assert "Get-Date" in script
