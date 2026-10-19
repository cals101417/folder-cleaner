"""Creates demo/Downloads: a realistic messy folder for screenshots and manual testing.

Usage: python scripts/make_demo.py   (re-running adds nothing if the folder exists)
"""

import os
import random
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "demo" / "Downloads"
MB = 1024 * 1024
DAY = 86400

LOOSE = [
    ("python-3.12.10-amd64.exe", 26 * MB, 210), ("vlc-3.0.21-win64.exe", 41 * MB, 400),
    ("ChromeSetup.exe", 1.4 * MB, 30), ("Zoom_Installer.msi", 18 * MB, 95),
    ("Screen Recording 2026-03-14.mp4", 182 * MB, 219), ("team-call.mp4", 96 * MB, 60),
    ("Invoice_2026_0412.pdf", 0.3 * MB, 190), ("Lease agreement (signed).pdf", 2.1 * MB, 340),
    ("tax-return-2025.pdf", 1.2 * MB, 160), ("budget.xlsx", 0.09 * MB, 12),
    ("IMG_4021.JPG", 4.2 * MB, 25), ("IMG_4022.JPG", 3.9 * MB, 25), ("screenshot.png", 0.8 * MB, 3),
    ("photos-from-dad.zip", 120 * MB, 500), ("site-backup.tar.gz", 64 * MB, 75),
    ("podcast-ep12.mp3", 48 * MB, 44), ("font-pack.7z", 9 * MB, 600), ("notes.txt", 0.004 * MB, 2),
    ("movie.mkv.crdownload", 30 * MB, 0), ("readme", 0.002 * MB, 700),
]
NESTED = [
    ("Old Phone Backup/DCIM/IMG_0001.JPG", 3.1 * MB, 1200), ("Old Phone Backup/DCIM/IMG_0002.JPG", 2.8 * MB, 1200),
    ("Old Phone Backup/DCIM/VID_0003.MP4", 210 * MB, 1190), ("Old Phone Backup/WhatsApp/voice-note.opus", 0.4 * MB, 1100),
    ("Course videos/week1.mp4", 140 * MB, 800), ("Course videos/week2.mp4", 150 * MB, 790),
    ("Projects/brand/logo-final.psd", 38 * MB, 300), ("Projects/brand/logo-final-v2.psd", 39 * MB, 290),
]
DUPLICATES = [  # (copy, original) — exact copies
    ("Projects/brand/IMG_4021 (1).JPG", "IMG_4021.JPG"),
    ("Old Phone Backup/DCIM/IMG_4021.JPG", "IMG_4021.JPG"),
    ("Invoice_2026_0412 (1).pdf", "Invoice_2026_0412.pdf"),
    ("Course videos/week1 (copy).mp4", "Course videos/week1.mp4"),
    ("vlc-3.0.21-win64 (1).exe", "vlc-3.0.21-win64.exe"),
]


def make(rel: str, size: float, age_days: float, rng: random.Random) -> None:
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(rng.randbytes(min(int(size), 256 * 1024)))   # unique head, so sizes alone don't match
        fh.truncate(int(size))
    stamp = time.time() - age_days * DAY
    os.utime(path, (stamp, stamp))


def main() -> None:
    if ROOT.exists():
        print("exists:", ROOT)
        return
    rng = random.Random(7)
    for rel, size, age in LOOSE + NESTED:
        make(rel, size, age, rng)
    for copy, original in DUPLICATES:
        dst = ROOT / copy
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / original, dst)
    print("created:", ROOT)


if __name__ == "__main__":
    main()
