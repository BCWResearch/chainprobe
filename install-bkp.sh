#!/bin/bash

set -e

echo "🌐 Multi-Chain Exporter Setup Script (Global Python)"

# Install required Python packages globally
echo "📦 Installing required Python packages globally..."
sudo pip3 install --upgrade pip
sudo pip3 install httpx prometheus_client toml psutil web3 schedule

# ---------------------------
# Gather config input
# ---------------------------
echo "🛠️  Exporter Configuration"
read -p "Enter protocol (cosmos / evm / other): " protocol
read -p "Is this a validator node? (yes/no): " is_validator
read -p "Enter Prometheus metrics port (default 3000): " metrics_port
metrics_port=${metrics_port:-3000}
read -p "Enter comma-separated systemd binary names (or leave blank): " binary_input
read -p "Enter comma-separated Docker container names (or leave blank): " docker_input

# ---------------------------
# Generate config.toml
# ---------------------------
echo "📝 Writing config.toml..."
cat > config.toml <<EOF
protocol = "$protocol"
metrics_port = $metrics_port
EOF

# ---------------------------
# Cosmos-specific config
# ---------------------------
if [[ "$protocol" == "cosmos" ]]; then
  echo "🔗 Cosmos configuration"
  echo -e "\nhost = \"http://localhost\"\nrest_port = 1317" >> config.toml

  if [[ "$is_validator" == "yes" ]]; then
    read -p "Enter valcons_address: " valcons_address
    read -p "Enter valoper_address: " valoper_address
    read -p "Enter account_address: " account_address
    read -p "Enter scaling factor (default 1e18): " scaling_factor
    scaling_factor=${scaling_factor:-1e18}

cat >> config.toml <<EOF

valcons_address = "$valcons_address"
valoper_address = "$valoper_address"
account_address = "$account_address"

[metrics.latest_block]
path = "/cosmos/base/tendermint/v1beta1/blocks/latest"
description = "Latest block height"

[metrics.validator_missed_blocks_total]
path = "/cosmos/slashing/v1beta1/signing_infos/\${valcons_address}"
description = "Total missed blocks"

[metrics.validator_is_jailed]
path = "/cosmos/staking/v1beta1/validators/\${valoper_address}"
description = "Is validator jailed"

[metrics.validator_is_active]
path = "/cosmos/staking/v1beta1/validators/\${valoper_address}"
description = "Is validator active"

[metrics.validator_commission_rate]
path = "/cosmos/staking/v1beta1/validators/\${valoper_address}"
description = "Validator commission rate"

[metrics.validator_commission_amount]
path = "/cosmos/distribution/v1beta1/validators/\${valoper_address}/commission"
description = "Total commission amount"
scaling_factor = $scaling_factor

[metrics.validator_rewards_total]
path = "/cosmos/distribution/v1beta1/delegators/\${account_address}/rewards/\${valoper_address}"
description = "Validator total rewards"
scaling_factor = $scaling_factor
EOF

  else
cat >> config.toml <<EOF

[metrics.latest_block]
path = "/cosmos/base/tendermint/v1beta1/blocks/latest"
description = "Latest block height"
EOF
  fi

# ---------------------------
# EVM-specific config
# ---------------------------
elif [[ "$protocol" == "evm" ]]; then
cat >> config.toml <<EOF

[default]
rpcaddress = "http://localhost:8545"

[metrics.latest_block]
description = "Latest block number of the chain"

[metrics.peer_count]
description = "Number of peers"

[metrics.syncing]
description = "Syncing status"

[metrics.blocks_to_sync]
description = "Remaining blocks to sync"

[metrics.network_name]
description = "Network chain ID or name"

[metrics.net_listening]
description = "Whether client is accepting connections"
EOF
fi

# ---------------------------
# Add binaries (systemd services)
# ---------------------------
if [[ -n "$binary_input" ]]; then
  echo -e "\n[binaries]" >> config.toml
  IFS=',' read -ra BIN_ARRAY <<< "$binary_input"
  for alias in "${BIN_ARRAY[@]}"; do
    alias_trimmed=$(echo "$alias" | xargs)
    unit_path=$(systemctl show "${alias_trimmed}.service" -p FragmentPath --value 2>/dev/null)
    safe_alias="\"$alias_trimmed\""

    if [[ -n "$unit_path" && -f "$unit_path" ]]; then
      echo "$safe_alias = \"$unit_path\"" >> config.toml
      echo "[✓] Found unit for $alias_trimmed → $unit_path"
    else
      echo "[!] Could not find unit file for $alias_trimmed. Skipping..."
    fi
  done
fi

# ---------------------------
# Add Docker containers
# ---------------------------
if [[ -n "$docker_input" ]]; then
  echo -e "\n[docker_containers]" >> config.toml
  IFS=',' read -ra DOCKER_ARRAY <<< "$docker_input"
  for alias in "${DOCKER_ARRAY[@]}"; do
    alias_trimmed=$(echo "$alias" | xargs)
    safe_alias="\"$alias_trimmed\""
    echo "$safe_alias = true" >> config.toml
  done
fi

echo "✅ config.toml created."

# ---------------------------
# Create systemd service
# ---------------------------
echo "🔧 Creating systemd service: chainprobe"

cat > /etc/systemd/system/chainprobe.service <<EOF
[Unit]
Description=chainprobe Multi-Protocol Exporter
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$(pwd)
ExecStart=/usr/bin/python3 $(pwd)/main.py --config config.toml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# ---------------------------
# Enable + start service
# ---------------------------
echo "🟢 Starting chainprobe service..."
systemctl daemon-reexec
systemctl daemon-reload
systemctl enable chainprobe
systemctl restart chainprobe

# ---------------------------
# Done!
# ---------------------------
echo -e "\n🚀 chainprobe is installed and running!"
echo "Check status:  sudo systemctl status chainprobe"
echo "Logs:          journalctl -u chainprobe -f"
echo "Metrics:       curl http://localhost:$metrics_port/metrics"
