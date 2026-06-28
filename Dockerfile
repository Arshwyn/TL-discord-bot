# Use a slim Python 3.12 base
FROM python:3.12-slim

# Copy the uv binary directly from the official astral image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Optimize uv for container environments
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Copy dependency management files first for layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies (this creates a .venv automatically in /app)
# --frozen ensures it uses exact versions from uv.lock
# --no-install-project skips installing the source code itself for this layer
RUN uv sync --frozen --no-install-project

# Copy the rest of the bot's source code
COPY . .

# Run the bot using uv's managed environment
CMD ["uv", "run", "bot.py"]