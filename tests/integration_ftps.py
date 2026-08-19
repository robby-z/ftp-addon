#!/usr/bin/env python3
"""Black-box FTPS checks against a running test container."""

import ftplib
import io
import os
import ssl
import sys
import time

HOST = os.environ.get("FTPS_HOST", "127.0.0.1")
PORT = int(os.environ.get("FTPS_PORT", "2121"))


def tls_login(username, password):
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    ftp = ftplib.FTP_TLS(context=context, timeout=10)
    ftp.connect(HOST, PORT)
    ftp.login(username, password)
    ftp.prot_p()
    ftp.set_pasv(True)
    assert ftp.sock.version() in {"TLSv1.2", "TLSv1.3"}, ftp.sock.version()
    return ftp


def expect_ftp_error(action, label):
    try:
        action()
    except ftplib.Error:
        return
    raise AssertionError(f"Expected FTP rejection: {label}")


def main():
    deadline = time.time() + 60
    while True:
        try:
            ftp = tls_login("camera_front", "front-secret")
            break
        except (OSError, EOFError, ftplib.Error, ssl.SSLError):
            if time.time() >= deadline:
                raise
            time.sleep(1)

    ftp.mkd("events")
    ftp.storbinary("STOR events/upload.tmp", io.BytesIO(b"first"))
    ftp.rename("events/upload.tmp", "events/recording.mp4")
    ftp.storbinary("STOR events/recording.mp4", io.BytesIO(b"replacement"))
    output = io.BytesIO()
    ftp.retrbinary("RETR events/recording.mp4", output.write)
    assert output.getvalue() == b"replacement"
    ftp.delete("events/recording.mp4")
    ftp.rmd("events")
    expect_ftp_error(lambda: ftp.cwd("../garden"), "chroot traversal")
    ftp.quit()

    garden = tls_login("camera_garden", "garden-secret")
    garden.storbinary("STOR garden-only.mp4", io.BytesIO(b"garden"))
    garden.quit()

    front = tls_login("camera_front", "front-secret")
    expect_ftp_error(lambda: front.retrbinary("RETR garden-only.mp4", lambda _: None), "cross-user file read")
    front.storbinary("STOR viewer-visible.mp4", io.BytesIO(b"front"))
    front.quit()

    viewer = tls_login("viewer", "viewer-secret")
    downloaded = io.BytesIO()
    viewer.retrbinary("RETR viewer-visible.mp4", downloaded.write)
    assert downloaded.getvalue() == b"front"
    expect_ftp_error(lambda: viewer.storbinary("STOR forbidden.mp4", io.BytesIO(b"no")), "read-only upload")
    expect_ftp_error(lambda: viewer.mkd("forbidden"), "read-only mkdir")
    expect_ftp_error(lambda: viewer.delete("viewer-visible.mp4"), "read-only delete")
    expect_ftp_error(lambda: viewer.rename("viewer-visible.mp4", "renamed.mp4"), "read-only rename")
    viewer.quit()

    plain = ftplib.FTP(timeout=10)
    plain.connect(HOST, PORT)
    expect_ftp_error(lambda: plain.login("camera_front", "front-secret"), "plain FTP login")
    plain.close()
    print("FTPS integration checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
