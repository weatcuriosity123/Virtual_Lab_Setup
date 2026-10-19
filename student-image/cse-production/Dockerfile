ARG CSE_BASE=linux-lab:cse-readonly-candidate
FROM ${CSE_BASE}
USER root
COPY code /usr/local/bin/code
COPY launchers.py /opt/cse-readonly/launchers.py
RUN chmod 755 /usr/local/bin/code && python3 /opt/cse-readonly/launchers.py
LABEL lab.runtime.profile=cse-readonly-v1
