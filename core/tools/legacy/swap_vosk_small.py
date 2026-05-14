"""
scripts/swap_vosk_small.py — Replace the large Vosk model (2.7GB/5GB RAM)
with the small-en-us model (40MB disk / ~180MB RAM).

RAM savings: 5203MB -> ~180MB = FREE UP ~5GB SYSTEM RAM

Run once:  python scripts/swap_vosk_small.py
"""
import sys, os, io, urllib.request, zipfile, shutil
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OLD_MODEL = os.path.join(ROOT, "vosk-model")
SMALL_DIR = os.path.join(ROOT, "vosk-model-small-en-us-0.15")
ZIP_FILE  = os.path.join(ROOT, "vosk-small.zip")
URL       = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"

SEP = "=" * 52
print(f"\n{SEP}")
print("  Vosk Model Swap: Large (5GB RAM) -> Small (~180MB RAM)")
print(f"{SEP}\n")

# ── 1. Check if small model already exists ─────────────────────────────────────
if os.path.isdir(SMALL_DIR):
    print(f"  [OK] Small model already present: {SMALL_DIR}")
    print("  Update vosk-model symlink/rename is still required if not done.")
else:
    # ── 2. Download small model ───────────────────────────────────────────────
    print(f"  Downloading {URL}")
    print(f"  Size: ~48 MB\n")

    def _progress(count, block_size, total_size):
        dl_mb  = min(count * block_size, total_size) / 1024 / 1024
        tot_mb = total_size / 1024 / 1024
        pct    = int(100 * min(count * block_size, total_size) / max(total_size, 1))
        bar    = "#" * (pct // 2) + "." * (50 - pct // 2)
        sys.stdout.write(f"\r  [{bar}] {dl_mb:.1f}/{tot_mb:.1f}MB  {pct}%")
        sys.stdout.flush()

    try:
        urllib.request.urlretrieve(URL, ZIP_FILE, reporthook=_progress)
        print("\n  Download complete.")
    except Exception as e:
        print(f"\n  ERROR: Download failed: {e}")
        sys.exit(1)

    # ── 3. Extract ────────────────────────────────────────────────────────────
    print(f"  Extracting to {ROOT}...")
    with zipfile.ZipFile(ZIP_FILE, "r") as z:
        z.extractall(ROOT)
    os.remove(ZIP_FILE)
    # The zip contains vosk-model-small-en-us-0.22/, rename to our target
    raw_dir = os.path.join(ROOT, "vosk-model-small-en-us-0.22")
    if os.path.isdir(raw_dir) and not os.path.isdir(SMALL_DIR):
        os.rename(raw_dir, SMALL_DIR)
    print(f"  Extracted: {SMALL_DIR}")

# ── 4. Rename old model as backup, set small as default ───────────────────────
if os.path.isdir(OLD_MODEL):
    backup = OLD_MODEL + "-large-backup"
    if not os.path.isdir(backup):
        os.rename(OLD_MODEL, backup)
        print(f"\n  Old large model backed up: {backup}")
    else:
        print(f"\n  Old large model backup exists: {backup} (skipping rename)")

# ── 5. Create vosk-model symlink / rename so VoiceEngine auto-picks it ────────
if not os.path.isdir(OLD_MODEL):
    # Just rename/link small → vosk-model so no code changes needed
    try:
        os.symlink(SMALL_DIR, OLD_MODEL)
        print(f"  Symlink: vosk-model -> vosk-model-small-en-us")
    except (OSError, NotImplementedError):
        # Symlinks may require admin on Windows — just rename instead
        shutil.copytree(SMALL_DIR, OLD_MODEL)
        print(f"  Copied small model to vosk-model/")

# ── 6. Quick RAM test ─────────────────────────────────────────────────────────
print(f"\n  Testing small model...")
try:
    import psutil
    proc = __import__('psutil').Process(os.getpid())
    before = proc.memory_info().rss // 1024**2
    from vosk import Model
    m = Model(OLD_MODEL if os.path.isdir(OLD_MODEL) else SMALL_DIR)
    after = proc.memory_info().rss // 1024**2
    print(f"  Small model RAM: {after - before}MB (was 5203MB with large model)")
    print(f"\n  [PASS] Vosk small model loaded successfully.")
    print(f"  RAM savings: ~{5203 - (after-before)}MB freed from system RAM")
except Exception as e:
    print(f"  Test failed: {e}")

print(f"\n{SEP}")
print("  DONE. Restart JARVIS to use the small model.")
print(f"{SEP}\n")
