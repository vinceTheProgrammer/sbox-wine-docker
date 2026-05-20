#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path
import argparse
import time
import hashlib

ROOT = Path("/root/sbox")
DOTNET_EXE = r"C:\Program Files\dotnet\dotnet.exe"
CONFIG = os.environ.get("SBOX_CONFIG", "Developer")

CACHE_DIR = ROOT / ".sboxbuild_cache"
HOST_UID = os.environ.get("HOST_UID")
HOST_GID = os.environ.get("HOST_GID")

CODEGEN_PATCH_FLAG = ROOT / ".sboxbuild_codegen_patch"
CODEGEN_TARGETS = ROOT / "engine/CodeGen.Targets"
CODEGEN_PATCH_SRC = Path("/root/patches/CodeGen.Targets")
CODEGEN_BACKUP = ROOT / "CodeGen.Targets.backup"

# Ignore paths (repo-relative)
IGNORE_DIRS = {
    ".git",
    ".vscode",
    ".idea",
    ".vs",
    "bin",
    "obj",
    ".sboxbuild_cache",
}

IGNORE_SUFFIXES = {
    ".user",
    ".suo",
    ".cache",
    ".log",
}

RELEVANT_SUFFIXES = {
    ".cs",
    ".csproj",
    ".props",
    ".targets",
    ".sln",
    ".slnx",
    ".json",
    ".razor",
    ".tt",
}

SBOXBUILD_CSPROJ = ROOT / "engine/Tools/SboxBuild/SboxBuild.csproj"


def run(cmd, capture=False):
    print(f"+ {' '.join(cmd)}")
    if capture:
        return subprocess.check_output(cmd, text=False)
    subprocess.check_call(cmd)
    return None


def is_ignored(path: str) -> bool:
    path = path.replace("\\", "/").lstrip("./")
    parts = path.split("/")

    for part in parts[:-1]:
        if part in IGNORE_DIRS:
            return True

    p = Path(path)
    if p.suffix in IGNORE_SUFFIXES:
        return True

    return False


def is_relevant(path: str) -> bool:
    if path.endswith("/"):
        return False
    return Path(path).suffix in RELEVANT_SUFFIXES


def git_changed_files():
    changed = set()

    out = run(["git", "status", "--porcelain", "-z"], capture=True)
    entries = out.split(b"\x00")

    for entry in entries:
        if not entry:
            continue
        if len(entry) < 4:
            continue

        raw_path = entry[3:]
        path = raw_path.decode("utf-8", errors="replace").strip()

        if not path:
            continue
        if is_ignored(path):
            continue
        if not is_relevant(path):
            continue

        changed.add(path)

    return sorted(changed)

def find_all_csprojs():
    return sorted(ROOT.rglob("*.csproj"))

def find_csproj_owners(changed_files):
    owners = set()

    for f in changed_files:
        full = ROOT / f
        if not full.exists():
            continue

        p = full.parent
        while p != ROOT and p != p.parent:
            csprojs = sorted(p.glob("*.csproj"))
            if csprojs:
                owners.add(csprojs[0])
                break
            p = p.parent

    return sorted(owners)

def prompt_yes_no(msg: str, default: bool) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    while True:
        ans = input(msg + suffix + ": ").strip().lower()
        if ans == "":
            return default
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print("Please answer y or n.")

def wine_path(path: Path):
    return "Z:/" + str(path.relative_to("/")).replace("\\", "/")


def build_project(csproj: Path):
    proj = wine_path(csproj)
    print(f"\n==> BUILDING: {csproj.relative_to(ROOT)}\n")

    run([
        "xvfb-run", "-a",
        "wine", DOTNET_EXE,
        "build", proj,
        "-c", CONFIG
    ])

def test():
    if not SBOXBUILD_CSPROJ.exists():
        print(f"ERROR: missing {SBOXBUILD_CSPROJ}")
        return 1

    proj = wine_path(SBOXBUILD_CSPROJ)

    print("\n==> TESTS (SboxBuild)\n")

    run([
        "xvfb-run", "-a",
        "wine", DOTNET_EXE,
        "run",
        "--project", proj,
        "--",
        "test"
    ])

    print("\n==> Testing done.")
    return 0

