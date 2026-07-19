FROM python:3.13.14-slim-trixie@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BBM_DATA_DIR=/data

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client openssh-server openssl borgbackup tzdata \
    && borg_version="$(borg --version 2>/dev/null | sed -n 's/.*\([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' | head -n1)" \
    && test -n "$borg_version" \
    && dpkg --compare-versions "$borg_version" ge 1.4.0 \
    && dpkg --compare-versions "$borg_version" lt 2.0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY VERSION ./VERSION
COPY README.md INSTALLATION.md RELEASE_NOTES.md ./
COPY app ./app
COPY docker/entrypoint.sh /usr/local/bin/bbm-entrypoint
COPY docker/borg-serve.sh /usr/local/bin/bbm-borg-serve
COPY docker/sshd_config /etc/ssh/sshd_config

RUN groupadd --gid 1000 borg \
    && useradd --uid 1000 --gid borg --home-dir /repositories --shell /bin/sh borg \
    && passwd -d borg \
    && mkdir -p /data /repositories /run/sshd \
    && chmod 755 /usr/local/bin/bbm-entrypoint /usr/local/bin/bbm-borg-serve

EXPOSE 8443 2222
ENTRYPOINT ["/usr/local/bin/bbm-entrypoint"]
