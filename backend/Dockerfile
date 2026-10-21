FROM python:3.12-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    docker \
    "PyJWT[crypto]>=2.10,<3" \
    tzdata

COPY plans.py main.py classrooms.py identity.py admin.py storage.py network_guard.py disk_guard.py desktop_runtime.py packet_capture.py cse-seccomp.json /app/

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