def format():
    if not SBOXBUILD_CSPROJ.exists():
        print(f"ERROR: missing {SBOXBUILD_CSPROJ}")
        return 1

    proj = wine_path(SBOXBUILD_CSPROJ)

    print("\n==> FORMAT (SboxBuild)\n")

    run([
        "xvfb-run", "-a",
        "wine", DOTNET_EXE,
        "run",
        "--project", proj,
        "--",
        "format",
        "--verify"
    ])

    print("\n==> Format done.")
    return 0


def looks_like_fresh_clone(min_hits=4):
    sentinel_paths = [
        ROOT / "game/sbox.exe",
        ROOT / "game/sbox.dll",
        ROOT / "game/bin/managed/Sandbox.Engine.dll",
        ROOT / "game/.source2",
        ROOT / "engine/Tools/CodeGen/bin/CodeGen.dll",
    ]

    hits = sum(1 for p in sentinel_paths if p.exists())
    return hits < min_hits

def full_build():
    if not SBOXBUILD_CSPROJ.exists():
        print(f"ERROR: missing {SBOXBUILD_CSPROJ}")
        return 1

    proj = wine_path(SBOXBUILD_CSPROJ)

    print("\n==> FULL BUILD (SboxBuild)\n")

    run([
        "xvfb-run", "-a",
        "wine", DOTNET_EXE,
        "run",
        "--project", proj,
        "--",
        "build",
        "--config", CONFIG
    ])

    run([
        "xvfb-run", "-a",
        "wine", DOTNET_EXE,
        "run",
        "--project", proj,
        "--",
        "build-shaders"
    ])

    run([
        "xvfb-run", "-a",
        "wine", DOTNET_EXE,
        "run",
        "--project", proj,
        "--",
        "build-content"
    ])

    print("\n==> Full build done.")
    return 0


def iter_project_inputs(project_dir: Path):
    """
    Walk project dir recursively and yield relevant files
    (excluding bin/obj/.git/.vscode/etc).
    """
    for root, dirs, files in os.walk(project_dir):
        root_path = Path(root)

        # prune ignored directories
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

        for f in files:
            p = root_path / f
            if p.suffix in IGNORE_SUFFIXES:
                continue
            if p.suffix not in RELEVANT_SUFFIXES:
                continue
            yield p


def find_directory_build_files(start_dir: Path):
    """
    Collect Directory.Build.props/targets walking up to ROOT.
    """
    out = []
    p = start_dir

    while True:
        props = p / "Directory.Build.props"
        targets = p / "Directory.Build.targets"

        if props.exists():
            out.append(props)
        if targets.exists():
            out.append(targets)

        if p == ROOT:
            break
        if p.parent == p:
            break
        p = p.parent

    return out


