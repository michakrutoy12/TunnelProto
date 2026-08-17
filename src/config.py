import json
import os
import logging
import uuid

_temp_uuid = str(uuid.uuid4())

default_config = {
	'log_level': 'info',
	'cert': 'certs/server.pem',
	'key': 'certs/server.key',

	'server': {
		'dynamic_port_allocation_range': [2000, 65535],
		'bind_addr': '127.0.0.1:1234',
		'enable_auth': False,
		'allowed_clients': {
			_temp_uuid: {
				'rate_limit': float('inf'),
				'reserved_port': None,
				'max_connections': None,
			}
		},
		'clients_limit': 10,
	},
	'client': {
		'server_addr': '127.0.0.1:1234',
		'local_addr': '127.0.0.1:8080',
		'check_hostname': True,
		'client_id': _temp_uuid,
	}
}

class Config:
	def __init__(self, values=default_config):
		self._values = values

	def parse_args(self, args):
		self._values['log_level'] = args.log_level
		self._values['cert'] = args.cert
		self._values['key'] = args.key

		if args.mode == 'server':
			self._values['server']['bind_addr'] = args.bind_addr
			self._values['server']['enable_auth'] = False
			self._values['server']['clients_limit'] = args.clients_limit
			self._values['server']['dynamic_port_allocation_range'] = args.dynamic_port_allocation_range
		if args.mode == 'client':
			self._values['client']['server_addr'] = args.server_addr
			self._values['client']['local_addr'] = args.local_addr
			self._values['client']['check_hostname'] = args.check_hostname
			self._values['client']['client_id'] = args.client_id

	@property
	def client_values(self):
		val = self._values['client']
		return val['server_addr'], val['local_addr'], self._values['cert'], val['check_hostname'], val['client_id']

	@property
	def server_values(self):
		val = self._values['server']
		return val['bind_addr'], self._values['cert'], self._values['key'], val['enable_auth'], val['allowed_clients'], \
				val['clients_limit'], val['dynamic_port_allocation_range']

	@property
	def log_level(self):
		return self._values['log_level']

	@property
	def values(self):
		return self._values
	

def validate_and_merge(user_cfg, def_cfg, path=""):
	final_cfg = {}
	
	for key in user_cfg:
		full_path = f"{path}.{key}" if path else key
		if key not in def_cfg:
			logging.warning(f"Extra attribute in the config: '{full_path}'")
			
	for key, def_value in def_cfg.items():
		full_path = f"{path}.{key}" if path else key
		
		if key not in user_cfg:
			final_cfg[key] = def_value
		elif isinstance(def_value, dict) and isinstance(user_cfg[key], dict):
			if key == 'allowed_clients':
				final_cfg[key] = user_cfg[key]
			else:
				final_cfg[key] = validate_and_merge(user_cfg[key], def_value, full_path)
		else:
			final_cfg[key] = user_cfg[key]
			
	return final_cfg

def generate_default_config():
	os.makedirs('config', exist_ok=True)
	if not os.path.exists('config/config.json'):
		with open('config/config.json', 'w', encoding='utf-8') as file:
			json.dump(default_config, file, ensure_ascii=False, indent=4)

def get_config(filename='config/config.json'):
	if not os.path.exists(filename):
		logging.warning('Configuration file not found. Creating a default one.')
		generate_default_config()
		return Config(default_config.copy())

	with open(filename, 'r', encoding='utf-8') as file:
		try:
			user_config = json.load(file)
		except json.JSONDecodeError:
			logging.error('Error reading JSON. Using default settings..')
			return Config(default_config.copy())

	valid_config = validate_and_merge(user_config, default_config)
	return Config(valid_config)
