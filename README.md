# Secure Async Tunnel TLS

A high-performance, secure, and rate-limited client-server tunneling system written in Python 3. It allows you to expose a local service (web server, game server, etc.) to the public internet through a remote server (VPS) using a custom binary protocol over TLS.

## Features

- **Asynchronous Architecture:** Powered by Python's `asyncio` for high concurrency and low latency.
- **Transport Security:** All control and data traffic is fully encrypted using TLS 1.2+.
- **Traffic Shaping:** Built-in per-client Token Bucket rate limiting to prevent server overloading.
- **Per-Client Connection Limits:** Control the maximum number of simultaneous active tunnels per client.
- **Static Port Reservation:** Assign fixed public ports to specific client IDs.
- **Graceful Shutdown:** Handles `SIGINT` and `SIGTERM` signals for clean resource cleanup.
- **Proven Stability:** Stable over long multi-hour sessions (e.g. gaming) and capable of high throughput up to 200 MB/s locally.

---

## Architecture Overview

The system consists of two main components:

1. **Server:** Runs on a publicly accessible machine (VPS). Accepts TLS connections from tunnel clients, reserves public ports, listens for external public traffic, and multiplexes data back to the appropriate client.
2. **Client:** Runs on the local machine hosting the target service. Connects to the remote server, establishes the tunnel, and bridges traffic between the server and your local service (e.g. `127.0.0.1:8080`).

---

## Quick Start (Local Testing)

### 1. Generate SSL Certificates

Generate self-signed TLS certificates using the helper script:

    python gencert.py --domain localhost --ip 127.0.0.1 --duration 365

### 2. Start the Server

Run the server on port `1234`. Authentication is disabled by default when using CLI arguments:

    python main.py server -b 127.0.0.1:1234 --clients-limit 5

### 3. Start the Client

Expose your local service running at port `8080` via the remote server:

    python main.py client -s 127.0.0.1:1234 -l 127.0.0.1:8080 --client-id 550e8400-e29b-41d4-a716-446655440000

---

## Security & Authentication

### Client Authentication

The server can require clients to present a valid `client_id` (16-byte UUID) during the handshake phase. The server validates this ID against an internal list of allowed clients.

### Port Reservation

By default, the server dynamically allocates the first available public port from its internal pool (ports `2000-65535`, configurable via a configuration file or the `--dynamic-port-allocation-range` CLI parameter) to any newly connected tunnel client.

For production environments where a public-facing application needs a permanent address, a static reserved port can be assigned to a specific client ID via the configuration file.

The port allocation strategy depends on the `reserved_port` value in the client profile:

- **Static Assignment (`reserved_port: <number>`):**
  - The server isolates this port at startup, removing it from the dynamic pool so no other client can accidentally use it.
  - Upon connection, the server bypasses dynamic allocation and binds exclusively to this pre-assigned port.
  - Upon disconnection, the port remains locked and dedicated to that specific `client_id`; it is not recycled back into the public pool.

- **Dynamic Assignment (`reserved_port: null`):**
  - The server leases the first available port from the pool to the client for the session duration.
  - After disconnection, the port is recycled back into the allocation pool.

### Rate Limiting

Each client can have an individual rate limit in bytes per second, enforced by a Token Bucket algorithm. When a client sends data, the server checks its token bucket; if insufficient tokens are available, the packet is delayed or dropped to conform to the limit. This prevents one client from saturating the server's bandwidth.

- **Configuration:** Set `rate_limit` per client in the `allowed_clients` section.
- **Default:** Infinity — no limit.

### Per-Client Connection Limit

You can restrict the maximum number of simultaneous active tunnels per client. This prevents a client from opening too many concurrent connections and exhausting system resources.

- **Configuration:** Set `max_connections` per client in the `allowed_clients` section.
- **Default:** Infinity — no limit.

> [!IMPORTANT]
> All client-specific features (`reserved_port`, `rate_limit`, `max_connections`) are effective **only** when authentication is enabled (`enable_auth: true`) and the server is started using a configuration file.
>
> When the server is started via CLI arguments (`-b`, `--clients-limit`, etc.), authentication is automatically disabled, and all per-client restrictions are ignored. The server falls back to dynamic port allocation, unlimited rate, and unlimited connections for every client.

---

## Configuration File (`config/config.json`)

For production environments, running via a configuration file is highly recommended. If the file does not exist, a default template is automatically generated at `config/config.json`.

### Top-Level Parameters

| Key | Type | Description |
| --- | --- | --- |
| `log_level` | string | Logging verbosity: `"info"` or `"debug"`. |
| `cert` | string | Path to the TLS certificate file (PEM). |
| `key` | string | Path to the TLS private key file (PEM). |
| `server` | object | Server-specific settings. |
| `client` | object | Client-specific settings. |

