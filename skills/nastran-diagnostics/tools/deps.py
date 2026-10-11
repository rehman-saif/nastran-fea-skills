"""Stop early, with an install line, when a required package is missing.

    from deps import require
    require()          # pyNastran, numpy, scipy (and h5py with h5=True)

Exit code 5 means "dependencies missing"; nothing has been read yet.
"""
import importlib
import sys

INSTALL = ("uv venv --python 3.12 .venv && "
           "uv pip install --python .venv -r skills/nastran-diagnostics/requirements.txt\n"
           "  (or, on Python 3.12: python -m pip install \"pyNastran==1.4.1\" h5py)")


def require(h5=False):
    names = ["pyNastran", "numpy", "scipy"] + (["h5py"] if h5 else [])
    missing = []
    for n in names:
        try:
            importlib.import_module(n)
        except Exception:  # noqa: BLE001 - ImportError or a broken binary wheel
            missing.append(n)
    if missing:
        sys.stderr.write(
            "nastran-diagnostics needs %s (Python %d.%d found; pyNastran 1.4.1 needs Python <= 3.12).\n"
            "Install:\n  %s\n" % (", ".join(missing), sys.version_info[0], sys.version_info[1], INSTALL))
        sys.exit(5)
