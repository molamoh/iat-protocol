FROM python:3.12-slim

ARG IAT_BUILD_VERSION=development

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV IAT_BUILD_VERSION=${IAT_BUILD_VERSION}

LABEL org.opencontainers.image.revision=${IAT_BUILD_VERSION}

WORKDIR /app

RUN apt-get update && apt-get install -y curl gcc build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 10000

CMD ["sh", "-c", "uvicorn iat.api.agent_b_api:app --host 0.0.0.0 --port ${PORT:-10000}"]
