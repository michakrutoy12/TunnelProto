# Tunnel
A lightweight, asynchronous TCP tunnel written in pure Python, allowing public internet access to a local service behind NAT or firewall. It uses a custom binary protocol to forward data between a public server and a local client.

**Beta Status** – This project is under active development. It has been tested with HTTP web servers and Minecraft servers, but may still contain bugs or performance issues. Use at your own risk in production environments.

## Features
* **Pure Python** – no external dependencies, runs on Python 3.7+ (tested on Python 3.14)
* **Asynchronous I/O** – uses asyncio for efficient concurrency
* **Custom binary protocol** – minimal overhead (7‑byte header) with keep‑alive and error handling
* **Port reservation** – dynamic port allocation on the server for each client
* **Multiple connections** – each client can handle multiple simultaneous tunnels
* **Keep‑alive** – detects stale connections and cleans up resources

## Requirements
* Python 3.7 or higher
* No third‑party packages required

## Installation
Clone the repository and run the script directly:

```bash
git clone https://github.com/michakrutoy12/TunnelProto
cd tunnel
python main.py --help
```

## Usage
The tool operates in two modes: server and client.

### Server Mode
Start the public server:

```bash
python main.py server --bind-addr <address:port>
```

* `--bind-addr` – IP and port to listen on (e.g., 0.0.0.0:8080)
* `--log-level` (optional) – info or debug

**Example:**

```bash
python main.py server --bind-addr 0.0.0.0:8080 --log-level debug
```
The server will listen for client connections and allocate random ports (2000‑65535) for each tunnel.

### Client Mode
Run the client on your local machine:

```bash
python main.py client --server-addr <server:port> --local-addr <local:port>
```

* `--server-addr` – public server address (e.g., example.com:8080)
* `--local-addr` – local service to expose (e.g., 127.0.0.1:80 for HTTP)

**Example:**

```bash
python main.py client --server-addr myserver.com:8080 --local-addr 127.0.0.1:25565
```
Once connected, the client will reserve a port on the server. Any incoming connection to that public port will be tunneled to your local service.

## Protocol
The communication uses a binary packet format:

`{0x42, payload, 0x52}`

Full details are documented in PROTO.md. Key commands include:
* Handshake (port reservation)
* Connection notifications
* Data transfer (max payload 4096 bytes)
* Keep‑alive (every 30 seconds)
* Error and close notifications

## Stability & Testing
This tunnel has been successfully used to expose:
* HTTP servers (Apache, Nginx, development servers)
* Minecraft Java Edition servers (port 25565)

However, due to the custom protocol and minimal error recovery, you may encounter:
* Unexpected disconnections under high load
* Race conditions in connection management (addressed with locks, but still evolving)
* Potential memory leaks if connections are not closed properly

We welcome bug reports and contributions to improve robustness.

>  **Security Note:** The protocol does not include encryption or authentication. Do not expose sensitive services over this tunnel without additional security layers (e.g., VPN, TLS, or SSH forwarding).

## License
This project is licensed under the Apache License 2.0 – see the LICENSE file for details.
