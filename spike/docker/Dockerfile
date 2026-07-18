FROM alpine:3.22

RUN apk add --no-cache bash coreutils openssh-server python3 py3-virtualenv sudo \
    && adduser -D -s /bin/bash serverops \
    && printf 'serverops ALL=(ALL:ALL) ALL\n' > /etc/sudoers.d/serverops \
    && chmod 0440 /etc/sudoers.d/serverops \
    && mkdir -p /run/sshd /home/serverops/.ssh /opt/app \
    && chown -R serverops:serverops /home/serverops /opt/app \
    && chmod 0700 /home/serverops/.ssh \
    && python3 -m venv /opt/app/.venv \
    && chown -R serverops:serverops /opt/app/.venv \
    && ssh-keygen -A

COPY entrypoint.sh /usr/local/bin/serverops-spike-entrypoint
RUN chmod 0755 /usr/local/bin/serverops-spike-entrypoint

EXPOSE 22
ENTRYPOINT ["/usr/local/bin/serverops-spike-entrypoint"]

