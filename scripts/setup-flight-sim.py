"""Set up the pinned local FlightGear/A320 runtime under this project's work folder.

Downloads official assets and extracts them without running the FlightGear installer.
The innounp extraction tool comes from its developer's site. Asset hashes pin the
artifacts reviewed for this project; they are not a statement of model validity.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work" / "flightgear"


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def fetch(asset):
    checksum = asset.get("sha256")
    if not isinstance(checksum, str) or len(checksum) != 64 or any(
        character not in "0123456789abcdef" for character in checksum
    ):
        raise ValueError("Invalid SHA-256 pin for " + asset["name"])
    target = WORK / "downloads" / asset["name"]
    if not target.exists():
        partial = target.with_name(target.name + ".partial")
        # This setup owns the partial only while running; do not run two setups.
        print("Downloading", asset["name"], flush=True)
        with urllib.request.urlopen(asset["url"], timeout=60) as source, partial.open("wb") as output:
            while chunk := source.read(1024 * 1024):
                output.write(chunk)
        if partial.stat().st_size != asset["bytes"]:
            raise ValueError("Download length mismatch: " + asset["name"])
        partial.rename(target)
    if target.stat().st_size != asset["bytes"] or digest(target) != checksum:
        raise ValueError("Asset differs from reviewed pin; preserved for inspection: " + str(target))
    print("Verified", asset["name"], flush=True)
    return target


def unzip(archive, target):
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        for name in source.namelist():
            if not (target / name).resolve().is_relative_to(target.resolve()):
                raise ValueError("Archive path escapes destination")
        source.extractall(target)


def main():
    (WORK / "downloads").mkdir(parents=True, exist_ok=True)
    pins = json.loads((ROOT / "configs" / "flightgear-assets.json").read_text(encoding="utf-8"))
    files = {a["name"]: fetch(a) for a in pins["assets"]}
    tool_dir = WORK / "tools" / "innounp"
    if not (tool_dir / "innounp.exe").exists():
        unzip(files["innounp-2.zip"], tool_dir)
    runtime = WORK / "runtime"
    if not (runtime / "{app}" / "bin" / "fgfs.exe").exists():
        runtime.mkdir(parents=True, exist_ok=True)
        with (WORK / "extract-runtime.log").open("w", encoding="utf-8") as log:
            subprocess.run([
                str(tool_dir / "innounp.exe"), "-x", "-q", "-d" + str(runtime),
                str(files["flightgear-2024.1.7-windows-amd64.exe"]),
            ], cwd=ROOT, check=True, stdout=log, stderr=subprocess.STDOUT,
               creationflags=subprocess.CREATE_NO_WINDOW)
    base = WORK / "base"
    marker = base / ".extracted-2024.1.7"
    if not marker.exists():
        print("Extracting FlightGear base data; this can take a few minutes.", flush=True)
        base.mkdir(parents=True, exist_ok=True)
        with tarfile.open(files["FlightGear-2024.1.7-data.txz"], "r|xz") as source:
            source.extractall(base, filter="data")
        if not (base / "fgdata_2024_1" / "version").exists():
            raise ValueError("Unexpected FlightGear data layout")
        marker.write_text("2024.1.7\n", encoding="utf-8")
    aircraft = WORK / "aircraft"
    if not (aircraft / "A320-family" / "A320-200-CFM-set.xml").exists():
        unzip(files["A320-family.zip"], aircraft)
    print("Local FlightGear and A320 assets are ready. See docs/CONNECTED-SIMULATOR.md for manual startup.", flush=True)


if __name__ == "__main__":
    main()
