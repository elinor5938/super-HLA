import subprocess
import pandas as pd
from io import StringIO
command = "/Users/aviadchmelnik/Documents/Elinor/thesis/netMHCpan-4.2/netMHCpan -p /Users/aviadchmelnik/Code/Thesis-project/input/peptides_for_pred_9.txt -l 9 -a HLA-A01:01,HLA-A02:01,HLA-A03:01,HLA-A24:02,HLA-A29:02,HLA-B07:02,HLA-B08:01,HLA-B27:05,HLA-A30:01,HLA-B40:01,HLA-B58:01,HLA-B15:01"
out = subprocess.run(command, shell=True, text=True, capture_output=True)
stdout_string = out.stdout

# See output directly
lines = [l for l in stdout_string.splitlines() if not l.startswith('#')]
for i, l in enumerate(lines[:10]):
    print(f"{i}: {l}")

