"""What iOS reports about crashes, through MetricKit: kept once, and read back."""

from __future__ import annotations

from typing import Any

from pycoder.host import diagnostics

REPORT = {
    'timeStampEnd': '2026-11-01 10:00:00',
    'crashDiagnostics': [
        {
            'diagnosticMetaData': {
                'exceptionType': 1,
                'signal': 11,
                'terminationReason': 'Namespace SIGNAL',
                'virtualMemoryRegionInfo': 'at 0\n  REGION TYPE',
            }
        }
    ],
    'hangDiagnostics': [{'diagnosticMetaData': {'hangDuration': '12 sec'}}],
}


def test_a_report_is_kept_once_and_described(tmp_path: Any) -> None:
    folder = str(tmp_path / 'diagnostics')
    lines = diagnostics.save(REPORT, folder)
    assert lines[0].startswith('crash at 2026-11-01 10:00:00: exceptionType 1, signal 11')
    assert lines[0].endswith('virtualMemoryRegionInfo at 0')  # one line of it
    assert 'hang at 2026-11-01 10:00:00: hangDuration 12 sec' in lines
    assert diagnostics.save(REPORT, folder) == []  # iOS may offer the same one again
    assert diagnostics.all_lines(folder) == lines
