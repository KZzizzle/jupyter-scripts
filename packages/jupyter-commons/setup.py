import re
import sys
from pathlib import Path

from setuptools import find_packages, setup

here = Path(sys.argv[0] if __name__ ==
            "__main__" else __file__).resolve().parent


def read_reqs(reqs_path: Path):
    reqs = re.findall(
        r"^([^#\s].+)", reqs_path.read_text(), re.MULTILINE
    )
    for i, r in enumerate(reqs):
        m = re.match(r"^git\+.*#egg=([\w-]+)", r)
        if m:
            reqs[i] = f"{m.group(1)} @ {r}"

    return reqs


# Ensures compatiblity with jupyter-minimal
JUPYTER_MINIMAL_COMPATIBLE_REQUIREMENTS = read_reqs(here / "requirements" / "requirements.txt")

OSPARC_REQUIREMENTS = list(set(read_reqs( here / "requirements/osparc-simcore.txt")) | {"watchdog", "jupyterlab"})


# can be used to debug
for r in OSPARC_REQUIREMENTS:
    print(r)

if __name__ == "__main__":

    setup(
        name="jupyter-commons",
        version="0.2.0",
        packages=find_packages(where="src"),
        package_dir={"": "src"},
        python_requires=">=3.6",
        install_requires=OSPARC_REQUIREMENTS,
        extras_require= {
            "jupyter-minimal": JUPYTER_MINIMAL_COMPATIBLE_REQUIREMENTS
        }
    )
