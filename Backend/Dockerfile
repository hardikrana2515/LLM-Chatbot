# 1. Base image
FROM python:3.12-slim

# 2. Working directory
WORKDIR /app

#Add app user
RUN useradd --create-home --shell /bin/bash appuser

# 3. Python environment configuration
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 4. Copy production dependencies
COPY requirements.txt .

# 5. Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# 6. Copy application source code
COPY --chown=appuser:appuser . .

USER appuser
# 7. Document application port
EXPOSE 5000

# 8. Start FastAPI
CMD ["uvicorn","main:app","--host","0.0.0.0","--port","5000"]


