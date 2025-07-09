import httpx
import asyncio
from prometheus_client import Gauge

gauges = {}

def register_metrics(config):
    for name, m in config["metrics"].items():
        gauges[name] = Gauge(name, m["description"])

async def fetch_metric(name, config, client):
    cfg = config["metrics"][name]
    path = cfg["path"]
    path = path.replace("${valcons_address}", config["valcons_address"])
    path = path.replace("${valoper_address}", config["valoper_address"])
    path = path.replace("${account_address}", config["account_address"])
    url = f"{config['host']}:{config['rest_port']}{path}"

    try:
        response = await client.get(url, timeout=5.0)
        data = response.json()

        match name:
            case "latest_block":
                h = int(data["block"]["header"]["height"])
                gauges[name].set(h)
            case "validator_missed_blocks_total":
                missed = int(data["val_signing_info"]["missed_blocks_counter"])
                gauges[name].set(missed)
            case "validator_is_jailed":
                jailed = data["validator"]["jailed"]
                gauges[name].set(1 if jailed else 0)
            case "validator_is_active":
                status = data["validator"]["status"]
                gauges[name].set(1 if status == "BOND_STATUS_BONDED" else 0)
            case "validator_commission_rate":
                rate = float(data["validator"]["commission"]["commission_rates"]["rate"])
                gauges[name].set(rate)
            case "validator_commission_amount":
                amt = float(data["commission"]["commission"][0]["amount"])
                factor = cfg.get("scaling_factor", 1.0)
                gauges[name].set(amt / factor)
            case "validator_rewards_total":
                rewards = data["rewards"]
                if rewards:
                    amt = float(rewards[0]["amount"])
                    factor = cfg.get("scaling_factor", 1.0)
                    gauges[name].set(amt / factor)

        print(f"[✓] {name} updated")
    except Exception as e:
        print(f"[!] Failed to update {name}: {e}")

async def metric_updater(config):
    register_metrics(config)
    async with httpx.AsyncClient() as client:
        while True:
            await asyncio.gather(*(fetch_metric(name, config, client) for name in gauges))
            await asyncio.sleep(10)
