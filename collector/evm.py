import asyncio
import json
import logging
from typing import Any, Optional
from urllib.request import Request, urlopen

from prometheus_client import Gauge


# -------------------------
# Logger
# -------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("evm")


# -------------------------
# Lazy Prometheus objects
# -------------------------
gauges: dict[str, Gauge] = {}

labeled_gauges: dict[str, Gauge] = {}
labeled_last_label_value: dict[str, str] = {}

unsupported_metrics: set[str] = set()


# -------------------------
# Error classification
# -------------------------
def is_method_not_supported(e: Exception) -> bool:
    """
    Returns True when the exception signals that the RPC method is permanently
    unavailable on this node — as opposed to a transient error.
    """
    msg = str(e).lower()

    # Standard JSON-RPC "Method not found"
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
    return any(p in msg for p in not_supported_phrases)


def mark_unsupported(metric_name: str, reason: Optional[str] = None):
    unsupported_metrics.add(metric_name)
    if reason:
        logger.warning(f"[{metric_name}] Unsupported — {reason} (disabled for process lifetime).")
    else:
        logger.warning(f"[{metric_name}] Unsupported (disabled for process lifetime).")


# -------------------------
# Prometheus setters
# -------------------------
def set_gauge(metric_name: str, description: str, value: float):
    if metric_name not in gauges:
        gauges[metric_name] = Gauge(metric_name, description)
        logger.info(f"[{metric_name}] Metric supported — gauge registered.")
    gauges[metric_name].set(value)


def set_labeled_gauge(metric_name: str, description: str, label_name: str, label_value: str, value: float):
    if metric_name not in labeled_gauges:
        labeled_gauges[metric_name] = Gauge(metric_name, description, labelnames=[label_name])
        logger.info(f"[{metric_name}] Labeled gauge registered with label '{label_name}'.")

    g = labeled_gauges[metric_name]
    prev = labeled_last_label_value.get(metric_name)
    if prev is not None and prev != label_value:
        try:
            g.labels(**{label_name: prev}).set(0)
        except Exception:
            pass

    g.labels(**{label_name: label_value}).set(value)
    labeled_last_label_value[metric_name] = label_value


# -------------------------
# Config helpers (backward compatible ONLY for RPC URL + interval)
# -------------------------
def get_default_rpc(config: dict) -> str:
    """
    Backward compatible:
      - old configs: rpcaddress at root
      - newer: [default].rpcaddress
    """
    default = config.get("default")
    if isinstance(default, dict) and default.get("rpcaddress"):
        return str(default["rpcaddress"])
    return str(config.get("rpcaddress", "http://localhost:8545"))


def get_interval_seconds(config: dict) -> int:
    """
    Backward compatible interval (default 15):
      1) [default].interval_seconds
      2) interval_seconds at root
      3) default 15
    """
    default = config.get("default")
    if isinstance(default, dict) and "interval_seconds" in default:
        return int(default.get("interval_seconds", 15))

    if "interval_seconds" in config:
        return int(config.get("interval_seconds", 15))

    return 15


def standard_enabled(config: dict) -> bool:
    """
    Optional:
      [evm]
      enabled = true/false
    Default: True.
    """
    evm_cfg = config.get("evm")
    if isinstance(evm_cfg, dict) and "enabled" in evm_cfg:
        return bool(evm_cfg.get("enabled", True))
    return True


def get_metrics_table(config: dict) -> dict:
    m = config.get("metrics")
    return m if isinstance(m, dict) else {}


def metric_timeout_seconds(config: dict, metric_cfg: dict) -> float:
    if "timeout_seconds" in metric_cfg:
        return float(metric_cfg.get("timeout_seconds", 5))
    return 5.0


def metric_rpcaddress(default_rpc: str, metric_cfg: dict) -> str:
    """
    IMPORTANT: If rpcaddress isn't overridden per-metric, always use default RPC.
    """
    if metric_cfg.get("rpcaddress"):
        return str(metric_cfg["rpcaddress"])
    return default_rpc


def metric_enabled(metric_cfg: dict) -> bool:
    if "enabled" in metric_cfg:
        return bool(metric_cfg.get("enabled", True))
    return True


def metric_description(metric_cfg: dict, default_desc: str) -> str:
    if metric_cfg.get("description"):
        return str(metric_cfg["description"])
    return default_desc


def _iter_methods(metric_cfg: dict) -> list[str]:
    """
    Accept JSON-RPC method names only:
      method = "eth_syncing"
      methods = ["eth_chainId", "net_version"]
    """
    out: list[str] = []

    if isinstance(metric_cfg.get("methods"), list):
        for x in metric_cfg["methods"]:
            if isinstance(x, str) and x.strip():
                out.append(x.strip())

    m = metric_cfg.get("method")
    if isinstance(m, str) and m.strip():
        out.append(m.strip())

    return out


# -------------------------
# Enum mapping
# -------------------------
def _enum_candidates(value: Any) -> list[str]:
    c: list[str] = []
    try:
        c.append(str(value))
    except Exception:
        pass
    try:
        c.append(str(int(value)))
    except Exception:
        pass
    try:
        c.append(str(value).lower())
    except Exception:
        pass
    return c


