import base64

DOMAIN = "huayuan_gas"
BALANCE_URL = base64.b64decode(
    "aHR0cDovL3FjLmh1YXl1YW5yYW5xaS5jb20vaW5kZXgucGhwP2c9V2FwJm09SW5kZXgmYT1iYWxhbmNlX2RldGFpbCZzbj0="
).decode()
RECHARGE_LOG_URL = base64.b64decode(
    "aHR0cDovL3FjLmh1YXl1YW5yYW5xaS5jb20vaW5kZXgucGhwP2c9V2FwJm09SW5kZXgmYT1wYXlfZGV0YWlsJnNuPQ=="
).decode()
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_1) AppleWebKit/537 (KHTML, like Gecko) Chrome/116.0 Safari/537"
DEFAULT_SCAN_INTERVAL=24
