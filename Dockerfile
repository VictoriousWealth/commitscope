FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates nodejs npm openjdk-17-jdk-headless \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY src ./src
COPY examples ./examples
COPY docs ./docs
COPY scripts ./scripts
COPY tools ./tools
RUN mkdir -p /app/tools/java/bin \
    && javac -cp /app/tools/java/lib/javaparser-core-3.27.1.jar \
      -d /app/tools/java/bin \
      /app/tools/java/src/JavaMetricsMain.java

CMD ["python", "-m", "commitscope.main", "run", "--config", "/app/examples/config.dev.json"]
