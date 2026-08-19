ARG BUILD_FROM=ghcr.io/home-assistant/base:3.24
FROM ${BUILD_FROM}

ARG BUILD_ARCH
ARG BUILD_VERSION=1.0.0

RUN apk add --no-cache \
        openssl~3.5 \
        python3~3.14 \
        shadow~4.18 \
        vsftpd~3.0

COPY rootfs /

RUN chmod 0755 /usr/local/bin/reolink-ftps \
        /etc/services.d/reolink-ftps/run \
        /etc/services.d/reolink-ftps/finish

LABEL \
    io.hass.type="app" \
    io.hass.name="Reolink FTPS Server" \
    io.hass.version="${BUILD_VERSION}" \
    org.opencontainers.image.title="Home Assistant App: Reolink FTPS Server" \
    org.opencontainers.image.description="Secure explicit FTPS server for Reolink cameras, powered by vsftpd." \
    org.opencontainers.image.source="https://github.com/robby-z/ftp-addon" \
    org.opencontainers.image.licenses="MIT"
