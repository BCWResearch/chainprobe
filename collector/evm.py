import asyncio
from prometheus_client import Gauge
from web3 import Web3, HTTPProvider

# -------------------------
# Gauges for EVM metrics
# -------------------------
gauges = {
    "peer_count": Gauge("peer_count", "Number of connected peers"),
    "latest_block": Gauge("latest_block", "Latest block number"),
    "syncing": Gauge("syncing", "Syncing status: 1 if synced, 0 if syncing"),
    "blocks_to_sync": Gauge("blocks_to_sync", "Blocks remaining to sync"),
    "network_name": Gauge("network_name", "Network ID"),
    "net_listening": Gauge("net_listening", "Listening status: 1 if true, 0 if false"),
}


# -------------------------
# Collector Task
# -------------------------
async def metric_updater(config):
    rpc = config.get("rpcaddress", "http://localhost:8545")
    w3 = Web3(HTTPProvider(rpc))

    while True:
        try:
            gauges["peer_count"].set(w3.net.peer_count)
            gauges["latest_block"].set(w3.eth.block_number)

            syncing = w3.eth.syncing
            if syncing:
                gauges["syncing"].set(0)
                gauges["blocks_to_sync"].set(syncing["highestBlock"] - syncing["currentBlock"])
            else:
                gauges["syncing"].set(1)
                gauges["blocks_to_sync"].set(0)

            gauges["network_name"].set(int(w3.net.version))
            gauges["net_listening"].set(1 if w3.net.listening else 0)

            print("[✓] EVM metrics updated")

        except Exception as e:
            print(f"[!] Error updating EVM metrics: {e}")

        await asyncio.sleep(15)
