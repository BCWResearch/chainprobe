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


# Gauges are created lazily — only after a successful fetch confirms the metric
# is supported by this node. Nothing is registered at import time.
gauges: dict[str, Gauge] = {}

# Metrics confirmed unsupported at runtime on this node.
# Once added here, the metric is never attempted again for this process lifetime.
unsupported_metrics: set[str] = set()


# -------------------------
# Helpers
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

    if "-32601" in msg:
        return True

    not_supported_phrases = [
        "method not found",
        "method not supported",
        "the method does not exist",
        "unsupported method",
        "not supported",
        "unknown method",
    ]
    return any(phrase in msg for phrase in not_supported_phrases)


def mark_unsupported(metric_name: str):
    unsupported_metrics.add(metric_name)
    logger.warning(
        f"[{metric_name}] Method not supported by this node — "
        f"metric will not be exposed."
    )


def set_gauge(metric_name: str, description: str, value: float):
    """Create gauge on first successful fetch, then just update the value."""
    if metric_name not in gauges:
        gauges[metric_name] = Gauge(metric_name, description)
        logger.info(f"[{metric_name}] Metric supported — gauge registered.")
    gauges[metric_name].set(value)


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
                set_gauge("peer_count", "Number of connected peers", w3.net.peer_count)
            except Exception as e:
                if is_method_not_supported(e):
                    mark_unsupported("peer_count")
                else:
                    logger.error(f"peer_count: {e}")

        # ---- latest_block ----
        if "latest_block" not in unsupported_metrics:
            try:
                set_gauge("latest_block", "Latest block number", w3.eth.block_number)
            except Exception as e:
                if is_method_not_supported(e):
                    mark_unsupported("latest_block")
                else:
                    logger.error(f"latest_block: {e}")

        # ---- syncing + blocks_to_sync ----
        if "syncing" not in unsupported_metrics:
            try:
                syncing = w3.eth.syncing
                if syncing:
                    try:
                        set_gauge("syncing", "Syncing status: 1 if synced, 0 if syncing", 0)
                        set_gauge(
                            "blocks_to_sync",
                            "Blocks remaining to sync",
                            syncing["highestBlock"] - syncing["currentBlock"]
                        )
                    except Exception as sub:
                        logger.error(f"blocks_to_sync parse error: {sub}")
                else:
                    set_gauge("syncing", "Syncing status: 1 if synced, 0 if syncing", 1)
                    set_gauge("blocks_to_sync", "Blocks remaining to sync", 0)
            except Exception as e:
                if is_method_not_supported(e):
                    mark_unsupported("syncing")
                else:
                    logger.error(f"syncing: {e}")

        # ---- network_name (chain_id with net.version fallback) ----
        if "network_name" not in unsupported_metrics:
            try:
                set_gauge("network_name", "Network ID", int(w3.eth.chain_id))
            except Exception as e_chain:
                if is_method_not_supported(e_chain):
                    # chain_id unsupported — try net.version before giving up
                    try:
                        set_gauge("network_name", "Network ID", int(w3.net.version))
                    except Exception as e_net:
                        if is_method_not_supported(e_net):
                            mark_unsupported("network_name")
                        else:
                            logger.error(
                                f"network_name: chain_id={e_chain}, net.version={e_net}"
                            )
                else:
                    logger.error(f"network_name (chain_id): {e_chain}")

        # ---- net_listening ----
        if "net_listening" not in unsupported_metrics:
            try:
                set_gauge(
                    "net_listening",
                    "Listening status: 1 if true, 0 if false",
                    1 if w3.net.listening else 0
                )
            except Exception as e:
                if is_method_not_supported(e):
                    mark_unsupported("net_listening")
                else:
                    logger.error(f"net_listening: {e}")

        exposed = set(gauges.keys())
        logger.info(f"EVM metrics updated — exposing: {sorted(exposed)}")

        await asyncio.sleep(15)