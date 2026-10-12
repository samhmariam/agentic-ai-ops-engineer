FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock .python-version ./

# Install dependencies only — project source not available yet
RUN uv sync --frozen --no-install-project

# Copy the rest of the project
COPY . .

# Install the project itself now that src/ is present
RUN uv sync --frozen

# uv run realthor is the entry point
ENTRYPOINT ["uv", "run", "realthor"]
CMD ["--help"]
