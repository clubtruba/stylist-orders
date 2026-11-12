FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client passwd && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 1000 tunnel && useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin tunnel
USER tunnel
CMD ["ssh", "-F", "/dev/null", "-i", "/keys/id_ed25519", "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=/keys/known_hosts", "-o", "UpdateHostKeys=no", "-o", "ExitOnForwardFailure=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3", "-o", "LogLevel=ERROR", "-NT", "-L", "0.0.0.0:8080:127.0.0.1:18080", "stylist-browser-tunnel@82.165.142.124"]
