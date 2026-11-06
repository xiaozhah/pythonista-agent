"""What iOS says about this app's crashes and hangs, through MetricKit: an app can't read the system's
crash logs, but it can get its own reports, with why it ended even when iOS killed it from outside
(which leaves nothing in crash.log). Kept as JSON files that /crashes and the model can read.

Reports come only for an app that subscribed before the crash, and iOS delivers them at a later start.
"""

from __future__ import annotations

import ctypes
import json
import os
from typing import Any

from .. import config
from . import env

METRICKIT = '/System/Library/Frameworks/MetricKit.framework/MetricKit'
DIRECTORY = os.path.join(config.DATA_DIR, 'diagnostics')
KINDS = ('crashDiagnostics', 'hangDiagnostics', 'cpuExceptionDiagnostics', 'diskWriteExceptionDiagnostics')
WORDS = (
    'exceptionType',
    'exceptionCode',
    'signal',
    'terminationReason',
    'virtualMemoryRegionInfo',
    'hangDuration',
)


def collect(directory: str = DIRECTORY) -> list[str]:
    """Subscribe, and save the reports iOS has for us. Returns a line about each new one."""
    if not env.IN_PYTHONISTA:
        return []
    from objc_util import ObjCClass, nsdata_to_bytes

    ctypes.cdll.LoadLibrary(METRICKIT)
    manager = ObjCClass('MXMetricManager').sharedManager()
    # a plain object, so no Python runs when iOS delivers (the reports are read below); kept for the
    # life of the process, as the manager holds its subscribers weakly
    if not env.process_wide('metrickit_subscribed', []):
        subscriber = ObjCClass('NSObject').new()
        manager.addSubscriber_(subscriber)
        env.process_wide('metrickit_subscribed', []).append(subscriber)
    payloads = manager.pastDiagnosticPayloads()
    lines = []
    for i in range(payloads.count() if payloads else 0):
        data = nsdata_to_bytes(payloads.objectAtIndex_(i).JSONRepresentation())
        report = json.loads(data)
        lines += save(report, directory)
    return lines


def save(report: dict[str, Any], directory: str) -> list[str]:
    """Keep a report once; a line for each crash or hang in a new one."""
    stamp = ''.join(c for c in str(report.get('timeStampEnd', 'report')) if c.isalnum())
    path = os.path.join(directory, f'{stamp}.json')
    if os.path.exists(path):
        return []
    os.makedirs(directory, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    return describe(report)


def describe(report: dict[str, Any]) -> list[str]:
    lines = []
    for kind in KINDS:
        for item in report.get(kind) or []:
            meta = item.get('diagnosticMetaData') or {}
            found = ', '.join(
                f'{word} {str(meta[word]).splitlines()[0]}'
                for word in WORDS
                if meta.get(word) not in (None, '')
            )
            lines.append(f'{kind.removesuffix("Diagnostics")} at {report.get("timeStampEnd", "?")}: {found}')
    return lines


def all_lines(directory: str = DIRECTORY) -> list[str]:
    """Every report kept here, newest first."""
    if not os.path.isdir(directory):
        return []
    lines: list[str] = []
    for name in sorted(os.listdir(directory), reverse=True):
        try:
            with open(os.path.join(directory, name), encoding='utf-8') as f:
                lines += describe(json.load(f))
        except (OSError, ValueError):
            continue
    return lines
