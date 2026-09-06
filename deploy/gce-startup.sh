#!/bin/bash
set -eux
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y docker.io docker-compose-v2 git
systemctl enable --now docker
if id ubuntu >/dev/null 2>&1; then
  usermod -aG docker ubuntu
fi
