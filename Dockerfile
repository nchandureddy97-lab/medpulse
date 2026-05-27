FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy application code
COPY server.py .
COPY public/ public/

# Cloud Run sets PORT env var automatically
ENV PORT=8080

EXPOSE 8080

# Use gunicorn for production (not Flask dev server)
CMD exec gunicorn --bind :$PORT --workers 2 --threads 4 --timeout 120 server:app
