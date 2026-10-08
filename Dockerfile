FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 DATABASE_PATH=/data/grokcord.db
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY grokcord ./grokcord
VOLUME /data
CMD ["python", "-m", "grokcord"]
