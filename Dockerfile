FROM python:3.11-slim

WORKDIR /app

# Unbuffered output so docker logs show errors immediately
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install --with-deps chromium

COPY . .
ENV PYTHONPATH=/app

EXPOSE 9000
CMD ["python", "main.py"]