### `server` Object

| Key | Type | Description |
| --- | --- | --- |
| `dynamic_port_allocation_range` | array of two integers | Range of ports available for dynamic allocation, e.g. `[2000, 65535]`. |
| `bind_addr` | string | Address and port the server listens on, e.g. `"0.0.0.0:1234"`. |
| `enable_auth` | boolean | Must be `true` to activate client authentication and per-client features. |
| `allowed_clients` | object | Map of client UUIDs to their individual settings. |
| `clients_limit` | integer | Maximum number of concurrently connected clients. |

### `allowed_clients` Object

Each key is a UUID string (with or without hyphens). The value is an object with the following optional fields:

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `rate_limit` | number | Infinity | Maximum data rate in bytes per second, enforced by Token Bucket. |
| `reserved_port` | integer or null | `null` | Static public port reserved exclusively for this client. `null` means dynamic allocation. |
| `max_connections` | integer or null | Infinity | Maximum number of simultaneous active tunnels this client may open. |

> **Note:** These settings are only effective when `enable_auth` is `true`. If authentication is off, the server ignores these values and behaves as if every client had unlimited rate, dynamic port allocation, and unlimited connections.

### `client` Object

| Key | Type | Description |
| --- | --- | --- |
| `server_addr` | string | Remote server address, e.g. `"your-public-vps.com:1234"`. |
| `local_addr` | string | Local service address to forward traffic to, e.g. `"127.0.0.1:8080"`. |
| `check_hostname` | boolean | Whether to validate the TLS certificate hostname. |
| `client_id` | string | UUID identifying this client. Must match an entry in `allowed_clients` if auth is enabled. |

### Example Configuration

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
            "reserved_port": 7070,
            "max_connections": 10
          },
          "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d": {
            "rate_limit": 524288,
            "reserved_port": null,
            "max_connections": 5
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

In the example above, `1048576` bytes/s equals 1 MB/s and `524288` bytes/s equals 512 KB/s. The client with `reserved_port: null` will receive a dynamic port.

To run using the configuration file, use the `--config` flag:

    python main.py --config config/config.json server
    python main.py --config config/config.json client

---

## Protocol Specification (`PROTO.md` Summary)

All communication between client and server is encapsulated within a strict byte-stream framing structure:

    { start_byte (0x42) | payload | end_byte (0x52) }

Multi-byte integers (`reserved_port`, `connection_id`, `data_length`) are transmitted in big-endian order.

Data packets (`0x04`) have a safe network payload limit of 1393 bytes. The application uses an internal buffer size of 4096 bytes for efficient asynchronous streaming over TLS.

### Command Matrix

| Command | Hex Code | Direction | Description |
| --- | --- | --- | --- |
| Error | `0x00` | Server → Client | Handshake rejected / No ports available |
| Reservation Req | `0x01` | Client → Server | Initial port reservation request |
| Reservation Resp | `0x01` | Server → Client | Successful handshake containing the `reserved_port` |
| New Connection | `0x02` | Server → Client | Notification of a new incoming public connection |
| Connection Ack | `0x03` | Client → Server | Client confirmation (accept/reject) of the connection |
| Data Transfer | `0x04` | Both | Tunneled data transmission |
| Close Connection | `0x05` | Both | Close specific tunnel stream `connection_id` |
| Keep-Alive | `0x06` | Both | Ping/Pong heartbeat, required every 30 seconds |
| Error Signal | `0xFF` | Both | System error broadcast |

---

## CLI Reference

### Global Arguments

- `--log-level`: `info` or `debug` (default: `info`).
- `--cert`: Path to the SSL certificate file.
- `--key`: Path to the SSL private key file.
- `--config`: Path to a custom JSON configuration file.

### Server Subcommand Options

- `-b, --bind-addr`: Host and port to bind the server to, e.g. `0.0.0.0:1234`.
- `--clients-limit`: Maximum number of simultaneous tunnel clients.
- `--dynamic-port-allocation-range`: Range of ports available for dynamic allocation, e.g. `2000-65535`.

### Client Subcommand Options

- `-s, --server-addr`: Remote tunnel server address.
- `-l, --local-addr`: Local target application service address.
- `--client-id`: 16-byte hex UUID for server registration.
- `--check-hostname`: Validate the TLS certificate hostname (default: `true`).

---

## Performance & Diagnostics

- **Throughput:** Up to 200 MB/s over high-speed networks, primarily bounded by CPU TLS processing overhead and network bandwidth.
- **Keep-Alive Thresholds:** The client sends a heartbeat every 30 seconds. The server enforces a strict 90-second timeout; clients failing to respond within this window are gracefully disconnected, and their public ports are recycled back into the allocation pool.
