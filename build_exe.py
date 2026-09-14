# -*- coding: utf-8 -*-
"""
build_exe.py — Build Script for Tumblr Outreach Bot v2.0
=========================================================
Automates building the standalone Windows executable using PyInstaller.
Usage:
    python build_exe.py            # Builds standalone TumblrBot.exe (Windowed mode)
    python build_exe.py --console  # Builds TumblrBot.exe with console window enabled
"""

import os
import sys
import shutil
import argparse
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def clean_build_artifacts():
    """Remove compiler intermediates without touching runtime data in dist/."""
    print("[1/3] Cleaning previous build artifacts...")
    for folder in ["build"]:
        path = os.path.join(BASE_DIR, folder)
        if os.path.exists(path):
            try:
                shutil.rmtree(path)
                print(f"      Removed {folder}/")
            except Exception as e:
                print(f"      Warning: could not delete {folder}/: {e}")


def run_pyinstaller(console: bool = False):
    """Build in staging, then replace only the executable in dist/."""
    print("[2/3] Compiling TumblrBot.exe with PyInstaller...")
    spec_path = os.path.join(BASE_DIR, "tumblr_bot.spec")
    staging_dir = os.path.join(BASE_DIR, "build", "staged_dist")

    # If user wants console mode, adjust spec parameter or pass CLI flags
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--distpath",
        staging_dir,
        spec_path,
    ]

    print(f"      Executing: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=BASE_DIR)
    if result.returncode != 0:
        print(f"\n[ERROR] PyInstaller build failed with exit code {result.returncode}")
        sys.exit(result.returncode)

    staged_exe = os.path.join(staging_dir, "TumblrBot.exe")
    if not os.path.isfile(staged_exe):
        print(f"\n[ERROR] Staged executable was not found at: {staged_exe}")
        sys.exit(1)

    output_dir = os.path.join(BASE_DIR, "dist")
    os.makedirs(output_dir, exist_ok=True)
    shutil.copy2(staged_exe, os.path.join(output_dir, "TumblrBot.exe"))
    shutil.rmtree(staging_dir, ignore_errors=True)


def verify_output():
    """Verifies that the executable was successfully produced and reports size."""
    print("[3/3] Verifying output executable...")
    exe_path = os.path.join(BASE_DIR, "dist", "TumblrBot.exe")
    if os.path.isfile(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print("\n" + "=" * 60)
        print("  BUILD SUCCESSFUL!")
        print(f"  Executable: {exe_path}")
        print(f"  File Size : {size_mb:.2f} MB")
        print("=" * 60 + "\n")
        print("Tip: You can now double-click 'dist\\TumblrBot.exe' to launch the bot.")
    else:
        print(f"\n[ERROR] Expected output file not found at: {exe_path}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Build TumblrBot Windows Executable")
    parser.add_argument("--console", action="store_true", help="Enable terminal console window")
    parser.add_argument("--no-clean", action="store_true", help="Skip cleaning compiler files in build/")
    args = parser.parse_args()

    if not args.no_clean:
        clean_build_artifacts()

    run_pyinstaller(console=args.console)
    verify_output()


if __name__ == "__main__":
    main()
