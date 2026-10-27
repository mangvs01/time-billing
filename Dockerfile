FROM python:3.12-slim
WORKDIR /app
# pip is a build tool only, but keep it current ; runtime dependencies are pinned in requirements.lock (requirements.txt = direct dependencies)
RUN pip install --no-cache-dir --upgrade "pip>=26.2"
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY app ./app
ENV DB_PATH=/data/timebilling.db PYTHONDONTWRITEBYTECODE=1
# RC11: the service no longer runs as root. The data folder of the host must belong to uid 10001 (done by procedure/40-deploy.sh).
RUN groupadd -r -g 10001 tb && useradd -r -u 10001 -g tb -M -d /nonexistent -s /usr/sbin/nologin tb && mkdir -p /data && chown tb:tb /data
USER 10001:10001
EXPOSE 8000
CMD ["gunicorn","-w","2","--worker-class","gthread","--threads","8","--worker-tmp-dir","/dev/shm","--timeout","60","--graceful-timeout","20","-b","0.0.0.0:8000","app.app:APP"]
