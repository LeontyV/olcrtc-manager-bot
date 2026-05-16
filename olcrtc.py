import asyncio
import re
import subprocess
from config import OLCRTC_BIN, OLCRTC_DATA, OLCRTC_DNS


async def _run(cmd: list[str], timeout: int = 30) -> tuple[str, str, int]:
    """Run command in a thread (isolated subprocess), return (stdout, stderr, code)."""
    loop = asyncio.get_running_loop()

    def _sync():
        try:
            r = subprocess.run(
                cmd, capture_output=True, timeout=timeout, text=False
            )
            return (
                r.stdout.decode("utf-8", errors="replace").strip(),
                r.stderr.decode("utf-8", errors="replace").strip(),
                r.returncode,
            )
        except subprocess.TimeoutExpired:
            return "", "timeout", -1
        except Exception as e:
            return "", str(e), -1

    return await loop.run_in_executor(None, _sync)


async def gen_key() -> str:
    """Generate random 64-char hex key."""
    stdout, _, code = await _run(["openssl", "rand", "-hex", "32"])
    if code != 0 or not stdout:
        raise RuntimeError("Failed to generate key")
    return stdout.strip()


async def gen_room(client_id: str, key_hex: str, carrier: str = "jazz") -> dict:
    """Create room via olcrtc -id any. Returns {room_id, raw_output}."""
    stdout, stderr, code = await _run(
        [
            OLCRTC_BIN,
            "-mode", "srv",
            "-carrier", carrier,
            "-id", "any",
            "-key", key_hex,
            "-client-id", client_id,
            "-transport", "datachannel",
            "-link", "direct",
            "-dns", OLCRTC_DNS,
            "-data", OLCRTC_DATA,
        ],
        timeout=40,
    )
    combined = stdout + "\n" + stderr

    if "404" in combined or "not found" in combined.lower():
        return {"room_id": None, "raw": f"Комната не найдена. Проверь ID для carrier={carrier}", "exit": code}

    m = re.search(r"(?:room created|joining room):\s*(\S+)", combined)
    room_id = m.group(1) if m else None
    return {"room_id": room_id, "raw": combined[:500], "exit": code}


async def systemctl(action: str, service_name: str) -> tuple[bool, str]:
    """Run systemctl start/stop/restart/is-active on a service."""
    cmd = ["systemctl", action, service_name]
    if action in ("is-active", "status"):
        cmd = ["systemctl", "--no-pager", action, service_name]
    stdout, stderr, code = await _run(cmd, timeout=15)
    ok = code == 0
    output = stdout or stderr
    return ok, output


async def journalctl(service_name: str, lines: int = 5) -> str:
    """Get last N lines from service journal."""
    stdout, _, _ = await _run(
        ["journalctl", "--no-pager", "-u", service_name, "-n", str(lines)],
        timeout=10,
    )
    return stdout


async def create_service(profile: dict) -> tuple[bool, str]:
    """Create systemd service for olcrtc profile. Returns (ok, output)."""
    name = profile["name"]
    client_id = profile["client_id"]
    key_hex = profile["key_hex"]
    room_id = profile["room_id"]
    carrier = profile.get("carrier", "jazz")
    transport = profile.get("transport", "datachannel")
    service_name = f"olcrtc-{client_id}"
    unit_path = f"/etc/systemd/system/{service_name}.service"

    flag_lines = []
    if transport == "vp8channel":
        flag_lines = ["  -vp8-fps 60", "  -vp8-batch 64"]
    elif transport == "seichannel":
        flag_lines = ["  -fps 60", "  -batch 64", "  -frag 900", "  -ack-ms 2000"]
    elif transport == "videochannel":
        flag_lines = [
            "  -video-codec qrcode", "  -video-w 1080", "  -video-h 1080",
            "  -video-fps 60", "  -video-bitrate 5000k", "  -video-hw none",
        ]

    lines = [
        "[Unit]",
        f"Description=OLCRTC tunnel for {name} ({client_id})",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Service]",
        "Type=simple",
        f"ExecStart=/root/olcrtc-manager-bot/olcrtc-wrapper.sh {OLCRTC_BIN} \\",
        "  -mode srv \\",
        f"  -carrier {carrier} \\",
        f'  -id "{room_id}" \\',
        f'  -key "{key_hex}" \\',
        f'  -client-id "{client_id}" \\',
        f"  -transport {transport} \\",
        "  -link direct \\",
        f"  -dns {OLCRTC_DNS} \\",
        f"  -data {OLCRTC_DATA}" + (" \\" if flag_lines else ""),
    ]
    for i, flag in enumerate(flag_lines):
        suffix = " \\" if i < len(flag_lines) - 1 else ""
        lines.append(flag + suffix)
    lines += [
        "Restart=always",
        "RestartSec=10",
        "StandardOutput=journal",
        "StandardError=journal",
        "",
        "[Install]",
        "WantedBy=multi-user.target",
    ]
    unit = "\n".join(lines)

    def _sync():
        try:
            with open(unit_path, "w") as f:
                f.write(unit)
            subprocess.run(["systemctl", "daemon-reload"], capture_output=True, timeout=10, check=True)
            return True, f"Создан: {unit_path}"
        except Exception as e:
            return False, str(e)

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _sync)
