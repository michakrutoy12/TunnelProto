
# Secure Async Tunnel TLS

A high-performance, secure, and rate-limited client-server tunneling system written in Python 3. It allows you to expose a local service (like a web server or a game server) to the public internet through a remote server (VPS) using a custom binary protocol over TLS.

## Features

- **Asynchronous Architecture:** Powered by Python's `asyncio` for high concurrency and low latency.
- **Transport Security:** All control and data traffic is fully encrypted using TLS (TLS 1.2+).
- **Traffic Shaping (Rate Limiting):** Built-in Token Bucket algorithm per client to prevent server overloading.
- **Graceful Shutdown:** Handles `SIGINT` and `SIGTERM` signals for clean resource cleanup.
- **Battle-Tested:** Proven stable over long multi-hour sessions (e.g., gaming) and capable of high throughput (up to 200 MB/s locally).

---

## Architecture Overview

The system consists of two main components:

1. **Server:** Runs on a publicly accessible machine (VPS). It accepts TLS connections from tunnel clients, reserves public ports, listens for external public traffic, and multiplexes data back to the appropriate client.
2. **Client:** Runs on the local machine hosting the target service. It connects to the remote server, establishes the tunnel, and bridges traffic between the server and your local service (e.g., `127.0.0.1:8080`).

---

## Quick Start (Local Testing)

### 1. Generate SSL Certificates
The tunnel requires TLS certificates. Generate self-signed certificates using the helper script:
```bash
python gencert.py --domain localhost --ip 127.0.0.1 --duration 365
```

### 2. Start the Server
Run the server on port `1234` (authentication is disabled by default when using CLI arguments):
```bash
python main.py server -b 127.0.0.1:1234 --clients-limit 5
```

### 3. Start the Client
Expose your local service running at port `8080` via the remote server:
```bash
python main.py client -s 127.0.0.1:1234 -l 127.0.0.1:8080 --client-id 550e8400-e29b-41d4-a716-446655440000
```

---

## Security & Authentication

### Client Authentication
The server can require clients to present a valid `client_id` (16-byte UUID) during the handshake phase. The server validates this ID against an internal list of allowed clients.

### Port Reservation (Static Ports)
By default, the server dynamically allocates the first available public port from its internal pool (ports `2000-65535`, configurable via a configuration file or via command line parameter `--dynamic-port-allocation-range`) to any newly connected tunnel client. 

For production environments where your public-facing application needs a permanent address, you can assign a **static reserved port** to a specific client ID via the configuration file.

The server determines the port allocation strategy based on the `reserved_port` value in the client's profile:

- **Static Assignment (`reserved_port`: <number>):** 
  1. The server isolates this port at startup, completely removing it from the dynamic pool so no other client can accidentally hijack it.
  2. Upon connection, the server bypasses dynamic allocation and binds exclusively to this pre-assigned port.
  3. Upon disconnection, the port remains locked and dedicated to that specific `client_id`, rather than being recycled back into the public pool.

- **Dynamic Assignment (`reserved_port`: null):** 
  The server falls back to standard behavior. It will dynamically lease the first available port from the pool to the client for the duration of the session, and recycle it back into the allocation pool once the client disconnects.

> [!NOTE]
> Static port reservation is **strictly linked to client authentication**. If you start the server via CLI arguments (which disables authentication), static port assignment is deactivated, and all ports will be allocated dynamically.

### > [!IMPORTANT]
> **Authentication vs CLI Arguments:** 
> When the server is started using command-line arguments (`-b` / `--bind-addr` or `--clients-limit`), **authentication is automatically disabled**, and any client can connect.

### > [!WARNING]
> **Rate Limiting Dependency:**
> The Token Bucket rate limiter relies entirely on the client's profile lookup. If authentication is disabled (via CLI flags or config), **traffic rate limiting is completely deactivated**, allowing unlimited throughput (`float('inf')`). For production deployments, always use a configuration file with `enable_auth: true`.

