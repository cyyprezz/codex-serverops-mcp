#!/bin/sh
set -eu

password_file=/run/secrets/serverops_password
if [ ! -r "$password_file" ]; then
    echo "missing generated spike password file" >&2
    exit 2
fi

password=$(cat "$password_file")
printf 'serverops:%s\n' "$password" | chpasswd
unset password

if [ -r /run/secrets/serverops_authorized_key ]; then
    cp /run/secrets/serverops_authorized_key /home/serverops/.ssh/authorized_keys
    chown serverops:serverops /home/serverops/.ssh/authorized_keys
    chmod 0600 /home/serverops/.ssh/authorized_keys
fi

exec /usr/sbin/sshd -D -e

