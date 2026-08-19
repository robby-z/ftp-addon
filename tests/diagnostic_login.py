#!/usr/bin/env python3
"""Perform one FTPS login attempt without printing credentials."""

import ftplib
import ssl
import sys


def main():
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    ftp = ftplib.FTP_TLS(context=context, timeout=10)
    try:
        ftp.connect("127.0.0.1", 2121)
        ftp.login("camera_front", "front-secret")
        print(f"Diagnostic login succeeded with {ftp.sock.version()}")
        return 0
    except Exception as err:  # noqa: BLE001 - diagnostic must report the protocol failure
        print(f"Diagnostic login failed: {type(err).__name__}: {err}")
        return 1
    finally:
        try:
            ftp.close()
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
