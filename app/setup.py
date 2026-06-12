"""py2app build config (M12) — built by app/deploy.sh inside the brew-python
build venv (`python setup.py py2app`). The bundle is what gives the app its
TCC/Dock/Cmd-Tab identity; keep CFBundleIdentifier stable forever.
"""

from setuptools import setup

VERSION = "0.12.0"  # M12

OPTIONS = {
    "iconfile": "assets/macsist.icns",  # also sets CFBundleIconFile
    "resources": ["assets"],  # -> Contents/Resources/assets/ (asset_dir())
    # Second launcher sharing the bundle runtime -> Contents/MacOS/macsist_notify
    # (cli/macsist posts distributed notifications through it).
    "extra_scripts": ["macsist_notify.py"],
    # "packages" land OUTSIDE site-packages.zip as real directories: pynput
    # imports its darwin backend at runtime, certifi needs cacert.pem as a real
    # file for ssl, and PyObjC's lazy framework loading is kept off the
    # zipimport path entirely.
    "packages": [
        "pynput",
        "httpx",
        "httpcore",
        "h11",
        "idna",
        "certifi",
        # NOTE: PyObjCTools must NOT be listed — it's a namespace package
        # (split across pyobjc-core and pyobjc-framework-Cocoa) and
        # modulegraph's imp-style finder dies on it. The statically imported
        # PyObjCTools.AppHelper is picked up from main.py just fine.
        "objc",
        "Foundation",
        "AppKit",
        "Quartz",
        "ApplicationServices",
        "CoreFoundation",
    ],
    "includes": [
        "pynput.keyboard._darwin",
        "pynput.mouse._darwin",
        "pynput._util.darwin",
    ],
    "plist": {
        # NEVER change: TCC's designated requirement is
        # `identifier "com.macsist.app" + certificate leaf` — this id plus the
        # fixed "Macsist Signing" cert is what keeps grants across redeploys.
        "CFBundleIdentifier": "com.macsist.app",
        "CFBundleName": "Macsist",
        "CFBundleDisplayName": "Macsist",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        # Menu-bar app: start without Dock icon; main.py still flips the
        # activation policy to Regular while the History window is open.
        "LSUIElement": True,
        "LSMinimumSystemVersion": "26.0",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "© 2026 Macsist",
    },
}

setup(name="Macsist", app=["main.py"], options={"py2app": OPTIONS})
