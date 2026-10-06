import nbformat
from nbclient import NotebookClient
import os

notebook_path = '/home/nguyen-dai-tung/supplyforge-ai/notebooks/EDA_Diagnosis_v2.ipynb'

print("Loading notebook...")
with open(notebook_path, 'r', encoding='utf-8') as f:
    nb = nbformat.read(f, as_version=4)

print("Executing notebook on FULL Silver Parquet dataset...")
client = NotebookClient(nb, timeout=600, kernel_name='python3')
client.execute()

print("Saving executed notebook...")
with open(notebook_path, 'w', encoding='utf-8') as f:
    nbformat.write(nb, f)

print("FULL EDA Notebook execution complete and saved!")
