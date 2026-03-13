# This Dockerfile is a modified version of https://github.com/bskaggs/ghidra-docker/blob/master/Dockerfile

FROM eclipse-temurin:11-jdk
LABEL maintainer="anmarcel <anmarcel@cisco.com>"

ARG GHIDRA_VERSION=9.1.2_PUBLIC_20200212
ARG GHIDRA_URL=https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_9.1.2_build/ghidra_9.1.2_PUBLIC_20200212.zip
RUN useradd -m ghidra && \
    mkdir -p /srv/repositories && \
    chown -R ghidra: /srv/repositories
COPY --chown=ghidra:ghidra launch.sh.patch /tmp/

RUN apt-get update \
  && apt-get install -y python3-pip python3-dev unzip \
  && cd /usr/local/bin \
  && ln -s /usr/bin/python3 python

RUN apt-get install -y libgtk2.0-0 libidn12 libglu1-mesa

WORKDIR /opt
RUN apt-get update && apt-get install -y wget gettext-base patch && \
    wget -q -O ghidra.zip ${GHIDRA_URL}
RUN unzip -tq ghidra.zip >/dev/null && \
    unzip ghidra.zip && \
    rm ghidra.zip && \
    ln -s ghidra* ghidra && \
    cd ghidra && \
    patch -p0 < /tmp/launch.sh.patch && \ 
    rm -rf docs && \
    cd .. && \
    chown -R ghidra: ghidra*

COPY requirements.txt /opt/requirements.txt
RUN pip3 install --break-system-packages -r /opt/requirements.txt

# Create /opt/ghidraaas working folder
RUN mkdir -p /opt/ghidraaas
RUN chown ghidra:ghidra /opt/ghidraaas

RUN mkdir -p /opt/ghidra_projects
RUN chown ghidra:ghidra /opt/ghidra_projects

WORKDIR /opt/ghidraaas

ENV ghidra_home=/opt/ghidra

COPY --chown=ghidra:ghidra flask_api.py flask_api.py
COPY --chown=ghidra:ghidra ghidra_plugins /opt/ghidra_plugins/
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN mkdir /opt/ghidraaas/config
COPY --chown=ghidra:ghidra config/docker_config.json /opt/ghidraaas/config/config.json

RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