def enum_match_label(raw_value: Any, enum_map: Any) -> Optional[str]:
    if not isinstance(enum_map, dict):
        return None

    for k in _enum_candidates(raw_value):
        if k in enum_map and isinstance(enum_map[k], str):
            return enum_map[k]

    for k in _enum_candidates(raw_value):
        try:
            ki = int(k, 0)
            if ki in enum_map and isinstance(enum_map[ki], str):
                return enum_map[ki]
        except Exception:
            continue

    return None


def enum_numeric_override(raw_value: Any, enum_map: Any) -> Optional[float]:
    if not isinstance(enum_map, dict):
        return None

    for k in _enum_candidates(raw_value):
        if k in enum_map and not isinstance(enum_map[k], str):
            try:
                return float(enum_map[k])
            except Exception:
                return None

    for k in _enum_candidates(raw_value):
        try:
            ki = int(k, 0)
            if ki in enum_map and not isinstance(enum_map[ki], str):
                try:
                    return float(enum_map[ki])
                except Exception:
                    return None
        except Exception:
            continue

    return None


def apply_enum_outputs(base_metric_name: str, base_desc: str, raw_numeric_value: float, metric_cfg: dict):
    enum_map = metric_cfg.get("enum")

    numeric_override = enum_numeric_override(raw_numeric_value, enum_map)
    if numeric_override is not None:
        set_gauge(base_metric_name, base_desc, float(numeric_override))
        return

    set_gauge(base_metric_name, base_desc, float(raw_numeric_value))

    label = enum_match_label(raw_numeric_value, enum_map)
    if label is not None:
        label_name = str(metric_cfg.get("enum_label", "enum"))
        labeled_metric = str(metric_cfg.get("enum_metric", f"{base_metric_name}_enum"))
        set_labeled_gauge(
            labeled_metric,
            f"{base_desc} (enum)",
            label_name,
            label,
            float(raw_numeric_value),
        )


