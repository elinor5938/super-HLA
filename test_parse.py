import subprocess
import os
from config import NETMHCPAN_EXECUTABLE, INPUT_DIR_PATH, HLA_STR

# Construct command using environment-aware variables from config.py
peptides_file = os.path.join(INPUT_DIR_PATH, "peptides_for_pred_9.txt")
command = f"{NETMHCPAN_EXECUTABLE} -p {peptides_file} -l 9 -a {HLA_STR}"

print(f"Executing command: {command}")

out = subprocess.run(command, shell=True, text=True, capture_output=True)
stdout_string = out.stdout

# See output directly
lines = [l for l in stdout_string.splitlines() if not l.startswith('#')]
for i, l in enumerate(lines[:10]):
    print(f"{i}: {l}")


