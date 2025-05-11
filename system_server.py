from daebus import Daebus, DaebusHttp, response, request
from daebus.modules.logger import logger as direct_logger
import os
import subprocess
import time

direct_logger.info("Starting system server...")

app = Daebus(__name__)
cors_config = {
    'allowed_origins': '*',
    'allowed_methods': ['GET', 'POST'],
    'allowed_headers': '*',
}
endpoint = DaebusHttp(port=8080, cors_config=cors_config)

app.attach(endpoint)


status_cache: dict[str, dict] = {}


@app.action("service_status")
def handle_status_response():
    try:
        payload = request.payload
        service_name = payload.get("service_name")
        status_payload = {
            "status": payload.get("status", "unknown"),
            "service_name": service_name,
            "timestamp": time.time(),
            "details": payload.get("details", None)
        }
        status_cache[service_name] = status_payload
        return response.success({
            "status": "ok",
        })
    except Exception as e:
        direct_logger.error(f"Error in handle_status_response: {e}")
        return response.error(str(e))


@app.route("/status")
def handle_status():
    if not status_cache:
        return response.send({}, 200)
    else:
        return response.send(status_cache, 200)


@app.route("/health")
def handle_health():
    return response.send({
        "status": "ok",
        "sdk_connected": True,  # We know SDK is connected if we've gotten this far
        "uptime": "unknown",  # Could add more detailed info here
        "endpoints": ["/health", "/status", "/ws", "/debug"]
    }, 200)


@app.route("/debug")
def handle_debug():
    return response.send({
        "status": "ok",
        "sdk_connected": True,
        "status_cache_size": len(status_cache),
        "server_info": {
            "host": "0.0.0.0",
            "port": 8080
        },
        "endpoints": ["/health", "/status", "/debug"]
    }, 200)


@app.on_start()
def notify_systemd_ready():
    try:
        if os.environ.get('NOTIFY_SOCKET'):
            direct_logger.info("Notifying systemd that service is ready")
            subprocess.run(["/bin/systemd-notify", "--ready"], check=True)
            return True
        else:
            direct_logger.info("Not running under systemd, skipping notification")
            return False
    except Exception as e:
        direct_logger.error(f"Failed to notify systemd: {e}")
        return False


# Main execution block
if __name__ == "__main__":
    # Run the Daebus application
    app.run(service='system-server', debug=True,
            redis_host='localhost', redis_port=6379) 