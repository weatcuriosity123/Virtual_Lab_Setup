ARG CSE_BASE=linux-lab:cse-readonly-candidate
FROM ${CSE_BASE}
USER root
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends strace \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
