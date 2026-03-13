#!/bin/sh
set -eu

mkdir -p /opt/ghidra_projects /opt/ghidraaas/output /opt/ghidraaas/samples /opt/ghidraaas/ida_samples
chown -R ghidra:ghidra /opt/ghidra_projects /opt/ghidraaas

export JAVA_HOME="${JAVA_HOME:-/opt/java/openjdk}"
export PATH="${JAVA_HOME}/bin:${PATH}"

exec su -m -s /bin/sh ghidra -c "gunicorn -w 1 -k gthread --threads 4 -t 1200 -b 0.0.0.0:8080 flask_api:app"
