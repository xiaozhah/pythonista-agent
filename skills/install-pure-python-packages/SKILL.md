---
name: install-pure-python-packages
description: "Use when a task needs a Python package Pythonista may not have: check whether it can work on iOS and install it without pip"
---

Not available, having C code: scipy, cryptography, lxml, cffi, pydantic v2. Bundled: numpy, pandas, matplotlib, PIL, PyCrypto, reportlab and others.

1. Check first whether Pythonista already ships it: `import name` in run_python (numpy, matplotlib,
   requests, PIL, bs4, markdown, pygments, jinja2, yaml ... are bundled).
2. Only pure-Python packages can run on iOS. On PyPI their files include a wheel tagged
   `py3-none-any`. If only platform wheels or an sdist with C/Rust sources exist, it cannot be
   installed: iOS does not let an app load native code it downloaded.
3. Install with the install_package tool (or `/pip install name`). It downloads the wheel, checks
   its sha256, installs missing dependencies and unzips into site-packages-3 (local to the device;
   install again on each device).
4. Watch for dependencies that clash with Pythonista's bundled versions: it ships requests 2.28 with
   urllib3 1.26. A package requiring urllib3>=2 will break requests — pin an older release instead.
   Example: dulwich 1.x needs urllib3 2.x, so git uses `dulwich==0.22.8` (urllib3>=1.25).
5. After installing, import it in run_python to confirm it loads.
