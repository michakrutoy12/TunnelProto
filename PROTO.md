# Tunnel Protocol

**Tunnel Protocol** is a set of rules that allows you to create a tunnel from the public internet to a local machine.

## General Packet Structure

All communication is performed in a byte stream using the following envelope:
`{start_byte, payload, end_byte}`

- **start_byte** – `0x42`
- **end_byte** – `0x52`

The payload is a sequence of bytes that depends on the command being sent. The maximum payload size for data packets (`0x04`) is 1393 bytes, resulting in a total packet size of 1400 bytes (including 7 bytes of overhead). Other commands have fixed small sizes.

---

## 1. Handshake Phase

The handshake establishes a tunnel session and reserves a port for the client.

### 1.1 Client → Server: Reservation Request
The client sends a request to reserve a public port on the server.
- **Format:** `{0x42, 0x01, 0x52}`
- `0x01` – command: port reservation request

### 1.2 Server → Client: Reservation Response
The server responds with the result of the reservation.
- **Format (success):** `{0x42, 0x01, reserved_port[0], reserved_port[1], 0x52}`
  - `0x01` – status: success
  - `reserved_port` – two-byte port number (big-endian) that the client can use from the public internet
- **Format (failure):** `{0x42, 0x00, 0x52}`
  - `0x00` – status: error

### 1.3 Client → Server: Acknowledgment
After receiving a successful response, the client must send an acknowledgment to finalise the handshake.
- **Format:** `{0x42, 0x06, 0x52}`
- `0x06` – command: acknowledgment / keep-alive (same code)

---

## 2. Connection Notification (Incoming Tunnel)

Once the handshake is complete, the server listens on the reserved public port. When a new incoming connection is accepted from the public internet, the server notifies the client.

### 2.1 Server → Client: New Connection
- **Format:** `{0x42, 0x02, connection_id[0], connection_id[1], 0x52}`
- `0x02` – command: new connection notification
- `connection_id` – two-byte unique identifier (big-endian) for this specific tunneled connection

### 2.2 Client → Server: Connection Acknowledgment
The client must respond to accept or reject the incoming connection.
- **Format:** `{0x42, 0x03, status, connection_id[0], connection_id[1], 0x52}`
- `0x03` – command: connection acknowledgment
- `status` – one byte indicating connection result
- `connection_id` – same identifier as received

*After this, the client should connect to the local host and start tunneling data.*

---

## 3. Data Transfer Phase

After a connection is accepted, both sides can exchange data packets.

### 3.1 Data Packet Format (both directions)
- **Format:** `{0x42, 0x04, connection_id[0], connection_id[1], data_length[0], data_length[1], data, 0x52}`
- `0x04` – command: data transfer
- `connection_id` – two-byte identifier of the tunneled connection (big-endian)
- `data_length` – two-byte length of the data payload (big-endian)
- `data` – the actual data being transferred (up to 1393 bytes)

### 3.2 Connection Close Notification
Either side may close a specific tunneled connection.
- **Format:** `{0x42, 0x05, connection_id[0], connection_id[1], 0x52}`
- `0x05` – command: close connection notification
- `connection_id` – the identifier of the connection to close

---

## 4. Keep-Alive

To maintain the tunnel session, the client must send a keep-alive packet every 30 seconds.
- **Client → Server:** `{0x42, 0x06, 0x52}`
- **Server → Client (reply):** `{0x42, 0x06, 0x52}`
- `0x06` – command: keep-alive (both request and reply)

---

## 5. Error Handling

Either side can send an error notification to signal a problem.
- **Format:** `{0x42, 0xFF, error_code, 0x52}`
- `0xFF` – command: error command
- `error_code` – one byte indicating the type:
  - `0x00` – general error
  - `0x01` – timeout error
  - `0x02` – connection closed

---

## Summary of Commands

| Command | Value (Hex) | Value (Dec) | Direction | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Error** | `0x00` | 0 | Server → Client | Handshake: error response (no port) |
| **Success / Req** | `0x01` | 1 | Client → Server | Handshake: port reservation request |
| **Success / Resp**| `0x01` | 1 | Server → Client | Handshake: success response (with port) |
| **New Conn** | `0x02` | 2 | Server → Client | New incoming connection notification |
| **Conn Ack** | `0x03` | 3 | Client → Server | Connection acknowledgment |
| **Data** | `0x04` | 4 | Both | Data transfer |
| **Close** | `0x05` | 5 | Both | Connection close notification |
| **Keep-Alive** | `0x06` | 6 | Both | Keep-alive / Handshake acknowledgment |
| **Error Cmd** | `0xFF` | 255 | Both | Error notification |

---

## Notes

- All multi-byte integers (`reserved_port`, `connection_id`, `data_length`) are transmitted in **big-endian** order.
- The server sends packets with a maximum payload size of 1393 bytes, resulting in a total packet size of 1400 bytes (including 7 bytes of overhead). The client sends data in the same format.
