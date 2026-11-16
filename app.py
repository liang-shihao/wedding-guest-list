"""Entry point: read config from environment and serve."""
import logging
import os
import sys

from seat.server import make_server


def main():
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not password:
        sys.exit("ADMIN_PASSWORD is required")
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8001"))
    data_dir = os.environ.get("DATA_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    redirect_to = os.environ.get("REDIRECT_TO", "").strip()
    trust_proxy = os.environ.get("TRUST_PROXY", "") == "1"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    httpd = make_server(host, port, data_dir, password, redirect_to=redirect_to, trust_proxy=trust_proxy)
    mode = f"redirect -> {redirect_to}" if redirect_to else f"data={data_dir}"
    logging.info("serving on http://%s:%d (%s)", host, port, mode)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
