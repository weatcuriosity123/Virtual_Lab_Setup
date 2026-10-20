ARG CSE_BASE=linux-lab:cse-readonly-candidate
FROM ${CSE_BASE}
USER root
COPY code /usr/local/bin/code
COPY launchers.py /opt/cse-readonly/launchers.py
COPY curiosity4u-wallpaper.png /usr/share/backgrounds/curiosity4u-wallpaper.png
COPY set-wallpaper.py /opt/cse-readonly/set-wallpaper.py
COPY curiosity4u-wallpaper.desktop /etc/xdg/autostart/curiosity4u-wallpaper.desktop
RUN chmod 644 /usr/share/backgrounds/curiosity4u-wallpaper.png /opt/cse-readonly/set-wallpaper.py /etc/xdg/autostart/curiosity4u-wallpaper.desktop
RUN chmod 755 /usr/local/bin/code && python3 /opt/cse-readonly/launchers.py
LABEL lab.runtime.profile=cse-readonly-v1
