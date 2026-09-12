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
    """Removes previous build artifacts to ensure a fresh compilation."""
    print("[1/3] Cleaning previous build artifacts...")
    for folder in ["build", "dist"]:
        path = os.path.join(BASE_DIR, folder)
        if os.path.exists(path):
            try:
                shutil.rmtree(path)
                print(f"      Removed {folder}/")
            except Exception as e:
                print(f"      Warning: could not delete {folder}/: {e}")


def run_pyinstaller(console: bool = False):
    """Executes PyInstaller with the project spec file."""
    print("[2/3] Compiling TumblrBot.exe with PyInstaller...")
    spec_path = os.path.join(BASE_DIR, "tumblr_bot.spec")

    # If user wants console mode, adjust spec parameter or pass CLI flags
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        spec_path,
    ]

    print(f"      Executing: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=BASE_DIR)
    if result.returncode != 0:
        print(f"\n[ERROR] PyInstaller build failed with exit code {result.returncode}")
        sys.exit(result.returncode)


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
    parser.add_argument("--no-clean", action="store_true", help="Skip cleaning build/ and dist/ folders")
    args = parser.parse_args()

    if not args.no_clean:
        clean_build_artifacts()

    run_pyinstaller(console=args.console)
    verify_output()


if __name__ == "__main__":
    main()
