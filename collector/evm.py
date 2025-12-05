import asyncio
from prometheus_client import Gauge
from web3 import Web3, HTTPProvider
import logging


## Logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("evm")



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

    logger.info(f"Starting EVM collector for RPC: {rpc}")

    while True:
        try:
            gauges["peer_count"].set(w3.net.peer_count)
        except Exception as e:
            logger.error(f"peer_count: {e}")

        try:
            gauges["latest_block"].set(w3.eth.block_number)
        except Exception as e:
            logger.error(f"latest_block: {e}")
        try:
            syncing = w3.eth.syncing
            if syncing:
                try:
                    gauges["syncing"].set(0)
                    gauges["blocks_to_sync"].set(syncing["highestBlock"] - syncing["currentBlock"])
                except Exception as sub:
                    logger.error(f"blocks_to_sync parse error: {sub}")
            else:
                gauges["syncing"].set(1)
                gauges["blocks_to_sync"].set(0)
        except Exception as e:
            logger.error(f"syncing: {e}")

        try:
            gauges["network_name"].set(int(w3.eth.chain_id))
        except Exception as e_chain:
            try:
                gauges["network_name"].set(int(w3.net.version))
            except Exception as e_net:
                logger.error(f"network_name: chain_id={e_chain}, net.version={e_net}")

        # -------------------- net_listening -------------------------
        try:
            gauges["net_listening"].set(1 if w3.net.listening else 0)
        except Exception as e:
            logger.error(f"net_listening: {e}")

        logger.info("EVM metrics updated")

        # except Exception as e:
        #     print(f"[!] Error updating EVM metrics: {e}")

        await asyncio.sleep(15)
