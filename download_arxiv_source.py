import os
import tqdm
import boto3
from bs4 import BeautifulSoup


ARXIV_BUCKET = 'arxiv'
OUTPUT_DIR = 'data/bulk_arxiv/'

os.makedirs(OUTPUT_DIR, exist_ok=True)
aws_attribs = {'RequestPayer': 'requester'}

s3 = boto3.resource('s3')
bucket = s3.Bucket(ARXIV_BUCKET)

manifest_file = os.path.join('src', 'arXiv_src_manifest.xml')
local_manifest_file = os.path.join('data', 'arXiv_src_manifest.xml')

if not os.path.exists(local_manifest_file):
    bucket.download_file(manifest_file, local_manifest_file, aws_attribs)

# read manifest
with open(local_manifest_file, 'r') as f:
    xml = f.read()
soup = BeautifulSoup(xml, 'xml')

# iterate and download
all_filenames = [el.text for el in soup.find_all('filename')]

for prefix in tqdm.tqdm(soup.find_all('filename')):
    print(prefix.text)
    _, fname = prefix.text.split('/')
    s3_arxiv_tar = prefix.text
    local_arxiv_tar = os.path.join(OUTPUT_DIR, fname)
    if os.path.exists(local_arxiv_tar):
        continue
    bucket.download_file(s3_arxiv_tar, local_arxiv_tar, aws_attribs)