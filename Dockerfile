FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# OS deps (Playwright + general)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# uv install
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# Copy dependency files first (better layer cache)
COPY pyproject.toml /app/pyproject.toml

# Install python deps
RUN uv sync --no-dev

# Install Playwright browsers + deps
# --with-deps will install system deps on Debian/Ubuntu base images
RUN uv run playwright install --with-deps chromium

# Copy app
COPY main.py /app/main.py
COPY search_scrape /app/search_scrape

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
