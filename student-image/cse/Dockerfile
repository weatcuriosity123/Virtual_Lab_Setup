# Candidate image: validate desktop streaming and IDE launch before classroom use.
# Pass an immutable digest using scripts/build-cse-image.sh.
ARG WEBTOP_BASE=lscr.io/linuxserver/webtop:debian-xfce
FROM ${WEBTOP_BASE}
USER root
ENV TZ=Asia/Kolkata
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc -o /tmp/microsoft.asc \
    && gpg --dearmor --batch --yes -o /usr/share/keyrings/microsoft.gpg /tmp/microsoft.asc \
    && chmod 644 /usr/share/keyrings/microsoft.gpg \
    && printf '%s\n' 'Types: deb' 'URIs: https://packages.microsoft.com/repos/code' \
       'Suites: stable' 'Components: main' 'Architectures: amd64 arm64' \
       'Signed-By: /usr/share/keyrings/microsoft.gpg' > /etc/apt/sources.list.d/cse-vscode.sources \
    && printf '%s\n' 'wireshark-common wireshark-common/install-setuid boolean false' \
       'code code/add-microsoft-repo boolean false' | debconf-set-selections \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       code build-essential cmake gdb \
       python3 python3-pip python3-venv python3-numpy python3-pandas python3-matplotlib \
       default-jdk maven nodejs npm \
       git gh openssh-client jq wget zip unzip nano vim-tiny \
       sqlite3 postgresql-client default-mysql-client \
       iproute2 iputils-ping traceroute dnsutils netcat-openbsd \
       tcpdump wireshark tshark htop procps file less man-db \
    && mkdir -p /opt/cse-lab \
    && dpkg-query -W > /opt/cse-lab/packages.tsv \
    && rm -f /tmp/microsoft.asc \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
COPY smoke.sh /usr/local/bin/cse-smoke
COPY README.md /opt/cse-lab/README.md
RUN chmod 755 /usr/local/bin/cse-smoke && /usr/local/bin/cse-smoke
# Retain the upstream entrypoint and its user/desktop initialization.
# No Docker socket, privileged mode, or live packet-capture grants are added.
