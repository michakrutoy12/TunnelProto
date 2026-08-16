# Tunnel

**Tunnel** is a lightweight tool written in **pure Python** using `asyncio` [cite: 1, 3, 4]. It allows you to expose a local service (like a web server or a game server) to the public internet through a remote server [cite: 1, 2].

## Features
* **Pure Python**: Zero third-party dependencies required [cite: 1, 3, 4].
* **Async Powered**: Built entirely on top of `asyncio` for high concurrency [cite: 1, 3, 4].
* **Custom Protocol**: Implementation of a custom framing byte-stream protocol [cite: 2, 3, 4].
* **Multiplexing**: Supports multiple connections over a single master tunnel [cite: 3, 4].

---

## How It Works
The project uses a simple 3-phase custom binary protocol over TCP [cite: 2]:
1. **Handshake Phase**: Client requests a public port reservation from the server [cite: 2, 3, 4].
2. **Connection Phase**: Server notifies the client about incoming public traffic [cite: 2, 3, 4].
3. **Data Transfer Phase**: Binary data chunks are packed, forwarded, and unpacked on both sides [cite: 2, 3, 4].

---

## Usage

### 1. Run the Server
Deploy the server on a public machine (VPS) with an open port [cite: 1, 4].

```bash
python main.py --log-level info server --bind-addr 0.0.0.0:8000
```
* Change `8000` to your desired control port [cite: 1, 4].

### 2. Run the Client
Run the client on your local machine to bridge your local app with the remote server [cite: 1, 3].

```bash
python main.py --log-level info client --server-addr YOUR_VPS_IP:8000 --local-addr 127.0.0.1:25565
```
* Replace `YOUR_VPS_IP` with your actual server IP address [cite: 1, 3].
* Replace `25565` with the port of your local service [cite: 1, 3].

---

## Stability and Testing
* **Disclaimer**: This is a custom protocol implementation [cite: 2, 3, 4]. It may experience minor instability, edge-case disconnects, or performance bottlenecks under heavy production loads.
* **What works**: The application was successfully tested and proved stable for:
  * **HTTP Web Servers**: Forwarding standard web traffic and assets.
  * **Minecraft Servers**: Tunneling game traffic with acceptable latency and connection stability.
