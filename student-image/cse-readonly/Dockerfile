# Experimental derivative only; never overwrite the working classroom image.
ARG CSE_BASE=linux-lab:cse-candidate
FROM ${CSE_BASE}
USER root
COPY prepare.py /opt/cse-readonly/prepare.py
RUN python3 /opt/cse-readonly/prepare.py
