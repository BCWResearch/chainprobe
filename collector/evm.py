import asyncio
from prometheus_client import Gauge
from web3 import Web3, HTTPProvider
from web3.exceptions import MethodUnavailable
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

# Metrics confirmed unsupported at runtime on this node.
# Once a metric lands here, it is never fetched again for this process lifetime.
# This prevents phantom 0-values from triggering false alerts on nodes that
# simply don't expose the method (e.g. managed RPC endpoints, light clients).
unsupported_metrics: set[str] = set()


# -------------------------
# Helper
# -------------------------
def is_method_not_supported(e: Exception) -> bool:
    """
    Returns True when the exception signals that the RPC method is permanently
    unavailable on this node — as opposed to a transient network/timeout error.

    Covers:
      - web3.py's own MethodUnavailable exception
      - Standard JSON-RPC error code -32601 (Method not found)
      - Common plain-text variants returned by various EVM clients
        (Erigon, Besu, Nethermind, managed endpoints like Infura/Alchemy)
    """
    if isinstance(e, MethodUnavailable):
        return True

    msg = str(e).lower()

    # JSON-RPC spec: -32601 = Method not found
    if "-32601" in msg:
        return True

    # Phrases used across different EVM client implementations
    not_supported_phrases = [
        "method not found",
        "method not supported",
        "the method does not exist",
        "unsupported method",
        "not supported",
        "unknown method",
    ]
    return any(phrase in msg for phrase in not_supported_phrases)


def skip_if_unsupported(metric_name: str):
    """Log once when a metric is first marked unsupported."""
    if metric_name not in unsupported_metrics:
        unsupported_metrics.add(metric_name)
        logger.warning(
            f"[{metric_name}] Method not supported by this node — "
            f"metric will not be exposed to avoid false alerts."
        )


# -------------------------
# Collector Task
# -------------------------
async def metric_updater(config):
    rpc = config.get("rpcaddress", "http://localhost:8545")
    w3 = Web3(HTTPProvider(rpc))

    logger.info(f"Starting EVM collector for RPC: {rpc}")

    while True:

        # ---- peer_count ----
        if "peer_count" not in unsupported_metrics:
            try:
                gauges["peer_count"].set(w3.net.peer_count)
            except Exception as e:
                if is_method_not_supported(e):
                    skip_if_unsupported("peer_count")
                else:
                    logger.error(f"peer_count: {e}")

        # ---- latest_block ----
        if "latest_block" not in unsupported_metrics:
            try:
                gauges["latest_block"].set(w3.eth.block_number)
            except Exception as e:
                if is_method_not_supported(e):
                    skip_if_unsupported("latest_block")
                else:
                    logger.error(f"latest_block: {e}")

        # ---- syncing + blocks_to_sync ----
        if "syncing" not in unsupported_metrics:
            try:
                syncing = w3.eth.syncing
                if syncing:
                    try:
                        gauges["syncing"].set(0)
                        gauges["blocks_to_sync"].set(
                            syncing["highestBlock"] - syncing["currentBlock"]
                        )
                    except Exception as sub:
                        logger.error(f"blocks_to_sync parse error: {sub}")
                else:
                    gauges["syncing"].set(1)
                    gauges["blocks_to_sync"].set(0)
            except Exception as e:
                if is_method_not_supported(e):
                    skip_if_unsupported("syncing")
                else:
                    logger.error(f"syncing: {e}")

        # ---- network_name (chain_id with net.version fallback) ----
        if "network_name" not in unsupported_metrics:
            try:
                gauges["network_name"].set(int(w3.eth.chain_id))
            except Exception as e_chain:
                if is_method_not_supported(e_chain):
                    # chain_id unsupported — try net.version before giving up
                    try:
                        gauges["network_name"].set(int(w3.net.version))
                    except Exception as e_net:
                        if is_method_not_supported(e_net):
                            skip_if_unsupported("network_name")
                        else:
                            logger.error(
                                f"network_name: chain_id={e_chain}, net.version={e_net}"
                            )
                else:
                    logger.error(f"network_name (chain_id): {e_chain}")

        # ---- net_listening ----
        if "net_listening" not in unsupported_metrics:
            try:
                gauges["net_listening"].set(1 if w3.net.listening else 0)
            except Exception as e:
                if is_method_not_supported(e):
                    skip_if_unsupported("net_listening")
                else:
                    logger.error(f"net_listening: {e}")

        exposed = set(gauges.keys()) - unsupported_metrics
        logger.info(f"EVM metrics updated — exposing: {sorted(exposed)}")

        await asyncio.sleep(15)