#!/bin/bash
set -e

cd /home/ubuntu/sofiatech_aiops/aiops-remediation

echo "$(date): Starting scheduled retraining..."

./venv/bin/python3 retrain_on_ec2.py

echo "$(date): Retraining complete. Restarting detection engine to load the new model..."

sudo systemctl restart aiops-cpu-engine

echo "$(date): aiops-cpu-engine restarted with updated model."
