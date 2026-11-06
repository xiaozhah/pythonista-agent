"""Run the test suite inside Pythonista, where the iOS modules are real.

From the Mac: python3 dev/client.py run dev/run_tests.py [pytest arguments]
(pytest must be installed in Pythonista's site-packages; pycoder's /pip install pytest does it).
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Pythonista keeps imported modules between runs: forget pycoder's and the tests' so this run
# sees the files as they are now
for name in [n for n in sys.modules if n.split('.')[0] in ('pycoder', 'tests')]:
    del sys.modules[name]
os.chdir(ROOT)
code = pytest.main(
    ['-q', '-p', 'no:cacheprovider', '--capture=sys', '-W', 'ignore', *(sys.argv[1:] or ['tests'])]
)
print('pytest exit code:', int(code))
