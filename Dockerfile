FROM python:3.13-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Install Playwright Chromium and all its system dependencies
RUN uv run playwright install --with-deps chromium

# Copy application code
COPY . .

# Install the package
RUN uv pip install --no-deps -e .

EXPOSE 8080

CMD ["uv", "run", "uvicorn", "proxy_voter.main:app", "--host", "0.0.0.0", "--port", "8080"]
