"""Read-only facts about the application under test, shared by the suites (no data, no network, no secret).

APP_ROOT is the folder that holds the « app » package: /app in the image, the checkout everywhere else. A child Python process started there
imports the package (and not app/app.py as a top-level module), whatever the current directory of the test run.
declared_version() reads VERSION from app/app.py as text, so a test compares the running module with the file actually shipped.
"""
import os, re

import app.app as m

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(m.__file__)))


def declared_version():
    with open(os.path.join(APP_ROOT, 'app', 'app.py'), encoding='utf-8') as f:
        found = re.findall(r'^VERSION\s*=\s*"([^"]*)"\s*$', f.read(), re.M)
    if len(found) != 1: raise AssertionError(f'app/app.py must declare VERSION exactly once, found {found!r}')
    if not re.fullmatch(r'9\.2-rc\d+', found[0]): raise AssertionError(f'unexpected version format {found[0]!r}')
    if int(found[0].rsplit('rc', 1)[1]) < 25: raise AssertionError(f'version older than the suites it must satisfy: {found[0]!r}')
    return found[0]