def file_hash(path: Path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def compute_project_hash(csproj: Path):
    """
    Hash project inputs + directory build files.
    """
    project_dir = csproj.parent

    inputs = [csproj]
    inputs.extend(find_directory_build_files(project_dir))
    inputs.extend(iter_project_inputs(project_dir))

    # remove duplicates, sort stable
    inputs = sorted(set(inputs))

    h = hashlib.sha256()

    for p in inputs:
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")

        with open(p, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)

    return h.hexdigest()


def cache_file_for(csproj: Path):
    safe_name = str(csproj.relative_to(ROOT)).replace("/", "__").replace("\\", "__")
    return CACHE_DIR / (safe_name + ".sha256")


def should_build_hash_cache(csproj: Path):
    new_hash = compute_project_hash(csproj)
    cache_file = cache_file_for(csproj)

    # Missing cache entry:
    # initialize it and assume unchanged
    if not cache_file.exists():
        cache_file.write_text(new_hash + "\n")
        print(f"==> Initialized hash cache: {csproj.relative_to(ROOT)}")
        return False

    old_hash = cache_file.read_text().strip()

    if old_hash == new_hash:
        return False

    cache_file.write_text(new_hash + "\n")
    return True

def force_update_hash(csproj: Path):
    new_hash = compute_project_hash(csproj)
    cache_file = cache_file_for(csproj)

    cache_file.write_text(new_hash + "\n")

def init_hash_cache():
    print("==> Initializing hash cache...")
    projects = find_all_csprojs()

    for p in projects:
        h = force_update_hash(p)

    print(f"==> Hash cache initialized for {len(projects)} projects.")

import shutil

def fix_addon_code_case():
    """
    Some builds incorrectly generate game/addons/<addon>/code/* instead of Code/*.
    On Linux this breaks Proton. This function merges `code` into `Code` and deletes `code`.
    """
    addons_dir = ROOT / "game/addons"
    if not addons_dir.exists():
        return

    print("\n==> Fixing addon Code/code case issues...")

    for addon in addons_dir.iterdir():
        if not addon.is_dir():
            continue

        lower = addon / "code"
        proper = addon / "Code"

        if not lower.exists() or not lower.is_dir():
            continue

        # If Code doesn't exist, create it
        proper.mkdir(parents=True, exist_ok=True)

        # Move everything from code/ into Code/
        for src in lower.rglob("*"):
            if src.is_dir():
                continue

            rel = src.relative_to(lower)
            dst = proper / rel

            dst.parent.mkdir(parents=True, exist_ok=True)

            # If destination exists, overwrite it
            if dst.exists():
                dst.unlink()

            shutil.move(str(src), str(dst))

        # Remove empty dirs inside lower
        for d in sorted(lower.rglob("*"), reverse=True):
            if d.is_dir():
                try:
                    d.rmdir()
                except OSError:
                    pass

        # Remove the main lower directory if empty
        try:
            lower.rmdir()
            print(f"   Fixed: {lower.relative_to(ROOT)} -> {proper.relative_to(ROOT)}")
        except OSError:
            print(f"   WARNING: could not delete {lower.relative_to(ROOT)} (not empty?)")

    print("==> Done fixing addon case issues.")

def fix_ownership_since(start_time: float):
    """
    Chown any files/dirs modified since start_time to HOST_UID:HOST_GID.
    This prevents root-owned build outputs on the host bind mount.
    """
    if not HOST_UID or not HOST_GID:
        print("==> HOST_UID/HOST_GID not set, skipping ownership fix.")
        return

    print(f"\n==> Fixing ownership (UID={HOST_UID}, GID={HOST_GID})...")

    ts = int(start_time)

    # Fix repo outputs
    subprocess.call([
        "bash", "-lc",
        f"find {ROOT} -xdev -newermt '@{ts}' -print0 | "
        f"xargs -0 -r chown {HOST_UID}:{HOST_GID}"
    ])

    print("==> Ownership fixed.")

def apply_codegen_patch():
    """
    If .sboxbuild_codegen_patch exists, replace engine/CodeGen.Targets
    with /root/patches/CodeGen.Targets, while backing up the original.
    """
    if not CODEGEN_PATCH_FLAG.exists():
        return False

    if not CODEGEN_PATCH_SRC.exists():
        print(f"ERROR: Codegen patch flag exists, but patch file missing: {CODEGEN_PATCH_SRC}")
        return False

    if not CODEGEN_TARGETS.exists():
        print(f"ERROR: Missing CodeGen.Targets in repo: {CODEGEN_TARGETS}")
        return False

    # ensure cache dir exists for backup
    CODEGEN_BACKUP.parent.mkdir(parents=True, exist_ok=True)

    # backup original (overwrite any previous backup)
    CODEGEN_BACKUP.write_bytes(CODEGEN_TARGETS.read_bytes())

    # apply patched version
    CODEGEN_TARGETS.write_bytes(CODEGEN_PATCH_SRC.read_bytes())

    print("==> Codegen patch enabled: replaced engine/CodeGen.Targets")
    return True


def restore_codegen_patch():
    """
    Restore CodeGen.Targets if a backup exists.
    """
    if not CODEGEN_BACKUP.exists():
        return

    CODEGEN_TARGETS.write_bytes(CODEGEN_BACKUP.read_bytes())
    CODEGEN_BACKUP.unlink(missing_ok=True)

    print("==> Codegen patch restored: reverted engine/CodeGen.Targets")

def main():
    start_time = time.time()

    something_to_build = True

    no_prompt_env = os.environ.get("NO_PROMPT", "") == "1"

    parser = argparse.ArgumentParser(description="Smart incremental build for s&box in docker/wine.")
    parser.add_argument("--full", action="store_true", help="Force a full build using SboxBuild.")
    parser.add_argument("--no-auto-full", action="store_true",
                        help="Disable auto full-build detection for fresh clones.")
    parser.add_argument("--enable-hash-cache", action="store_true",
                    help="Enable hash-cache mode (creates .sboxbuild_cache/).")
    parser.add_argument("--enable-codegen-patch", action="store_true",
                    help="Enable CodeGen.Targets patching (creates .sboxbuild_codegen_patch).")
    parser.add_argument("--test", action="store_true",
                        help="Run tests after build.")
    parser.add_argument("--format", action="store_true",
                        help="Format the project.")
    parser.add_argument("--no-prompt", action="store_true",
                    help="Never prompt user; use defaults.")
    args = parser.parse_args()

    no_prompt = args.no_prompt or no_prompt_env

    os.chdir(ROOT)

    # avoid "dubious ownership" issues
    subprocess.call(["git", "config", "--global", "--add", "safe.directory", str(ROOT)])

    codegen_patch_applied = False

    try:

        # First build wizard
        if looks_like_fresh_clone() and not no_prompt:
            print("==> Fresh clone detected.")

            if prompt_yes_no("Enable hash cache mode? (change based smart building that does not rely on git commits) ; Creates .sboxbuild_cache folder", default=True):
                if not CACHE_DIR.exists():
                    CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    init_hash_cache()
                print("==> Hash cache enabled.")

            if prompt_yes_no("Enable CodeGen.Targets patch? (experimental CodeGen.Targets patch that skips re-running codegen if already generated) ; Creates .sboxbuild_codegen_patch file", default=False):
                CODEGEN_PATCH_FLAG.write_text("enabled\n")
                print("==> Codegen patch enabled.")

        # Hash cache set up
        hash_cache_enabled = (CACHE_DIR.exists() or args.enable_hash_cache)

        if args.enable_hash_cache and not CACHE_DIR.exists():
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            print("==> Hash cache enabled: created .sboxbuild_cache/")
            init_hash_cache()
        elif hash_cache_enabled:
            print("==> Hash cache enabled: using existing .sboxbuild_cache/")
        else:
            print("==> Hash cache disabled")

        # Enable codegen patch (creates marker file)
        if args.enable_codegen_patch:
            CODEGEN_PATCH_FLAG.write_text("enabled\n")
            print("==> Enabled codegen patch: created .sboxbuild_codegen_patch")

        # Apply patch if marker exists
        codegen_patch_applied = apply_codegen_patch()

        # Format
        if args.format:
            rc = format()
            if rc == 1:
                return rc

        # Forced full build
        if args.full:
            rc = full_build()
            return rc

        # Auto full build if looks like never built
        if not args.no_auto_full and looks_like_fresh_clone():
            print("==> No build output detected (fresh clone?). Running full build...")
            rc = full_build()
            return rc

        if hash_cache_enabled:
            projects = find_all_csprojs()
        else:
            changed = git_changed_files()
            if not changed:
                print("==> No relevant git changes detected. Nothing to build.")
                projects = []
                something_to_build = False
            else:
                projects = find_csproj_owners(changed)

        if not projects:
            if hash_cache_enabled:
                print("==> No .csproj files found.")
            else:
                print("\n==> No owning .csproj found for changed files.")
                print("    (Maybe only non-code files changed?)")
            something_to_build = False

        if something_to_build:
            print("\n==> Projects to build:")
            for p in projects:
                print("   ", p.relative_to(ROOT))

            for p in projects:
                if hash_cache_enabled:
                    if not should_build_hash_cache(p):
                        print(f"\n==> SKIPPING (hash match): {p.relative_to(ROOT)}")
                        continue
                build_project(p)

        if args.test:
            rc = test()
            if rc == 1:
                return rc

        print("\n==> Done.")
        return 0

    finally:
        if codegen_patch_applied:
            restore_codegen_patch()
        fix_addon_code_case()
        fix_ownership_since(start_time)


if __name__ == "__main__":
    sys.exit(main())
