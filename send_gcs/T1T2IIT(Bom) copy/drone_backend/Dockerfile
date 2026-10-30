FROM python:3.10-slim

WORKDIR /app

# Install system dependencies (OpenGL for OpenCV)
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend logic
COPY . .

# Expose FastAPI port
EXPOSE 8000

# Optional: Run the ingestion and backend together (in production recommend using supervisor or multiple containers)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
