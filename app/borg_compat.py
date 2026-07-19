from __future__ import annotations

import re
from dataclasses import dataclass

BORG_MINIMUM = (1, 2, 0)
BORG_SECURITY_FIXED = (1, 2, 5)
BORG_RECOMMENDED = (1, 2, 8)
BORG_MANAGER_MINIMUM = (1, 4, 0)
BORG_MAXIMUM_EXCLUSIVE = (1, 5, 0)
_VERSION_RE = re.compile(r"(?<!\d)(1|2)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:[^\d]|$)")


@dataclass(frozen=True)
class BorgCompatibility:
    version: str | None
    supported: bool
    level: str
    title: str
    message: str


def parse_borg_version(text: str | None) -> str | None:
    """Read Borg versions only from explicit version output.

    Backup logs may contain file names such as ``1.02.1``. A generic search over
    the complete live log therefore produces false security warnings. Prefer the
    manager marker and known Borg version lines and never interpret arbitrary
    path content as a version.
    """
    if not text:
        return None
    patterns = (
        r"(?im)^\s*BORG AUF CLIENT:\s*((?:1|2)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))\s*$",
        r"(?im)^\s*(?:BBM_BORG_VERSION|BBM_CLIENT_BORG_VERSION)=((?:1|2)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))\s*$",
        r"(?im)^\s*borg(?:backup)?(?:\s+version)?\s+((?:1|2)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))(?:\s|$)",
    )
    for pattern in patterns:
        marker = re.search(pattern, text)
        if marker:
            return marker.group(1)
    return None


def version_tuple(version: str | None) -> tuple[int, int, int] | None:
    if not version:
        return None
    match = re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version)
    if not match:
        return None
    return tuple(int(value) for value in match.groups())


def classify_borg_version(version: str | None) -> BorgCompatibility:
    parsed = version_tuple(version)
    if parsed is None:
        return BorgCompatibility(
            version, False, "unknown", "Borg-Version nicht erkannt",
            "Die installierte Borg-Version konnte nicht zuverlässig ermittelt werden.",
        )
    if parsed < BORG_MINIMUM:
        return BorgCompatibility(
            version, False, "unsupported", "Borg-Version nicht unterstützt",
            "Unterstützt werden Borg 1.2.0 bis 1.4.x. Bitte Borg auf mindestens 1.2.0 aktualisieren.",
        )
    if parsed >= BORG_MAXIMUM_EXCLUSIVE:
        return BorgCompatibility(
            version, False, "unsupported", "Borg-Version nicht freigegeben",
            "Freigegeben und getestet sind Borg 1.2.x bis 1.4.x. Borg 2.x verwendet zusätzlich ein anderes Repository- und Befehlsformat.",
        )
    if parsed < BORG_SECURITY_FIXED:
        return BorgCompatibility(
            version, True, "critical", "Kritische Sicherheitswarnung",
            "Borg 1.2.0 bis 1.2.4 bleiben nutzbar, besitzen aber eine bekannte Archive-Spoofing-Schwachstelle. Ein Upgrade auf mindestens 1.2.5, besser 1.2.8 oder 1.4.x, wird dringend empfohlen.",
        )
    if parsed < BORG_RECOMMENDED:
        return BorgCompatibility(
            version, True, "warning", "Veraltete Borg-Version",
            "Die Version ist technisch nutzbar, liegt aber unter dem empfohlenen Stand 1.2.8. Ein Upgrade auf Borg 1.4.x wird empfohlen.",
        )
    return BorgCompatibility(
        version, True, "ok", "Borg-Version kompatibel",
        "Die Borg-1.x-Version ist für die verwendeten Manager-Funktionen geeignet.",
    )


def version_probe_shell(*, fail_unsupported: bool = True) -> str:
    """POSIX-shell probe supporting older Borg 1.x command-line variants."""
    unsupported = "exit 76" if fail_unsupported else ":"
    return rf'''
bbm_borg_version_output=""
if bbm_borg_version_output=$(borg --version 2>&1); then
  :
elif bbm_borg_version_output=$(borg -V 2>&1); then
  :
elif bbm_borg_version_output=$(borg --show-version help 2>&1); then
  :
else
  printf '%s\n' 'FEHLER: Borg ist nicht installiert oder die Version kann nicht abgefragt werden.' >&2
  exit 76
fi
bbm_borg_version=$(printf '%s\n' "$bbm_borg_version_output" | sed -n 's/.*\([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' | head -n 1)
if [ -z "$bbm_borg_version" ]; then
  printf '%s\n' 'FEHLER: Borg-Version konnte nicht aus der Ausgabe gelesen werden.' >&2
  exit 76
fi
printf 'BORG AUF CLIENT: %s\n' "$bbm_borg_version"
if ! awk -v version="$bbm_borg_version" 'BEGIN {{
  split(version, part, "."); major=part[1]+0; minor=part[2]+0; patch=part[3]+0;
  if (major == 1 && minor >= 2 && minor <= 4) exit 0;
  exit 1;
}}' </dev/null; then
  printf 'FEHLER: Borg %s wird nicht unterstützt. Unterstützt werden Borg 1.2.0 bis 1.4.x.\n' "$bbm_borg_version" >&2
  {unsupported}
fi
if awk -v version="$bbm_borg_version" 'BEGIN {{
  split(version, part, "."); major=part[1]+0; minor=part[2]+0; patch=part[3]+0;
  exit !(major == 1 && minor == 2 && patch < 5);
}}' </dev/null; then
  printf '%s\n' 'WARNUNG: Borg 1.2.0 bis 1.2.4 besitzen eine bekannte Archive-Spoofing-Schwachstelle.' >&2
  printf '%s\n' 'EMPFEHLUNG: Auf Borg 1.2.8 oder 1.4.x aktualisieren.' >&2
elif awk -v version="$bbm_borg_version" 'BEGIN {{
  split(version, part, "."); major=part[1]+0; minor=part[2]+0; patch=part[3]+0;
  exit !(major == 1 && minor == 2 && patch < 8);
}}' </dev/null; then
  printf '%s\n' 'WARNUNG: Diese Borg-Version ist nutzbar, aber veraltet. Borg 1.2.8 oder 1.4.x wird empfohlen.' >&2
fi
'''.strip()
