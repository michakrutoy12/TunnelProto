# Tunnel Protocol
**Tunnel protocol** is a set of rules, that allows you to create a tunnel from the public internet to a local machine
## How it Works
Communication occurs in a **byte stream** of the type `{start_byte, payload, end_byte}`
- **start_byte** - `0x42`
- **end_byte** - `0x52`

### First Phase - Handshake
---
The **Client** must send a `{start, cmd, end}` message after connecting to the server
- **cmd** :
 1. `0x01` - Port reservation request

The **Server** should respond with `{start, status, reserved_port[0], reserved_port[1], end}`
- **status** :
	1. `0x00` - Error
	2. `0x01` - Success
- **reserved_port** - a two-byte number representing the reserved port in big-endian byte order

The **Client** should respond with acknowledgment: `{start, 0x01, end}`

### Second Phase - Connection Notification
---
The **Server** listens for incoming connections on the reserved port. When a new connection is accepted from the public internet, the server sends a connection notification to the client.

Connection notification format: `{start, 0x02, connection_id[0], connection_id[1], end}`
- `0x02` - New connection notification
- `connection_id` - Two-byte unique identifier for this connection (big-endian)

The **Client** responds with connection acknowledgment: `{start, 0x03, connection_id[0], connection_id[1], end}`
- `0x03` - Connection acknowledgment

**After this**, the client should connect to the local host and start tunneling data *(Third phase)*.

### Third Phase - Data Transfer
---
The **server** sends packets with a maximum payload size of 1393 bytes, resulting in a total packet size of 1400 bytes (including 7 bytes of overhead). The **client** sends data in the same format.
**Data packet format:** `{start, 0x04, connection_id[0], connection_id[1], data_length[0], data_length[1], data, end}`
- `0x04` - Data transfer command
- `data_length` - Two-byte number representing the length of the data payload (big-endian).
- `data` - The actual data being transferred

**Connection close notification:** `{start, 0x05, connection_id[0], connection_id[1], end}`
- `0x05` - Connection close notification

### Error handling:
---
The **Server** or **Client** can send error notification: {start, 0xFF, error_code, end}
- `0xFF` - Error command
- **error_code** :
	1. `0x00` - General error
	2. `0x01` - Timeout error
	3. `0x02` - Connection closed

### Keep-Alive:
---
To maintain the tunnel, client should send keep-alive packets every 30 seconds: `{start, 0x06, end}`
- `0x06` - Keep-alive command

The **server** must respond with an acknowledgement `{start, 0x06, end}`
