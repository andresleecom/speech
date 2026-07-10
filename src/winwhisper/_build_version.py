"""Build-time version override for packaged releases.

The build scripts replace this value only while PyInstaller is running, then
restore the source fallback. Keeping it in a module makes the value available
inside frozen applications without changing the checked-in project version.
"""

BUILD_VERSION: str | None = None
