# Task CRUD API — Python 3.14 (standard build, GIL enabled).
# 100% stdlib: no pip, no extra packages. The base image IS the runtime (the
# equivalent of having python3 installed locally), not an app dependency.
FROM python:3.14-slim

WORKDIR /app

# Narrow COPY: only the app package (tests/ and *.db stay out; .dockerignore
# reinforces it).
COPY app/ ./app/

# sqlite creates the file but not the directory; the volume mounts at /data.
RUN mkdir -p /data

EXPOSE 8000

# --host 0.0.0.0: reachable through the published port (with "localhost" the
# container would only listen on its loopback and the host NAT wouldn't reach it).
CMD ["python", "-m", "app", "--host", "0.0.0.0", "--port", "8000", "--db", "/data/tasks.db"]
