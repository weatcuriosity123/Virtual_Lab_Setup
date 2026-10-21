# Build through scripts/build-programming-lite.sh using a locally pinned Webtop image.
ARG WEBTOP_BASE
FROM ${WEBTOP_BASE}
USER root
ENV TZ=Asia/Kolkata
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       python3 python3-venv gcc g++ make libc6-dev nano xfce4-terminal \
    && for package in chromium chromium-common chromium-sandbox firefox-esr firefox code wireshark wireshark-qt tshark; do \
         if dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed'; then \
           DEBIAN_FRONTEND=noninteractive apt-get purge -y "$package"; \
         fi; \
       done \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
COPY prepare.py /opt/cse-readonly/prepare.py
RUN python3 /opt/cse-readonly/prepare.py
COPY curiosity4u-wallpaper.png /usr/share/backgrounds/curiosity4u-wallpaper.png
COPY set-wallpaper.py /opt/cse-readonly/set-wallpaper.py
COPY curiosity4u-wallpaper.desktop /etc/xdg/autostart/curiosity4u-wallpaper.desktop
COPY smoke.sh /usr/local/bin/programming-lite-smoke
RUN chmod 755 /usr/local/bin/programming-lite-smoke \
    && chmod 644 /usr/share/backgrounds/curiosity4u-wallpaper.png /opt/cse-readonly/set-wallpaper.py /etc/xdg/autostart/curiosity4u-wallpaper.desktop \
    && /usr/local/bin/programming-lite-smoke
LABEL lab.runtime.profile="programming-lite-readonly-v1"
# Preserve upstream desktop entrypoint. No image is registered/promoted automatically.
