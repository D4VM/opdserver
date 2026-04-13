FROM python:3.12-slim

# System libs needed by lxml, Pillow, python-magic, and PyMuPDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 \
    libxslt1.1 \
    libmagic1 \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Runtime data directories (overridden by volume mounts)
RUN mkdir -p books covers

EXPOSE 8000

CMD ["python3", "main.py"]
