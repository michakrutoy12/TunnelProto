import argparse
import logging
import warnings
import signal

import asyncio
from src.client import Client
from src.server import Server
from src.config import get_config, Config

import os
import subprocess

warnings.filterwarnings(
	"ignore", 
	category=DeprecationWarning, 
	message=".*asyncio.iscoroutinefunction.*"
)

_log_level = {
	'info': logging.INFO,
	'debug': logging.DEBUG,
	'warning': logging.WARNING,
	'error': logging.ERROR
}

async def main(app):
	loop = asyncio.get_running_loop()
	
	stop_event = asyncio.Event()

	def signal_handler():
		stop_event.set()

	for sig in (signal.SIGINT, signal.SIGTERM):
		loop.add_signal_handler(sig, signal_handler)

	app_task = asyncio.create_task(app.run())
	await stop_event.wait()

	try:
		await asyncio.wait_for(app.stop(), timeout=5.0)
	except asyncio.TimeoutError:
		logging.warning("Force Termination: app.stop() timed out after 5 seconds.")

	app_task.cancel()
	try:
		await app_task
	except asyncio.CancelledError:
		pass

if __name__ == '__main__':
	parser = argparse.ArgumentParser(
		prog='Tunnel',
		description='This script allows you to create a tunnel from the public internet to a local machine'
	)
	parser.add_argument('--log-level',
		type=str, required=False,
		default='info', help='info/debug/warning/error'
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
	server_parser.add_argument('--dynamic-port-allocation-range', 
		type=str, required=False,
		help='The range of ports available for dynamic allocation between clients for which no port is reserved ([first port]-[last port], default: 2000-65535)',
		default='2000-65535'
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
		help='Client ID', default='a'*32
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

	logging.basicConfig(level=_log_level.get(config.log_level, logging.INFO), 
						format='%(asctime)s - %(levelname)s: %(message)s')

	if args.mode == 'server':
		app = Server(*config.server_values)
	elif args.mode == 'client':
		app = Client(*config.client_values)

	try:
		import uvloop
	except ImportError:
		logging.warning("Unable to import uvloop, asyncio will be used")
		uvloop = asyncio

	try:
		uvloop.run(main(app))
	except Exception as err:
		logging.error(f"Critical error: {err}. Stopping...")
