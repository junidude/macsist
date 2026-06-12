"""Distributed-notification poster (M12) — built as Contents/MacOS/macsist_notify
via py2app extra_scripts, sharing the bundle's runtime (PyObjC included).

Usage: macsist_notify <notification-name>
e.g. `macsist settings` runs: macsist_notify com.macsist.showSettings
"""

import sys

from Foundation import NSDistributedNotificationCenter


def main():
    NSDistributedNotificationCenter.defaultCenter() \
        .postNotificationName_object_userInfo_deliverImmediately_(
            sys.argv[1], None, None, True)


if __name__ == "__main__":
    main()
