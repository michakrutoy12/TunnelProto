import asyncio
import ssl
import random
import socket

import logging
import time

_START_BYTE = b'\x42'
_END_BYTE = b'\x52'
_PAYLOAD_LENGTH = 4096
_KEEPALIVE_TIMEOUT = 90
_CONFIRMATION_TIMEOUT = 30
_HANDSHAKE_TIMEOUT = 10


class TokenBucket:
    def __init__(self, rate: float, capacity: float = None):
        self.rate = rate
        self.capacity = capacity if capacity is not None else rate
        self.tokens = self.capacity
        self.last = time.time()
        self.lock = asyncio.Lock()
    
    async def consume(self, amount: float):
        wait_time = 0

        async with self.lock:
            now = time.time()

            delta = now - self.last
            self.tokens = min(self.capacity, self.tokens + delta * self.rate)
            self.last = now

            if self.tokens < amount:
                needed = amount - self.tokens
                wait_time = needed / self.rate
                
                self.tokens = 0
                self.last = now + wait_time
            else:
                self.tokens -= amount

        if wait_time > 0:
            await asyncio.sleep(wait_time)


class Server:
	def __init__(self, bind_addr, cert_path, key_path, enable_auth, allowed_clients, clients_limit, port_range):
		bind_addr = bind_addr.split(':')
		self.bind_addr = (bind_addr[0], int(bind_addr[1]))

		self.enable_auth = enable_auth

		self.clients_limit = clients_limit
		self.active_clients = 0
		self.clients_limit_lock = asyncio.Lock()

		self.cert_path = cert_path
		self.key_path = key_path

		self.available_ports = list(range(*port_range))
		if self.bind_addr[1] in self.available_ports:
			self.available_ports.remove(self.bind_addr[1])

		self.allowed_clients = {}
		for client in allowed_clients:
			if not 'reserved_port' in allowed_clients[client]:
				allowed_clients[client]['reserved_port'] = None
			if not 'rate_limit' in allowed_clients[client]:
				allowed_clients[client]['rate_limit'] = float('inf')
			if not 'max_connections' in allowed_clients[client]:
				allowed_clients[client]['max_connections'] = float('inf')

			if allowed_clients[client]['reserved_port'] in self.available_ports:
				self.available_ports.remove(allowed_clients[client]['reserved_port'])

			self.allowed_clients[bytes.fromhex(client.replace('-', ''))] = allowed_clients[client]

		self.connections = {}
		self.pending_confirmations = {}

		self.ports_lock = asyncio.Lock()
		self.conn_lock = asyncio.Lock()
		self.pending_lock = asyncio.Lock()

		self.server = None

	async def handler(self, reader, writer):
		uid = await self.handshake(reader, writer)
		if not uid:
			return

		keep_alive_task = asyncio.create_task(self.keep_alive_checker(uid))

		async with self.conn_lock:
			if uid in self.connections:
				self.connections[uid]['tasks'].add(keep_alive_task)

		try:
			while True:
				data = await asyncio.wait_for(self.read_packet(reader), timeout=_KEEPALIVE_TIMEOUT)
				if not data:
					break

				cmd = data[0]

				if cmd == 0x06:
					async with self.conn_lock:
						if uid not in self.connections:
							break
						self.connections[uid]['timer'] = time.time()
						reply_writer = self.connections[uid]['writer']

					try:
						await self.write(reply_writer, [b'\x06'])
					except Exception as err:
						logging.debug(f'Failed to send keep-alive reply to {uid.hex()}: {err}')
						break

					logging.debug(f'Keep-alive reply sent to {uid.hex()}')

				elif cmd == 0x05:
					if len(data) < 3:
						await self._send_error(writer, 0x00)
						break

					await self.close_connection(uid, data[1:3])

				elif cmd == 0x03:
					if len(data) < 4:
						await self._send_error(writer, 0x00)
						break

					conn_id = data[2:4]
					accepted = data[1] == 0x01

					async with self.pending_lock:
						if conn_id in self.pending_confirmations:
							self.pending_confirmations[conn_id] = accepted
						else:
							logging.debug(f'Ack for unknown/expired conn_id {conn_id.hex()}')

				elif cmd == 0xFF:
					error_code = data[1] if len(data) >= 2 else 0x00
					logging.info(f'Client {uid.hex()} sent error code {error_code:#x}; closing')
					await self.close_client(uid)
					break

				elif cmd == 0x04:
					async with self.conn_lock:
						await self.connections[uid]['bucket'].consume(len(data))

					if len(data) < 5:
						await self._send_error(writer, 0x00)
						break

					conn_id = data[1:3]
					data_length = int.from_bytes(data[3:5], byteorder='big')

					if data_length != len(data) - 5:
						logging.debug(f'Data length mismatch from {uid.hex()}')
						await self._send_error(writer, 0x00)
						break

					payload = data[5:]

					async with self.conn_lock:
						if uid not in self.connections:
							client_gone = True
						else:
							client_gone = False
							conns = self.connections[uid]['connections']

							if conn_id not in conns:
								conn_missing = True
							else:
								conn_missing = False
								local_writer = conns[conn_id][1]

					if client_gone:
						break

					if conn_missing:
						logging.debug(f'Data for unknown connection {conn_id.hex()} from client {uid.hex()}')
						continue

					try:
						local_writer.write(payload)
						await local_writer.drain()
					except Exception as err:
						logging.debug(f'Data forwarding error from client {uid.hex()} to connection {conn_id.hex()}: {err}')
						await self.close_connection(uid, conn_id)

				else:
					logging.debug(f'Unknown command {cmd:#x} from client {uid.hex()}')
					await self._send_error(writer, 0x00)
					break

		except Exception as err:
			logging.debug(f'Client {uid.hex()} error: {err}')
		finally:
			await self.close_client(uid)

	async def tunnel(self, reader, writer, uid):
		inet_uid = None

		try:
			async with self.conn_lock:
				if uid not in self.connections:
					raise Exception('Client disconnected')

				if len(self.connections[uid]['connections']) >= self.connections[uid]['max_connections']:
					raise Exception('Too many connections per client')

			inet_uid = await self._allocate_connection_id(uid)
			if inet_uid is None:
				raise Exception('No connection ids available')

			async with self.conn_lock:
				if uid not in self.connections:
					raise Exception('Client disconnected')

				client_writer = self.connections[uid]['writer']

				if inet_uid in self.connections[uid]['connections']:
					raise Exception('Connection id collision')

			async with self.pending_lock:
				self.pending_confirmations[inet_uid] = None

			conn_ip = writer.get_extra_info('peername')[0]

			logging.info(f'New connection {inet_uid.hex()}, {conn_ip} from client {uid.hex()}')
			await self.write(client_writer, [b'\x02', inet_uid, socket.inet_aton(conn_ip)])

			timer = time.time()
			confirmed = None

			while True:
				async with self.pending_lock:
					if inet_uid not in self.pending_confirmations:
						raise Exception('Connection confirmation expired')

					status = self.pending_confirmations[inet_uid]
					if status is not None:
						confirmed = status
						break

				if time.time() - timer >= _CONFIRMATION_TIMEOUT:
					async with self.pending_lock:
						self.pending_confirmations.pop(inet_uid, None)
					raise Exception('Waiting too long for connection confirmation')

				await asyncio.sleep(0.1)

			if not confirmed:
				raise Exception('Client rejected connection')

			logging.debug(f'Client {inet_uid.hex()} accepted.')

			async with self.pending_lock:
				self.pending_confirmations.pop(inet_uid, None)

			async with self.conn_lock:
				if uid not in self.connections:
					raise Exception('Client disconnected')

				if len(self.connections[uid]['connections']) >= self.connections[uid]['max_connections']:
					raise Exception('Too many connections per client')

				self.connections[uid]['connections'][inet_uid] = (reader, writer)

			while True:
				data = await reader.read(_PAYLOAD_LENGTH)
				if not data:
					break

				async with self.conn_lock:
					if uid not in self.connections or inet_uid not in self.connections[uid]['connections']:
						break

					client_writer = self.connections[uid]['writer']

				await self.write(
					client_writer,
					[b'\x04', inet_uid, len(data).to_bytes(2, byteorder='big'), data]
				)

		except Exception as err:
			logging.debug(
				f'{err} in tunnel, client {uid.hex()}, '
				f'connection {inet_uid.hex() if inet_uid else "?"}'
			)
		finally:
			if inet_uid is not None:
				async with self.pending_lock:
					self.pending_confirmations.pop(inet_uid, None)

			await self.close_connection(uid, inet_uid)

	async def _allocate_connection_id(self, client_uid):
		async with self.conn_lock:
			if client_uid not in self.connections:
				return None

			client_data = self.connections[client_uid]
			active = client_data['connections']

			for _ in range(65536):
				cid = client_data['next_conn_id'].to_bytes(2, byteorder='big')
				client_data['next_conn_id'] = (client_data['next_conn_id'] + 1) % 65536

				if cid not in active:
					return cid

		return None

	async def handshake(self, reader, writer):
		uid = None
		state = False

		try:
			req = await asyncio.wait_for(
				self.read_packet(reader),
				timeout=_HANDSHAKE_TIMEOUT
			)

			if req[:1] != b'\x01':
				raise Exception('Invalid handshake cmd')

			if self.enable_auth and req[1:] not in self.allowed_clients:
				raise Exception('Invalid UUID')

			async with self.clients_limit_lock:
				if self.active_clients >= self.clients_limit:
					raise Exception("Server overloaded")

			uid, port = await self.register_new_client(reader, writer, req[1:])
			async with self.clients_limit_lock:
				self.active_clients += 1

			# PROTO.md handshake response:
			# {start, status, reserved_port[0], reserved_port[1], end}
			await self.write(writer, [b'\x01', port.to_bytes(2, byteorder='big')])

			ack = await asyncio.wait_for(
				self.read_packet(reader),
				timeout=_HANDSHAKE_TIMEOUT
			)

			if ack != b'\x06':
				raise Exception('Invalid acknowledgment')

			state = True

		except Exception as err:
			logging.debug(f'Handshake unsuccessful: {err}')

			try:
				if writer and not writer.is_closing():
					await self.write(writer, [b'\x00'])
			except Exception:
				pass

			if uid:
				await self.close_client(uid)

			try:
				if writer and not writer.is_closing():
					writer.close()
					await writer.wait_closed()
			except Exception:
				pass

		if state:
			return uid

	async def register_new_client(self, reader, writer, client_id):
		async with self.ports_lock:
			if not self.available_ports:
				raise Exception('No ports available')

			if self.enable_auth and self.allowed_clients[client_id]['reserved_port']:
				port = self.allowed_clients[client_id]['reserved_port']
			else:
				port = self.available_ports.pop(0)

		try:
			uid = await self._allocate_client_uid(reader, writer, port, client_id)
		except Exception:
			async with self.ports_lock:
				self.available_ports.append(port)
			raise

		try:
			server = await asyncio.start_server(
				lambda r, w: self.tunnel(r, w, uid),
				'0.0.0.0',
				port
			)
		except Exception:
			async with self.conn_lock:
				self.connections.pop(uid, None)

			async with self.ports_lock:
				self.available_ports.append(port)

			raise

		async with self.conn_lock:
			if uid in self.connections:
				self.connections[uid]['server'] = server
			else:
				server.close()
				await server.wait_closed()

				async with self.ports_lock:
					self.available_ports.append(port)

				raise Exception('Client entry disappeared')

		logging.info(f'Reserving port {port} with client uid {uid.hex()}')
		return uid, port

	async def _allocate_client_uid(self, reader, writer, port, client_id):
		async with self.conn_lock:
			for _ in range(65536):
				uid = random.randbytes(2)

				if uid not in self.connections:
					self.connections[uid] = {
						'client_id': client_id,
						'port': port,
						'reader': reader,
						'writer': writer,
						'timer': time.time(),
						'connections': {},
						'server': None,
						'tasks': set(),
						'next_conn_id': 0,
						'bucket': TokenBucket(self.allowed_clients[client_id].get('rate_limit', float('inf')) if self.enable_auth else float('inf')),
						'max_connections': self.allowed_clients[client_id].get('max_connections', float('inf')) if self.enable_auth else float('inf')
					}
					return uid

			raise Exception('Could not allocate unique client id')

	async def keep_alive_checker(self, client_uid):
		try:
			while True:
				async with self.conn_lock:
					if client_uid not in self.connections:
						break

					timer = self.connections[client_uid]['timer']

				if time.time() - timer >= _KEEPALIVE_TIMEOUT:
					logging.debug(f'Client {client_uid.hex()} closed. Keep-alive timeout.')
					await self.close_client(client_uid, error_code=0x01)
					break

				await asyncio.sleep(3)

		except asyncio.CancelledError:
			pass
		except Exception as err:
			logging.debug(f'Keep-alive checker error for uid {client_uid.hex()}: {err}')
		finally:
			await self.close_client(client_uid)

	async def close_client(self, client_uid, error_code=None):
		async with self.conn_lock:
			client_data = self.connections.pop(client_uid, None)

		if not client_data:
			return

		client_writer = client_data.get('writer')

		if error_code is not None:
			try:
				if client_writer and not client_writer.is_closing():
					await self.write(client_writer, [b'\xFF', bytes([error_code])])
			except Exception:
				pass

		conns = list(client_data.get('connections', {}).items())

		for conn_id, (r, w) in conns:
			try:
				if client_writer and not client_writer.is_closing():
					await self.write(client_writer, [b'\x05', conn_id])
			except Exception:
				pass

			try:
				if not w.is_closing():
					w.close()
					await w.wait_closed()
			except Exception:
				pass

		try:
			server = client_data.get('server')
			if server is not None:
				server.close()
				await server.wait_closed()
		except Exception as err:
			logging.debug(f'Error closing server for client {client_uid.hex()}: {err}')

		try:
			if client_writer and not client_writer.is_closing():
				client_writer.close()
				await client_writer.wait_closed()
		except Exception as err:
			logging.debug(f'Error closing client writer for {client_uid.hex()}: {err}')

		for task in list(client_data.get('tasks', [])):
			if task is not asyncio.current_task():
				task.cancel()

		async with self.ports_lock:
			if not (self.enable_auth and self.allowed_clients[client_data['client_id']]['reserved_port']):
				self.available_ports.append(client_data['port'])
				self.available_ports.sort()

		logging.debug(f'Client {client_uid.hex()} closed')
		async with self.clients_limit_lock:
			self.active_clients -= 1

	async def close_connection(self, client_uid, conn_id):
		if conn_id is None:
			return

		async with self.conn_lock:
			client_data = self.connections.get(client_uid)
			if not client_data:
				return

			pair = client_data['connections'].pop(conn_id, None)
			client_writer = client_data.get('writer')

		if not pair:
			return

		r, w = pair

		try:
			if not w.is_closing():
				w.close()
				await w.wait_closed()
		except Exception as err:
			logging.debug(f'Error closing local connection {conn_id.hex()}: {err}')

		try:
			if client_writer and not client_writer.is_closing():
				await self.write(client_writer, [b'\x05', conn_id])
		except Exception as err:
			logging.debug(f'Error sending close notification for {conn_id.hex()}: {err}')

		logging.debug(f'Closed connection {conn_id.hex()} for client {client_uid.hex()}')

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
				0x01: 16,
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
		logging.info(f'Starting server at {self.bind_addr}')

		ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
		ssl_context.load_cert_chain(certfile=self.cert_path, keyfile=self.key_path)

		self.server = await asyncio.start_server(self.handler, *self.bind_addr, ssl=ssl_context, backlog=128)
		await self.server.serve_forever()

	async def stop(self):
		if self.server is not None:
			self.server.close()
			await self.server.wait_closed()

		async with self.conn_lock:
			uids = list(self.connections.keys())

		for uid in uids:
			await self.close_client(uid)
