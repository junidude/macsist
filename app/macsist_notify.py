"""Distributed-notification poster (M12) — built as Contents/MacOS/macsist_notify
via py2app extra_scripts, sharing the bundle's runtime (PyObjC included).

Usage: macsist_notify <notification-name> [<payload-string>]
e.g. `macsist settings`           -> macsist_notify com.macsist.showSettings
     `macsist propose "리뷰"`     -> macsist_notify com.macsist.assistant.propose "리뷰"
The optional payload is delivered as userInfo {"payload": <string>} (M14).
"""

import sys

from Foundation import NSDistributedNotificationCenter


def main():
    name = sys.argv[1]
    user_info = {"payload": sys.argv[2]} if len(sys.argv) > 2 else None
    NSDistributedNotificationCenter.defaultCenter() \
        .postNotificationName_object_userInfo_deliverImmediately_(
            name, None, user_info, True)


if __name__ == "__main__":
    main()
