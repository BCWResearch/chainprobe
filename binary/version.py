import asyncio
import os
import psutil
import re
import subprocess
from prometheus_client import Gauge
import logging

logger = logging.getLogger("binary")
logger.setLevel(logging.INFO)

binary_version_metric = Gauge("binary_version_info", "Node binary version", ["binary", "version"])

def extract_binary_path_from_unit(unit_path):
    try:
        with open(unit_path, 'r') as f:
            content = f.read()

        # Allow leading whitespace before 'ExecStart='
        match = re.search(r'^\s*ExecStart=(\S+)', content, re.MULTILINE)
        if match:
            full_cmd = match.group(1)
            binary_path = full_cmd.split()[0]  # Only extract the binary path (first part)
            return binary_path
    except Exception as e:
        logger.error(f"[!] Failed to extract binary path from {unit_path}: {e}")
    return None

def find_actual_cosmovisor_binary(parent_bin="cosmovisor"):
    try:
        for proc in psutil.process_iter(attrs=["pid", "name", "cmdline"]):
            if not proc.info.get("cmdline"):
                continue
            if parent_bin in proc.info["cmdline"][0]:
                for child in proc.children():
                    try:
                        exe_path = os.readlink(f"/proc/{child.pid}/exe")
                        return exe_path
                    except Exception:
                        continue
    except Exception as e:
        logger.error(f"[!] Error inspecting processes: {e}")
    return None

def get_binary_version(binary_path):
    if not binary_path:
        return None

    version_regex = re.compile(r"\bv?(\d+\.\d+\.\d+(?:[-+.\w]*)?)\b")

    version_cmds = [
        [binary_path, "version"],
        [binary_path, "--version"]
    ]

    for cmd in version_cmds:
        try:
            output = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT).strip()
            lines = output.splitlines()
            for line in lines:
                match = version_regex.search(line)
                if match:
                    return match.group(0)
            return lines[0] if lines else None
        except subprocess.CalledProcessError:
            continue
    return None

async def report_binary_version_daily(config):
    binaries = config.get("binaries", {})

    while True:
        for alias, unit_path in binaries.items():
            binary_path = extract_binary_path_from_unit(unit_path)

            if binary_path and "cosmovisor" in binary_path:
                detected = find_actual_cosmovisor_binary()
                if detected:
                    binary_path = detected

            version = get_binary_version(binary_path)
            if version:
                binary_version_metric.labels(binary=alias, version=version).set(1)
                logger.info(f"[✓] {alias}: {version}")
            else:
                logger.warning(f"[!] Could not determine version for: {alias}")

        await asyncio.sleep(3600)
