FROM codex-serverops-spike:local

RUN printf '%s\n' \
      'Banner /etc/ssh/serverops-askpass-banner' \
      'PrintMotd yes' \
      >> /etc/ssh/sshd_config \
    && printf '%s\n' \
      'password:' \
      'Enter passphrase for key C:\Users\user\.ssh\id_ed25519:' \
      '[sudo] password for deploy:' \
      'Are you sure you want to continue connecting (yes/no/[fingerprint])?' \
      > /etc/ssh/serverops-askpass-banner \
    && cp /etc/ssh/serverops-askpass-banner /etc/motd
