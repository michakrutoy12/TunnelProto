import argparse
import logging

import asyncio
from src.client import Client
from src.server import Server

_log_level = {
	'info': logging.INFO,
	'debug': logging.DEBUG
}

if __name__ == '__main__':
	parser = argparse.ArgumentParser(
		prog='Tunnel',
		description='This script allows you to create a tunnel from the public internet to a local machine'
	)
	parser.add_argument('--log-level',
		type=str, required=False,
		default='info', help='info/debug'
	)
	subparsers = parser.add_subparsers(dest='mode', help='Mode to run in', required=True)

	# Server mode parser
	server_parser = subparsers.add_parser('server', help='Run in server mode')
	server_parser.add_argument('-b', '--bind-addr', 
		type=str, required=True,
		help='Address to bind server to (bind_addr:port)'
	)
	
	# Client mode parser
	client_parser = subparsers.add_parser('client', help='Run in client mode')
	client_parser.add_argument('-s', '--server-addr', 
		type=str, required=True,
		help='Server address to connect to (server_addr:port)'
	)
	client_parser.add_argument('-l', '--local-addr', 
		type=str, required=True,
		help='Local service address (addr:port)'
	)

	args = parser.parse_args()
	logging.basicConfig(level=_log_level.get(args.log_level, logging.INFO))
	
	if args.mode == 'server':
		app = Server(args.bind_addr)
	elif args.mode == 'client':
		app = Client(args.server_addr, args.local_addr)

	try:
		asyncio.run(app.run())
	except Exception as err:
		logging.error(f"Error: {err}. Stopping...")
	finally:
		asyncio.run(app.stop())
