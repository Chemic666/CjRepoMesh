# Copyright (c) 2026 CjRepoMesh contributors.
# Licensed under the Apache License, Version 2.0.

FROM ubuntu:22.04

LABEL org.opencontainers.image.title="CjRepoMesh" \
      org.opencontainers.image.description="Cangjie private and proxy repository" \
      org.opencontainers.image.licenses="Apache-2.0"

RUN groupadd --gid 10001 cjrepo \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin cjrepo \
    && mkdir -p /var/lib/cjrepo /usr/local/lib/cangjie \
    && chown -R cjrepo:cjrepo /var/lib/cjrepo

COPY .build-context/cjrepo /usr/local/bin/cjrepo
COPY .build-context/libcangjie-runtime.so /usr/local/lib/cangjie/libcangjie-runtime.so
COPY .build-context/libboundscheck.so /usr/local/lib/cangjie/libboundscheck.so

RUN chmod 0555 /usr/local/bin/cjrepo \
    && chmod 0444 /usr/local/lib/cangjie/*.so

ENV LD_LIBRARY_PATH=/usr/local/lib/cangjie \
    CJREPO_ADDRESS=0.0.0.0 \
    CJREPO_PORT=8080 \
    CJREPO_STORAGE=/var/lib/cjrepo

USER 10001:10001
WORKDIR /var/lib/cjrepo
EXPOSE 8080

HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=12 \
  CMD ["/bin/bash", "-c", "exec 3<>/dev/tcp/127.0.0.1/8080; printf 'GET /health HTTP/1.0\\r\\n\\r\\n' >&3; grep -q '200 OK' <&3"]

ENTRYPOINT ["/usr/local/bin/cjrepo"]
