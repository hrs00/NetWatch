"""
build.py — Packages NetWatch into a standalone Windows .exe via PyInstaller.

Usage (on Windows):
    pip install pyinstaller psutil requests
    python build.py

Output: dist/NetWatch.exe
"""

import subprocess
import sys
import os

def build():
    args = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",                   # Single .exe
        "--windowed",                  # No console window (GUI only)
        "--name", "NetWatch",
        "--add-data", "network_monitor.py;.",  # Bundle core module
        # Optional: add an icon
        # "--icon", "assets/icon.ico",
        "netwatch_gui.py",
    ]

    print("Building NetWatch.exe …")
    result = subprocess.run(args, cwd=os.path.dirname(__file__))

    if result.returncode == 0:
        print("\n✓ Build complete: dist/NetWatch.exe")
        print("  Note: Run as Administrator for full connection visibility.")
    else:
        print("\n✗ Build failed. Check output above.")
        sys.exit(1)


if __name__ == "__main__":
    build()