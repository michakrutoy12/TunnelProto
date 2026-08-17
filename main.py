import argparse
import logging
import signal

import asyncio
from src.client import Client
from src.server import Server
from src.config import get_config, Config

import os
import subprocess


_log_level = {
	'info': logging.INFO,
	'debug': logging.DEBUG
}

async def main(app):
	loop = asyncio.get_running_loop()

	for sig in (signal.SIGINT, signal.SIGTERM):
	    loop.add_signal_handler(sig, lambda: asyncio.create_task(app.stop()))

	await app.run()

if __name__ == '__main__':
	parser = argparse.ArgumentParser(
		prog='Tunnel',
		description='This script allows you to create a tunnel from the public internet to a local machine'
	)
	parser.add_argument('--log-level',
		type=str, required=False,
		default='info', help='info/debug'
	)

	parser.add_argument('--cert',
		type=str, required=False, default='certs/server.pem',
		help='Path to SSL certificate file (default: certs/server.pem)'
	)
	parser.add_argument('--key',
		type=str, required=False, default='certs/server.key',
		help='Path to SSL private key file (default: certs/server.key)'
	)
	parser.add_argument('--config',
		type=str, required=False,
		help='Path to config file (default: config/config.json)'
	)

	subparsers = parser.add_subparsers(dest='mode', help='Mode to run in', required=True)

	# Server mode parser
	server_parser = subparsers.add_parser('server', help='Run in server mode')
	server_parser.add_argument('-b', '--bind-addr', 
		type=str, required=False,
		help='Address to bind server to (bind_addr:port, default: 127.0.0.1:1234)',
		default='127.0.0.1:1234'
	)
	server_parser.add_argument('--clients-limit', 
		type=int, required=False,
		help='Maximum number of connected clients (default: 10)',
		default=10
	)
	
	# Client mode parser
	client_parser = subparsers.add_parser('client', help='Run in client mode')
	client_parser.add_argument('-s', '--server-addr', 
		type=str, required=False,
		help='Server address to connect to (server_addr:port, default: 127.0.0.1:1234)',
		default='127.0.0.1:1234'
	)
	client_parser.add_argument('-l', '--local-addr',
		type=str, required=False,
		help='Local service address (addr:port, default: 127.0.0.1:8080)',
		default='127.0.0.1:8080'
	)

	client_parser.add_argument('--client-id',
		type=str, required=False,
		help='Client ID'
	)
	client_parser.add_argument('--check-hostname',
		type=bool, required=False, default=True,
		help='Check the hostname from the certificate when connecting (default: True)'
	)

	args = parser.parse_args()

	if args.config:
		config = get_config(args.config)
	else:
		config = Config()
		config.parse_args(args)

	logging.basicConfig(level=_log_level.get(config.log_level, logging.INFO))

	if args.mode == 'server':
		app = Server(*config.server_values)
	elif args.mode == 'client':
		app = Client(*config.client_values)

	try:
		asyncio.run(main(app))
	except KeyboardInterrupt:
		logging.info("Keyboard interrupt.")
	except Exception as err:
		logging.error(f"Error: {err}. Stopping...")
