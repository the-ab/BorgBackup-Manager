# Third-Party Notices

BorgBackup Manager's own source code is licensed under the Apache License 2.0.
This file summarizes important third-party components used by the application.
It is not a replacement for the complete license texts supplied by those
projects, Python distributions or Debian packages.

## Core runtime components

| Component | Purpose | License |
|---|---|---|
| BorgBackup | Backup engine installed in the container | BSD-3-Clause |
| OpenSSH | Managed repository SSH service and client transport | BSD-style licenses |
| OpenSSL | TLS and cryptographic support | Apache-2.0 |
| Python | Application runtime | Python Software Foundation License |
| Debian | Container operating-system packages | Package-specific free-software licenses |

## Direct Python dependencies

| Package | License |
|---|---|
| FastAPI | MIT |
| Uvicorn | BSD-3-Clause |
| SQLAlchemy | MIT |
| APScheduler | MIT |
| Pydantic | MIT |
| cryptography | Apache-2.0 OR BSD-3-Clause |

The fully resolved dependency set is pinned in `requirements.txt`. Transitive
Python packages retain their own licenses and notices. Installed package metadata
can be inspected inside the image with `python -m pip show PACKAGE`. Debian
package copyright and license files are available under `/usr/share/doc` in the
container image.

## Browser assets

The web interface does not load third-party JavaScript, CSS, fonts or analytics
from external content-delivery networks. The shipped static files are maintained
as part of this project unless a file states otherwise.

## Trademarks and project independence

BorgBackup and related names are trademarks or project names of their respective
owners. BorgBackup Manager is an independent third-party community project. It
is not affiliated with, endorsed by or maintained by the BorgBackup project.

## Updating this file

When adding a dependency, bundled asset or operating-system component, verify its
license compatibility and update this notice where the component is material to
the distributed application.
