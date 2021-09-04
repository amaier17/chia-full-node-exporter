#!/bin/bash

CHIA_USER=${CHIA_USER:-$USER}
CHIA_GROUP=${CHIA_GROUP:-$CHIA_USER}
CHIA_PATH=${CHIA_PATH:-/opt/chia/chia-blockchain}
INSTALL_LOC=${INSTALL_LOC:-/etc/systemd/system}
FULLNODE=${FULLNODE:-localhost}
WALLET=${WALLET:-localhost}
HARVESTER=${HARVESTER:-localhost}
FARMER=${FARMER:-localhost}
PORT=${PORT:-9825}

SCRIPT_DIR=$(readlink -f $(dirname "$0"))

pushd $CHIA_PATH
. ./activate
pip3 install -r $SCRIPT_DIR/requirements.txt
deactivate
popd

echo "Installing $INSTALL_LOC/chia-exporter.service with user $CHIA_USER, group $CHIA_GROUP, and using the blockchain installed at $CHIA_PATH"
sed "s|CHIA_PATH|$CHIA_PATH|g;s|CHIA_USER|$CHIA_USER|g;s|CHIA_GROUP|$CHIA_GROUP|g;s|EXPORTER_PATH|$SCRIPT_DIR|g;s|FULLNODE|$FULLNODE|g;s|WALLET|$WALLET|g;s|HARVESTER|$HARVESTER|g;s|FARMER|$FARMER|g;s|PORT|$PORT|g" "$SCRIPT_DIR/chia-exporter.service.init" > "$SCRIPT_DIR/chia-exporter.service"
sudo ln -s $SCRIPT_DIR/chia-exporter.service $INSTALL_LOC/ -f

sudo systemctl daemon-reload
sudo systemctl enable chia-exporter.service
sudo systemctl start chia-exporter.service

