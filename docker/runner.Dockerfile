ARG PYTHON_IMAGE=python:3.12-slim@sha256:6c4dd321d176d61ea848dc8c73a4f7dbae8f70e0ee48bb411ea2f045b599fa8e
ARG NODE_IMAGE=node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392
FROM ${NODE_IMAGE} AS node
FROM ${PYTHON_IMAGE} AS guest
# Signed Debian packages; exact kernel, BusyBox and cpio versions are intentional.
RUN apt-get update && apt-get install -y --no-install-recommends \
    linux-image-amd64=6.12.111-1 busybox-static=1:1.37.0-6+b9 cpio=2.15+dfsg-2 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/LICENSE /build/node-LICENSE
COPY runner/build_guest.py runner/guest_init.sh runner/guest_agent.py runner/sql_guest.py /build/runner/
RUN python /build/runner/build_guest.py

FROM ${PYTHON_IMAGE} AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    qemu-system-x86=1:10.0.13+ds-0+deb13u1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=guest /build/guest/ /opt/fsp-guest/
RUN dpkg-query -W -f '${binary:Package}=${Version}\n' > /opt/fsp-guest/runtime-debian-packages.txt \
    && cp /usr/share/doc/qemu-system-x86/copyright /opt/fsp-guest/licenses/QEMU-copyright
COPY runner/ runner/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FSP_RUNNER_ACCEL=kvm
USER 10001:10001
CMD ["python", "-m", "runner.worker"]
