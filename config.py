import os
from pathlib import Path

# Provide a lightweight way to load .env without relying on python-dotenv
def load_env(env_path):
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    os.environ[key.strip()] = val.strip()

# Base directory is the current directory for super-HLA
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_env(os.path.join(BASE_DIR, ".env"))

# Configurable paths with sensible defaults
DEFAULT_MHC_PATH = "/path/to/netMHCpan-4.2/"
MHC_DIR_PATH = os.environ.get("MHC_DIR_PATH", DEFAULT_MHC_PATH)
NETMHCPAN_EXECUTABLE = os.path.join(MHC_DIR_PATH, "netMHCpan")
# Sometimes the executable is called ./netMHCpan or just netMHCpan if it's in the PATH
# We will verify if we need to call it securely. Actually, we'll just use the absolute path.

INPUT_DIR_PATH = os.environ.get("INPUT_DIR_PATH", os.path.join(BASE_DIR, "input"))
OUTPUT_DIR_PATH = os.environ.get("OUTPUT_DIR_PATH", os.path.join(BASE_DIR, "output"))

# Make sure directories exist
os.makedirs(INPUT_DIR_PATH, exist_ok=True)
os.makedirs(OUTPUT_DIR_PATH, exist_ok=True)

# NetMHCpan Configurations
DEFAULT_HLA_STR = 'HLA-A01:01,HLA-A02:01,HLA-A03:01,HLA-A24:02,HLA-A29:02,HLA-B07:02,HLA-B08:01,HLA-B27:05,HLA-A30:01,HLA-B40:01,HLA-B58:01,HLA-B15:01'
HLA_STR = os.environ.get("HLA_STR", DEFAULT_HLA_STR)

DEFAULT_SUPERTYPES_LIST = ['HLA-A*01:01', 'HLA-A*02:01', 'HLA-A*03:01', 'HLA-A*24:02', 'HLA-A*29:02', 'HLA-B*07:02', 'HLA-B*08:01', 'HLA-B*27:05', 'HLA-A*30:01', 'HLA-B*40:01', 'HLA-B*58:01', 'HLA-B*15:01']
SUPERTYPES_LIST_ENV = os.environ.get("SUPERTYPES_LIST")
if SUPERTYPES_LIST_ENV:
    SUPERTYPES_LIST = [hla.strip() for hla in SUPERTYPES_LIST_ENV.split(",")]
else:
    SUPERTYPES_LIST = DEFAULT_SUPERTYPES_LIST
