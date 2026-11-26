ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM $BUILD_FROM

ARG BUILD_VERSION
RUN mkdir -p /integration \
    && curl -fsSL "https://github.com/42p/ha-nuki-opener-ble/archive/refs/tags/v${BUILD_VERSION}.tar.gz" \
    | tar xz --strip-components=3 -C /integration "ha-nuki-opener-ble-${BUILD_VERSION}/custom_components/nuki_opener_ble" \
    && test -f /integration/manifest.json

COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
