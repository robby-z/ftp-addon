ARG BUILD_FROM=ghcr.io/home-assistant/base-debian:trixie
FROM ${BUILD_FROM}

ARG BUILD_ARCH
ARG BUILD_VERSION=1.0.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        openssl \
        libpam-pwdfile \
        passwd \
        python3 \
        vsftpd \
    && rm -rf /var/lib/apt/lists/*

COPY rootfs /

RUN chmod 0755 /usr/local/bin/reolink-ftps \
        /etc/services.d/reolink-ftps/run \
        /etc/services.d/reolink-ftps/finish

LABEL \
    io.hass.type="app" \
    io.hass.name="Reolink FTPS Server" \
    io.hass.version="${BUILD_VERSION}" \
    org.opencontainers.image.title="Home Assistant App: Reolink FTPS Server" \
    org.opencontainers.image.description="Secure explicit FTPS server and Ingress recording browser for Reolink cameras." \
    org.opencontainers.image.source="https://github.com/robby-z/ftp-addon" \
    org.opencontainers.image.licenses="MIT"
