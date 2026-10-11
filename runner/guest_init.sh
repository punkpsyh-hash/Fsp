#!/bin/sh
set -eu
export PATH=/usr/local/bin:/bin
export LD_LIBRARY_PATH=/usr/local/lib:/lib/x86_64-linux-gnu:/usr/lib/x86_64-linux-gnu
mount -t devtmpfs devtmpfs /dev
mount -t proc -o nosuid,nodev,noexec,hidepid=2 proc /proc
mount -t sysfs -o ro,nosuid,nodev,noexec sysfs /sys
mount -t tmpfs -o size=64m,nosuid,nodev tmpfs /work
mount -t tmpfs -o size=8m,nosuid,nodev,noexec tmpfs /tmp
chmod 1777 /tmp
exec python3.12 -I -B /guest_agent.py