# -------------------------
# JSON-RPC client
# -------------------------
def _jsonrpc_call_sync(rpc: str, method: str, params: Optional[list], timeout: float) -> dict:
    payload = {"jsonrpc": "2.0", "method": method, "params": params or [], "id": 1}
    data = json.dumps(payload).encode("utf-8")
    req = Request(rpc, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    return json.loads(body.decode("utf-8"))


async def jsonrpc_call(rpc: str, method: str, params: Optional[list], timeout: float) -> dict:
    return await asyncio.to_thread(_jsonrpc_call_sync, rpc, method, params, timeout)


def get_by_path(obj: Any, path: str) -> Any:
    cur = obj
    for seg in (path or "").split("."):
        if seg == "":
            continue
        if isinstance(cur, dict):
            cur = cur.get(seg)
        elif isinstance(cur, list):
            try:
                cur = cur[int(seg)]
            except Exception:
                return None
        else:
            return None
    return cur


def to_int(x: Any) -> int:
    if x is None:
        return 0
    if isinstance(x, bool):
        return int(x)
    if isinstance(x, (int, float)):
        return int(x)
    if isinstance(x, str):
        s = x.strip()
        if s.startswith(("0x", "0X")):
            return int(s, 16)
        return int(s)
    try:
        return int(x)
    except Exception:
        return 0


def transform_value(raw: Any, transform: str) -> float:
    t = (transform or "float").lower()

    if t == "float":
        try:
            return float(raw)
        except Exception:
            return float(to_int(raw))

    if t in ("int", "hex_to_int", "auto_int"):
        return float(to_int(raw))

    if t == "bool_to_01":
        return 1.0 if bool(raw) else 0.0

    if t == "invert_bool_to_01":
        return 0.0 if bool(raw) else 1.0

    if t == "len":
        return float(len(raw) if isinstance(raw, list) else 0.0)

    if t == "eth_syncing_to_synced":
        return 1.0 if (raw is False) else 0.0

    if t == "eth_syncing_blocks_to_sync":
        if raw is False:
            return 0.0
        if isinstance(raw, dict):
            highest = to_int(raw.get("highestBlock"))
            current = to_int(raw.get("currentBlock"))
            return float(max(highest - current, 0))
        return 0.0

    try:
        return float(raw)
    except Exception:
        return float(to_int(raw))


async def fetch_via_jsonrpc(metric_rpc: str, method: str, metric_cfg: dict, timeout: float) -> Any:
    params = metric_cfg.get("params", [])
    resp = await jsonrpc_call(str(metric_rpc), str(method), params if isinstance(params, list) else [], timeout)
    if isinstance(resp, dict) and resp.get("error"):
        raise Exception(str(resp["error"]))

    raw_result = resp.get("result")
    result_path = metric_cfg.get("result_path")
    return get_by_path(raw_result, result_path) if result_path else raw_result


# -------------------------
# Standard metrics defaults (EVM JSON-RPC)
# -------------------------
STANDARD_DEFAULTS: dict[str, dict[str, Any]] = {
    "peer_count": {
        "description": "Number of peers",
        "methods": ["net_peerCount"],
        "transform": "auto_int",
    },
    "latest_block": {
        "description": "Latest block number of the chain",
        "methods": ["eth_blockNumber"],
        "transform": "auto_int",
    },
    "syncing": {
        "description": "Syncing status (1 = synced, 0 = syncing)",
        "methods": ["eth_syncing"],
        "transform": "eth_syncing_to_synced",
    },
    "blocks_to_sync": {
        "description": "Remaining blocks to sync",
        "methods": ["eth_syncing"],
        "transform": "eth_syncing_blocks_to_sync",
    },
    "network_name": {
        "description": "Network chain ID or name",
        "methods": ["eth_chainId", "net_version"],
        "transform": "auto_int",
    },
    "net_listening": {
        "description": "Whether client is accepting connections",
        "methods": ["net_listening"],
        "transform": "bool_to_01",
    },
}


def uses_standard_defaults(metric_name: str, user_cfg: dict) -> bool:
    """
    Same rule as before:
      - For standard metrics, we ONLY auto-fill defaults if user changes NOTHING
        except 'description'.
      - If user changes any other field, we do NOT merge defaults.
    """
    if metric_name not in STANDARD_DEFAULTS:
        return False
    if not isinstance(user_cfg, dict) or not user_cfg:
        return True
    return set(user_cfg.keys()).issubset({"description"})


def effective_cfg(metric_name: str, user_cfg: dict) -> dict:
    if metric_name in STANDARD_DEFAULTS and uses_standard_defaults(metric_name, user_cfg):
        cfg = dict(STANDARD_DEFAULTS[metric_name])
        if isinstance(user_cfg, dict) and user_cfg.get("description"):
            cfg["description"] = user_cfg["description"]
        return cfg
    return dict(user_cfg or {})


def validate_cfg(metric_name: str, cfg: dict) -> Optional[str]:
    methods = _iter_methods(cfg)
    if not methods:
        return "missing 'method' or 'methods'"
    return None


# -------------------------
# Collector core
# -------------------------
async def collect_one_metric(config: dict, default_rpc: str, metric_name: str, user_cfg: dict):
    cfg = effective_cfg(metric_name, user_cfg)

    if not metric_enabled(cfg):
        return
    if metric_name in unsupported_metrics:
        return

    base_desc = STANDARD_DEFAULTS.get(metric_name, {}).get("description", metric_name)
    desc = metric_description(cfg, base_desc)

    # Validate only when NOT using defaults (i.e., custom or standard override)
    if not (metric_name in STANDARD_DEFAULTS and uses_standard_defaults(metric_name, user_cfg)):
        err = validate_cfg(metric_name, cfg)
        if err:
            logger.error(f"[{metric_name}] invalid config: {err}. Provide required fields (method(s)/...).")
            mark_unsupported(metric_name, reason=f"invalid config: {err}")
            return

    timeout = metric_timeout_seconds(config, cfg)
    rpc = metric_rpcaddress(default_rpc, cfg)  # always default if not overridden
    methods = _iter_methods(cfg)
    if not methods:
        mark_unsupported(metric_name, reason="missing method candidates")
        return

    try:
        last_err: Optional[Exception] = None

        for m in methods:
            try:
                raw = await fetch_via_jsonrpc(rpc, m, cfg, timeout)
                transform = str(cfg.get("transform", "float"))
                value = transform_value(raw, transform)
                apply_enum_outputs(metric_name, desc, value, cfg)
                return
            except Exception as e_try:
                last_err = e_try
                if is_method_not_supported(e_try):
                    continue
                raise

        if last_err is not None:
            mark_unsupported(metric_name, reason=str(last_err))
        else:
            mark_unsupported(metric_name, reason="no usable methods")

    except Exception as e:
        if is_method_not_supported(e):
            mark_unsupported(metric_name, reason=str(e))
        else:
            logger.error(f"{metric_name}: {e}")


async def collect_all_metrics(config: dict, default_rpc: str):
    metrics_table = get_metrics_table(config)

    # 1) standard metrics
    for name in STANDARD_DEFAULTS.keys():
        user_cfg = metrics_table.get(name, {})
        if not isinstance(user_cfg, dict):
            user_cfg = {}
        await collect_one_metric(config, default_rpc, name, user_cfg)

    # 2) custom metrics
    for name, user_cfg in metrics_table.items():
        if name in STANDARD_DEFAULTS:
            continue
        if not isinstance(user_cfg, dict):
            continue
        await collect_one_metric(config, default_rpc, name, user_cfg)


# -------------------------
# Main task
# -------------------------
async def metric_updater(config):
    default_rpc = get_default_rpc(config)
    logger.info(f"Starting EVM JSON-RPC collector for RPC: {default_rpc}")

    interval = get_interval_seconds(config)

    while True:
        if standard_enabled(config):
            await collect_all_metrics(config, default_rpc)

        exposed = sorted(set(gauges.keys()) | set(labeled_gauges.keys()))
        logger.info(f"EVM metrics updated — exposing: {exposed}")

        await asyncio.sleep(interval)
