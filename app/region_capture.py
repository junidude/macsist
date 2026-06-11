"""Interactive region capture: screencapture -i → PNG bytes (downscaled).

Cancel (Esc) and capture-to-clipboard (^C during selection) are silent no-ops:
Esc exits non-zero with no file; ^C exits 0 with no file — hence the combined
returncode + file-size success check.

Runs on a worker thread. The Popen handle is published to proc_holder so the
controller can terminate a pending selection overlay when a new hotkey press
preempts it.
"""

import base64
import os
import struct
import subprocess
import tempfile

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def capture_region(config, proc_holder=None, debug_rect=None):
    """Run the interactive selection; return PNG bytes or None (silent no-op).

    debug_rect: "x,y,w,h" → non-interactive `screencapture -R` (verification
    hook — the interactive overlay can't be driven synthetically).
    """
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        if debug_rect:
            cmd = ["screencapture", "-x", "-R", debug_rect, path]
        else:
            cmd = ["screencapture", "-i", "-x", "-o", path]
        proc = subprocess.Popen(cmd)
        if proc_holder is not None:
            # published, never cleared: terminate()/wait() on an exited proc
            # are no-ops, so a stale reference is benign and clearing would
            # race the next capture's publish
            proc_holder(proc)
        returncode = proc.wait()
        if returncode != 0 or not os.path.exists(path) or os.path.getsize(path) == 0:
            return None
        data = _read_downscaled(path, int(config.get("region_max_dim")))
        print(f"region captured: {len(data)} bytes", flush=True)
        return data
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def png_dimensions(data):
    """(width, height) from the IHDR chunk, or None if not a PNG. Cheaper than
    a sips subprocess, and we have the bytes in hand anyway."""
    if len(data) < 24 or not data.startswith(_PNG_SIGNATURE):
        return None
    return struct.unpack(">II", data[16:24])


def _read_downscaled(path, max_dim):
    with open(path, "rb") as f:
        data = f.read()
    dims = png_dimensions(data)
    # Check dimensions BEFORE running sips: whether -Z upscales smaller images
    # varies across macOS versions, so only invoke it when actually too big.
    if dims and max_dim > 0 and max(dims) > max_dim:
        result = subprocess.run(
            ["sips", "-Z", str(max_dim), path],
            capture_output=True,
        )
        if result.returncode == 0:
            with open(path, "rb") as f:
                data = f.read()
            print(f"region downscaled: {dims} -> {png_dimensions(data)}", flush=True)
    return data


def to_data_url(png_bytes):
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")


def _main():
    import argparse

    from config import ConfigStore

    parser = argparse.ArgumentParser(description="M3 region capture smoke test")
    parser.add_argument(
        "--rect", help='non-interactive capture rect "x,y,w,h" (skip overlay)'
    )
    args = parser.parse_args()

    data = capture_region(ConfigStore(), debug_rect=args.rect)
    if data is None:
        print("(취소 또는 캡처 실패 — no-op)", flush=True)
    else:
        print(f"captured {len(data)} bytes, dims={png_dimensions(data)}", flush=True)


if __name__ == "__main__":
    _main()
