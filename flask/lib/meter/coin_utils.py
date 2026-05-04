import re
import time
from html import unescape
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from lib.meter.ssh_meter import SSHMeter


_COIN_TALLY_ROW_RE = re.compile(
    r"^\s*(?P<index>\d+)\s+"
    r"(?P<value>\d+)\s+"
    r"(?P<accepted>\*)?\s*"
    r"(?P<wallet>\d+)\s+"
    r"(?P<cashbox>\d+)\s+"
    r"(?P<lifetime>\d+)\s*$"
)


def _strip_html(value: str) -> str:
    text = unescape(value or "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _is_coins_page_html(page_html: str) -> bool:
    text = _strip_html(page_html).lower()
    return "service:utilities:coins" in text and "empty wallet" in text


def _is_notice_page_html(page_html: str) -> bool:
    lowered = (page_html or "").lower()
    return (
        "<title>notice</title>" in lowered
        or "noticetitle" in lowered
        or "noticecontent" in lowered
    )


def _is_coin_collection_flow_page_html(page_html: str) -> bool:
    if not _is_notice_page_html(page_html):
        return False
    text = _strip_html(page_html).lower()
    return "cash collection" in text or "coin collection" in text


def _parse_coin_tally_rows(page_html: str) -> list[dict[str, int]]:
    pre_match = re.search(r"<pre[^>]*>(.*?)</pre>", page_html, flags=re.I | re.S)
    block = unescape(pre_match.group(1) if pre_match else page_html).replace("\r", "")
    block = re.sub(r"<[^>]+>", " ", block)

    rows: list[dict[str, int]] = []
    for line in block.splitlines():
        match = _COIN_TALLY_ROW_RE.match(line)
        if not match:
            continue
        rows.append(
            {
                "index": int(match.group("index")),
                "value": int(match.group("value")),
                "wallet": int(match.group("wallet")),
                "cashbox": int(match.group("cashbox")),
                "lifetime": int(match.group("lifetime")),
            }
        )
    return rows


def _coin_tallies_cleared(
    meter: "SSHMeter",
    *,
    goto_coins_if_needed: bool = True,
    timeout: float = 5.0,
) -> bool:
    try:
        page_html = meter.get_ui_page_html(timeout=timeout)
        if goto_coins_if_needed and not _is_coins_page_html(page_html):
            meter.goto_coins()
            page_html = meter.get_ui_page_html(timeout=timeout)

        rows = _parse_coin_tally_rows(page_html)
        return bool(rows) and all(
            row["wallet"] == 0 and row["cashbox"] == 0
            for row in rows
        )
    except Exception as e:
        if getattr(meter, "verbose", False):
            print(f"[coin_tallies_cleared] {e}")
        return False


def _wait_for_coin_collection_flow_to_finish(
    meter: "SSHMeter",
    *,
    startup_timeout: float = 4.0,
    flow_timeout: float = 20.0,
    poll_interval: float = 0.5,
    page_timeout: float = 2.0,
) -> bool:
    startup_deadline = time.time() + max(0.0, float(startup_timeout))
    flow_deadline: Optional[float] = None

    while True:
        if flow_deadline is not None and time.time() >= flow_deadline:
            return False

        try:
            page_html = meter.get_ui_page_html(timeout=page_timeout)
        except Exception as e:
            if getattr(meter, "verbose", False):
                print(f"[wait_for_coin_collection_flow_to_finish] {e}")
            time.sleep(max(0.0, float(poll_interval)))
            continue

        if _is_coin_collection_flow_page_html(page_html):
            if flow_deadline is None:
                flow_deadline = time.time() + max(0.0, float(flow_timeout))
        elif flow_deadline is not None:
            return True
        elif time.time() >= startup_deadline:
            return False

        time.sleep(max(0.0, float(poll_interval)))


def clear_coin_tallies(
    meter: "SSHMeter",
    *,
    wallet_reset_delay: float = 0.3,
    collection_start_timeout: float = 4.0,
    collection_flow_timeout: float = 20.0,
    verify_timeout: float = 10.0,
    poll_interval: float = 1.0,
) -> bool:
    meter.goto_coins()
    meter.press("-", delay=wallet_reset_delay)
    meter.present_coin_collection_card()

    _wait_for_coin_collection_flow_to_finish(
        meter,
        startup_timeout=collection_start_timeout,
        flow_timeout=collection_flow_timeout,
        poll_interval=min(max(0.1, float(poll_interval)), 0.5),
    )

    deadline = time.time() + max(0.0, float(verify_timeout))
    while True:
        if _coin_tallies_cleared(meter):
            return True
        if time.time() >= deadline:
            return False
        time.sleep(max(0.0, float(poll_interval)))
