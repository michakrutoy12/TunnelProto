import asyncio
import logging
import time

_START_BYTE = b'\x42'
_END_BYTE = b'\x52'
_PAYLOAD_LENGTH = 4096
_KEEPALIVE_INTERVAL = 30
_HANDSHAKE_TIMEOUT = 10


class Client:
    def __init__(self, server_addr, local_addr):
        server_addr = server_addr.split(':')
        local_addr = local_addr.split(':')

        self.server_addr = (server_addr[0], int(server_addr[1]))
        self.local_addr = (local_addr[0], int(local_addr[1]))

        self.connections = {}
        self.keep_alive_timer = time.time()
        self.last_server_keepalive = time.time()
        self.conn_lock = asyncio.Lock()

        self.master_reader = None
        self.master_writer = None

    async def handshake(self):
        state = False
        try:
            await self.write(self.master_writer, [b'\x01'])

            resp = await asyncio.wait_for(
                self._read_handshake_response(self.master_reader),
                timeout=_HANDSHAKE_TIMEOUT
            )

            # PROTO.md defines the server handshake response as:
            # {start, status, reserved_port[0], reserved_port[1], end}
            # So resp[0] is the status byte.
            if not resp or resp[0] != 0x01:
                raise Exception('No ports available or handshake rejected')

            port = int.from_bytes(resp[1:3], byteorder='big')
            logging.info(f'Handshake successful. Reserved address: {self.server_addr[0]}:{port}')

            await self.write(self.master_writer, [b'\x01'])
            state = True
        except Exception as err:
            state = False
            logging.debug(f'Handshake unsuccessful: {err}')

        return state

    async def _read_handshake_response(self, reader):
        try:
            start = await reader.readexactly(1)
            if start != _START_BYTE:
                return None

            status = await reader.readexactly(1)

            if status == b'\x00':
                end = await reader.readexactly(1)
                if end != _END_BYTE:
                    return None
                return status

            if status == b'\x01':
                port_bytes = await reader.readexactly(2)
                end = await reader.readexactly(1)
                if end != _END_BYTE:
                    return None
                return status + port_bytes

            return None
        except asyncio.IncompleteReadError:
            return None

    async def listen(self):
        while self.master_writer and not self.master_writer.is_closing():
            data = await self.read_packet(self.master_reader)
            if not data:
                break

            cmd = data[0]

            if cmd == 0x02:
                if len(data) < 3:
                    logging.debug('Invalid connection notification length')
                    continue

                uid = data[1:3]
                logging.debug(f'New connection notification for {uid.hex()}')

                async with self.conn_lock:
                    duplicate = uid in self.connections

                if duplicate:
                    logging.debug(f'Duplicate connection notification for {uid.hex()}; rejecting')
                    try:
                        await self.write(self.master_writer, [b'\x03', b'\x00', uid])
                    except Exception:
                        pass
                    continue

                try:
                    reader, writer = await asyncio.open_connection(*self.local_addr)
                    status = b'\x01'
                except Exception as err:
                    status = b'\x00'
                    logging.debug(f'Local connection failed for {uid.hex()}: {err}')

                try:
                    await self.write(self.master_writer, [b'\x03', status, uid])
                except Exception as err:
                    logging.debug(f'Failed to send connection ack for {uid.hex()}: {err}')
                    break

                if status[0] == 0x01:
                    logging.debug(f'Client {uid.hex()} accepted')
                    await self.register_new_client(uid, reader, writer)
                else:
                    logging.debug(f'Client {uid.hex()} rejected')

            elif cmd == 0x05:
                if len(data) < 3:
                    continue

                uid = data[1:3]
                await self.close_connection(uid, notify=False)

            elif cmd == 0x04:
                if len(data) < 5:
                    logging.debug('Invalid data packet length')
                    continue

                conn_id = data[1:3]
                data_length = int.from_bytes(data[3:5], byteorder='big')

                if data_length != len(data) - 5:
                    logging.debug('Data length mismatch')
                    await self._send_error(self.master_writer, 0x00)
                    break

                payload = data[5:]

                async with self.conn_lock:
                    conn = self.connections.get(conn_id)
                    if not conn:
                        logging.debug(f'Data for unknown connection {conn_id.hex()}')
                        continue
                    local_writer = conn['writer']

                try:
                    local_writer.write(payload)
                    await local_writer.drain()
                except Exception as err:
                    logging.debug(f'Data forwarding error from server to connection {conn_id.hex()}: {err}')
                    await self.close_connection(conn_id, notify=True)

            elif cmd == 0x06:
                self.last_server_keepalive = time.time()
                logging.debug('Keep-alive reply received')

            elif cmd == 0xFF:
                error_code = data[1] if len(data) >= 2 else 0x00
                logging.error(f'Server error notification {error_code:#x}; closing')
                break

            else:
                logging.debug(f'Unknown command from server: {cmd:#x}')
                await self._send_error(self.master_writer, 0x00)
                break

    async def register_new_client(self, uid, reader, writer):
        logging.info(f'New local connection mapped. uid: {uid.hex()}')

        async with self.conn_lock:
            duplicate = uid in self.connections
            if not duplicate:
                self.connections[uid] = {
                    'reader': reader,
                    'writer': writer,
                    'task': None
                }

        if duplicate:
            writer.close()
            await writer.wait_closed()
            return

        task = asyncio.create_task(self.inet_reader(uid))

        async with self.conn_lock:
            if uid in self.connections:
                self.connections[uid]['task'] = task

    async def inet_reader(self, uid):
        logging.debug(f'Starting tunneling from local connection to server for {uid.hex()}')

        try:
            async with self.conn_lock:
                conn = self.connections.get(uid)
                if not conn:
                    return
                local_reader = conn['reader']

            while True:
                async with self.conn_lock:
                    if uid not in self.connections:
                        break

                payload = await local_reader.read(_PAYLOAD_LENGTH)
                if not payload:
                    break

                await self.write(
                    self.master_writer,
                    [b'\x04', uid, len(payload).to_bytes(2, byteorder='big'), payload]
                )
        except Exception as err:
            logging.debug(f'Error {err} in inet_reader for {uid.hex()}')
        finally:
            await self.close_connection(uid, notify=True)

    async def close_connection(self, uid, notify=True):
        async with self.conn_lock:
            conn = self.connections.pop(uid, None)

        if not conn:
            return

        task = conn.get('task')
        if task and task is not asyncio.current_task():
            task.cancel()

        try:
            writer = conn.get('writer')
            if writer and not writer.is_closing():
                writer.close()
                await writer.wait_closed()
        except Exception as err:
            logging.debug(f'Error closing local writer for {uid.hex()}: {err}')

        if notify:
            try:
                if self.master_writer and not self.master_writer.is_closing():
                    await self.write(self.master_writer, [b'\x05', uid])
            except Exception as err:
                logging.debug(f'Error notifying server about close {uid.hex()}: {err}')

        logging.debug(f'Connection {uid.hex()} closed')

    async def keep_alive_checker(self):
        try:
            while self.master_writer and not self.master_writer.is_closing():
                now = time.time()
                if now - self.keep_alive_timer >= _KEEPALIVE_INTERVAL:
                    await self.write(self.master_writer, [b'\x06'])
                    self.keep_alive_timer = now
                    logging.debug('Keep-alive packet sent')

                await asyncio.sleep(5)
        except Exception as err:
            logging.debug(f'Keep-alive checker error: {err}')

    async def _send_error(self, writer, error_code=0x00):
        try:
            if writer and not writer.is_closing():
                await self.write(writer, [b'\xFF', bytes([error_code])])
        except Exception:
            pass

    async def write(self, writer, payload):
        payload_bytes = b''.join(payload)

        if len(payload_bytes) > _PAYLOAD_LENGTH + 5:
            raise ValueError('Payload too large')

        data = _START_BYTE + payload_bytes + _END_BYTE
        writer.write(data)
        await writer.drain()

    async def read_packet(self, reader):
        try:
            start = await reader.readexactly(1)
            if start != _START_BYTE:
                return None

            cmd_byte = await reader.readexactly(1)
            cmd = cmd_byte[0]

            if cmd == 0x04:
                header = await reader.readexactly(4)
                data_length = int.from_bytes(header[2:4], byteorder='big')

                if data_length > _PAYLOAD_LENGTH:
                    raise ValueError(f'Data length {data_length} exceeds max')

                payload = await reader.readexactly(data_length)
                end = await reader.readexactly(1)

                if end != _END_BYTE:
                    return None

                return b'\x04' + header + payload

            extra_lengths = {
                0x01: 0,
                0x02: 2,
                0x03: 3,
                0x05: 2,
                0x06: 0,
                0xFF: 1,
            }

            if cmd not in extra_lengths:
                raise ValueError(f'Unknown command: {cmd:#x}')

            extra = await reader.readexactly(extra_lengths[cmd]) if extra_lengths[cmd] else b''
            end = await reader.readexactly(1)

            if end != _END_BYTE:
                return None

            return bytes([cmd]) + extra

        except asyncio.IncompleteReadError:
            return None
        except ValueError as err:
            logging.debug(f'Protocol read error: {err}')
            return None

    async def run(self):
        logging.info(f'Starting tunneling to local address: {self.local_addr[0]}:{self.local_addr[1]}')

        try:
            self.master_reader, self.master_writer = await asyncio.open_connection(*self.server_addr)
        except Exception as err:
            logging.error(f'Unable to connect to server: {err}')
            return

        if not await self.handshake():
            await self.stop()
            return

        try:
            results = await asyncio.gather(
                self.listen(),
                self.keep_alive_checker(),
                return_exceptions=True
            )

            for result in results:
                if isinstance(result, Exception):
                    logging.debug(f'Task ended with error: {result!r}')
        finally:
            await self.stop()

    async def stop(self):
        try:
            async with self.conn_lock:
                conns = list(self.connections.values())
                self.connections.clear()

            for conn in conns:
                task = conn.get('task')
                if task and task is not asyncio.current_task():
                    task.cancel()

                writer = conn.get('writer')
                if writer:
                    try:
                        if not writer.is_closing():
                            writer.close()
                            await writer.wait_closed()
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            if self.master_writer and not self.master_writer.is_closing():
                self.master_writer.close()
                await self.master_writer.wait_closed()
        except Exception:
            pass
