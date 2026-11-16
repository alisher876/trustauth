FROM python:3.11-slim

WORKDIR /app

# Install dependencies first so Docker can cache this layer when only code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# --reload restarts the server when code changes (development only).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
