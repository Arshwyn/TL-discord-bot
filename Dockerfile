# Use a slim Python 3.12 base, pinned to an exact patch tag on Debian 13 (trixie)
FROM python:3.12.16-slim-trixie

# Copy the uv binary directly from the official astral image
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/

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
# --no-cache keeps the uv cache out of the image layer
RUN uv sync --frozen --no-install-project --no-cache

# Copy the rest of the bot's source code
COPY . .

# Create an unprivileged user; source and venv stay root-owned and read-only to it,
# only /app/data (the SQLite volume) is owned by the bot user
RUN groupadd --system --gid 10001 bot \
    && useradd --system --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin bot \
    && mkdir -p /app/data \
    && chown 10001:10001 /app/data

ENV PYTHONDONTWRITEBYTECODE=1

USER 10001:10001

# Run the bot using uv's managed environment
CMD ["uv", "run", "bot.py"]