---

## Configuration File (`config/config.json`)

For production environments, running via a configuration file is highly recommended. If the file does not exist, a default template will be automatically generated inside `config/config.json`.

### Config Example
```json
{
  "log_level": "info",
  "cert": "certs/server.pem",
  "key": "certs/server.key",
  "server": {
    "dynamic_port_allocation_range": [2000, 65535],
    "bind_addr": "0.0.0.0:1234",
    "enable_auth": true,
    "allowed_clients": {
      "550e8400-e29b-41d4-a716-446655440000": {
        "rate_limit": 1048576,
        "reserved_port": 7070
      },
      "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d": {
        "rate_limit": 524288,
        "reserved_port": null
      }
    },
    "clients_limit": 10
  },
  "client": {
    "server_addr": "your-public-vps.com:1234",
    "local_addr": "127.0.0.1:8080",
    "check_hostname": true,
    "client_id": "550e8400-e29b-41d4-a716-446655440000"
  }
}
```

To run using the configuration file, pass the `--config` flag:
```bash
python main.py --config config/config.json server
# or
python main.py --config config/config.json client
```

---

## Protocol Specification (`PROTO.md` Summary)

All communication between the client and server is encapsulated within a strict byte-stream framing structure:

`{ start_byte (0x42) | payload | end_byte (0x52) }`

- Multi-byte integers (`reserved_port`, `connection_id`, `data_length`) are transmitted in **big-endian** order.
- While the protocol defines data packets (`0x04`) with a safe network payload limit of 1393 bytes, the application utilizes an internal buffer size of **4096 bytes** for efficient asynchronous streaming over TLS.

### Command Matrix

| Command | Hex Code | Direction | Description |
| :--- | :--- | :--- | :--- |
| **Error** | `0x00` | Server → Client | Handshake rejected / No ports available |
| **Reservation Req** | `0x01` | Client → Server | Initial port reservation request |
| **Reservation Resp**| `0x01` | Server → Client | Successful handshake containing the `reserved_port` |
| **New Connection** | `0x02` | Server → Client | Notification of a new incoming public connection |
| **Connection Ack** | `0x03` | Client → Server | Client confirmation (accept/reject) of the connection |
| **Data Transfer** | `0x04` | Both | Tunneled data transmission |
| **Close Connection**| `0x05` | Both | Close specific tunnel stream `connection_id` |
| **Keep-Alive** | `0x06` | Both | Ping/Pong heartbeat (Required every 30s) |
| **Error Signal** | `0xFF` | Both | System error broadcast |

---

## CLI Reference

### Global Arguments
* `--log-level`: `info` or `debug` (default: `info`).
* `--cert`: Path to the SSL certificate file.
* `--key`: Path to the SSL private key file.
* `--config`: Path to custom JSON configuration file.

### Server Subcommand Options
* `-b, --bind-addr`: Host and port to bind the server to (e.g., `0.0.0.0:1234`).
* `--clients-limit`: Max simultaneous clients allowed to establish tunnels.
* `--dynamic-port-allocation-range`: The range of ports available for dynamic allocation between clients for which no port is reserved (e.g., 2000-65535)

### Client Subcommand Options
* `-s, --server-addr`: Remote tunnel server address.
* `-l, --local-addr`: Local target application service address.
* `--client-id`: 16-byte hex UUID for server registration.
* `--check-hostname`: Validate the TLS certificate hostname (default: `true`).

---

## Performance & Diagnostics

- **Throughput Capability:** Reaches up to 200 MB/s over high-speed networks, bounded primarily by CPU TLS processing overhead and network bandwidth.
- **Keep-Alive Thresholds:** The client sends a heartbeat every 30 seconds. The server enforces a strict 90-second timeout; clients failing to respond within this window are gracefully disconnected, and their public ports are recycled back into the allocation pool.
