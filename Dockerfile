# One image for checks now; the desk's services (UI, review queue) are added as they are built.
FROM python:3.12-slim
WORKDIR /app
# Streamlit puts only the script's folder (agents/ui) on sys.path; the packages live at /app.
ENV PYTHONPATH=/app
RUN apt-get update && apt-get install -y --no-install-recommends make && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY . .
CMD ["make", "check"]
