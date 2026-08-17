import argparse
import os
import subprocess

parser = argparse.ArgumentParser(
    description="Generating a self-signed SSL certificate."
)
parser.add_argument(
    "--domain", 
    required=True, 
    help="Domain name for the certificate (e.g. localhost)"
)
parser.add_argument(
    "--ip", 
    default="127.0.0.1", 
    help="IP address for the certificate (default: 127.0.0.1)"
)

parser.add_argument(
    '--duration',
    default='365',
    help='Certificate validity period in days (default: 365)'
)

args = parser.parse_args()

os.makedirs("certs", exist_ok=True)

if not os.path.exists("certs/server.pem") or not os.path.exists("certs/server.key"):
    subprocess.run([
        "openssl", "req", 
        "-x509", 
        "-newkey", "rsa:2048", 
        "-keyout", "certs/server.key", 
        "-out", "certs/server.pem", 
        "-days", args.duration,
        "-nodes", 
        "-subj", f"/CN={args.domain}",
        "-addext", f"subjectAltName=DNS:{args.domain},IP:{args.ip}"
    ])
    print("Certificates successfully created!")
else:
    print("Certificate files already exist.")
