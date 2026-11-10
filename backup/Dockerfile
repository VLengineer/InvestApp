FROM alpine:3.19

RUN apk add --no-cache \
    restic \
    postgresql16-client \
    bash \
    curl \
    tzdata

COPY entrypoint.sh /entrypoint.sh
COPY backup.sh /backup.sh
COPY restore.sh /restore.sh

RUN chmod +x /entrypoint.sh /backup.sh /restore.sh

ENTRYPOINT ["/entrypoint.sh"]
