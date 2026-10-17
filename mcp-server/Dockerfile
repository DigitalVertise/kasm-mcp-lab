FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

# uid 1000 matches kasm-user in the desktops so /shared files stay writable by both
RUN useradd --uid 1000 --create-home mcp && mkdir -p /shared && chown mcp /shared
USER mcp

EXPOSE 8811
CMD ["python", "-m", "app.server"]
