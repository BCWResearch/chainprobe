# 🔗 ChainProbe: Multi-Chain Prometheus Exporter

**ChainProbe** is a lightweight Prometheus exporter for blockchain nodes. It supports Cosmos SDK, EVM-based nodes, and can be extended for other protocols. It exports metrics such as binary version, block height, peer count, syncing status, validator status, and more.

---

## ✅ Features

- 🔄 Multi-protocol support: Cosmos SDK, EVM chains
- 📡 Exposes Prometheus-compatible metrics over HTTP
- 🔍 Auto-detects systemd `.service` files for binaries
- 🛠️ Configurable via `config.toml`
- 🚀 Runs as a systemd service (`chainprobe.service`)
- 🧩 Easily extendable to other protocols

---

## 🚀 Installation

### Requirements

- Linux system with `systemd`
- Python 3.7+ and `pip`
- Root access to install systemd service and packages

### Setup Instructions

```bash
git clone https://github.com/your-org/chainprobe.git
cd chainprobe
chmod +x install.sh
./install.sh
```

The installer will:

- Install required Python packages globally
- Prompt you for inputs (see below)
- Auto-detect `.service` file paths using `systemctl`
- Generate a `config.toml` file
- Create and start a `systemd` service named `chainprobe`

---

### 📥 What You'll Be Asked During Installation

| Prompt | Description | Example |
|--------|-------------|---------|
| **protocol** | Type of blockchain protocol. Choose from `cosmos`, `evm`, or `other`. Determines which metrics are pre-filled in `config.toml`. | `cosmos` |
| **Is this a validator node?** | Type `yes` if this node participates in consensus. Enables validator-specific metrics. | `yes` |
| **metrics port** | The HTTP port to expose metrics to Prometheus (default is `3000`). | `3000` |
| **binary aliases** | Comma-separated names of your systemd services **without `.service` suffix**. These names are used to auto-detect binary paths from systemd. | `gaiad,heimdalld,bor` |

🧠 **Note**: The script will run:

```bash
systemctl show <name>.service -p FragmentPath
```

to detect actual unit paths (e.g. `/lib/systemd/system/bor.service`).

---

## ⚙️ Configuration (`config.toml`)

After installation, a `config.toml` file will be created in the same directory:

```toml
protocol = "cosmos"
metrics_port = 3000

[binaries]
gaiad = "/lib/systemd/system/gaiad.service"
heimdalld = "/lib/systemd/system/heimdalld.service"

[metrics.latest_block]
path = "/cosmos/base/tendermint/v1beta1/blocks/latest"
description = "Latest block height"

[metrics.validator_is_jailed]
path = "/cosmos/staking/v1beta1/validators/${valoper_address}"
description = "Is validator jailed"
```

If `is_validator = yes`, additional validator metrics will be added automatically.

---

## 📈 Prometheus Integration

Add the following job to your Prometheus `prometheus.yml`:

```yaml
- job_name: 'chainprobe'
  static_configs:
    - targets: ['localhost:3000']  # Change port if needed
```

Then reload Prometheus config.

Visit `http://localhost:3000/metrics` to confirm.

---

## 📤 Sample Exported Metrics

```text
binary_version_info{binary="heimdalld", version="1.6.0"} 1.0
latest_block_height 1234567
validator_is_jailed 0
peer_count 25
syncing 0
```

---

## 🧰 Managing the Exporter

```bash
# Start the service
sudo systemctl restart chainprobe

# Enable on boot
sudo systemctl enable chainprobe

# View logs
journalctl -u chainprobe -f

# Check status
systemctl status chainprobe
```

---

## 🛠️ Extending

You can extend `main.py` or `config.toml` to support:

- Other blockchain protocols (e.g., Polkadot, Solana)
- Custom REST endpoints
- Additional metrics and scaling factors