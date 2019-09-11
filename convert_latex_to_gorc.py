"""
Convert latex files to GORC format

"""

import os
import re
import subprocess
import glob
import tqdm
import json
import bs4
from bs4 import BeautifulSoup
from typing import List, Dict


NAME_REGEX = [r'']


def process_authors(author_text: str, minimal=False) -> List[Dict]:
    """
    Process author text
    :return:
    """
    author_entries = []

    author_text = re.sub(r'\sand\s', ',', author_text)
    author_text = re.sub(r'\s', ' ', author_text)
    author_names = [n.strip() for n in author_text.split(',') if n.strip()]

    if len(author_names) > 0:
        for name in author_names:
            name_parts = name.split()
            if name_parts[-1] in {"Jr", "Sr", "III", "IV", "V"}:
                suffix = name_parts[-1]
                name_parts = name_parts[:-1]
            else:
                suffix = ""
            if minimal:
                name_entry = {
                    "first": name_parts[0],
                    "middle": name_parts[1:-1],
                    "last": name_parts[-1],
                    "suffix": suffix
                }
            else:
                name_entry = {
                    "first": name_parts[0],
                    "middle": name_parts[1:-1],
                    "last": name_parts[-1],
                    "suffix": suffix,
                    "affiliation": {},
                    "email": ""
                }
            author_entries.append(name_entry)

    return author_entries


def process_bibentry(bib_text: str) -> Dict:
    """
    Process one bib entry text into title, authors, etc
    :param bib_text:
    :return:
    """
    bib_lines = bib_text.split('\n')
    bib_lines = [re.sub(r'\s+', ' ', line) for line in bib_lines]
    bib_lines = [re.sub(r'\s', ' ', line).strip() for line in bib_lines]

    return ' '.join(bib_lines)


def process_paragraph(soup: BeautifulSoup, para_el: bs4.element.Tag, section_name: str):
    """
    Process one paragraph
    :param soup:
    :param para_el:
    :param section_name:
    :return:
    """
    # replace formula, figures and tables with corresponding keyword string
    strip_tags = ['formula', 'figure', 'table']
    for tag in strip_tags:
        for stag in para_el.find_all(tag):
            stag.replace_with(soup.new_string(f"{tag.upper()}"))

    # replace non citation references with REF keyword
    for rtag in para_el.find_all('ref'):
        if rtag.get('target') and not rtag.get('target').startswith('bid'):
            rtag.replace_with(soup.new_string("REF"))

    # replace all citations with cite keyword
    citations = para_el.find_all('cit')
    for cite in citations:
        target = cite.ref.get('target').upper()
        cite.replace_with(soup.new_string(target))
    text = re.sub(r'\s', ' ', para_el.text)

    # remove floats
    for fl in para_el.find_all('float'):
        fl.decompose()

    # remove notes
    for note in para_el.find_all('note'):
        note.decompose()

    # get all cite spans
    all_cite_spans = []
    for span in re.finditer(r'(BID\d+)', text):
        all_cite_spans.append([
            span.start(),
            span.start() + len(span.group()),
            span.group()
        ])

    return {
        "text": text,
        "mention_spans": all_cite_spans,
        "section": section_name
    }


LATEX_DIR = 'data/normalized/'
XML_DIR = 'data/latex_xml/'
OUTPUT_DIR = 'data/latex_gorc/'

os.makedirs(XML_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

for tex_file in tqdm.tqdm(glob.glob(os.path.join(LATEX_DIR, '*.tex'))):
    _, arxiv_id = os.path.split(os.path.splitext(tex_file)[0])
    out_file = os.path.join(OUTPUT_DIR, f'{arxiv_id}.json')

    tmp_xml_path = os.path.join(XML_DIR, '{}.xml'.format(arxiv_id))
    if not os.path.exists(tmp_xml_path):
        # run tralics
        tralics_args = ['tralics',
                        '-silent',
                        '-noxmlerror',
                        '-utf8',
                        '-oe8',
                        '-entnames=false',
                        '-nomathml',
                        '-output_dir={}'.format(XML_DIR),
                        tex_file]

        with open(os.path.join(OUTPUT_DIR, 'err.log'), 'a+') as err_f:
            try:
                subprocess.run(tralics_args, stderr=err_f, timeout=5)
            except subprocess.TimeoutExpired as e:
                continue

    # if no output, skip
    if not os.path.exists(tmp_xml_path):
        continue

    # get plain text from latexml output
    with open(tmp_xml_path, 'r') as f:
        xml = f.read()
    soup = BeautifulSoup(xml, 'xml')

    # remove what is most likely noise
    for mn in soup.find_all("unexpected"):
        mn.decompose()

    # processing of bibliography entries
    bibkey_map = {}

    if soup.Bibliography:
        for bi in soup.Bibliography.find_all('bibitem'):
            if not bi.get('id'):
                continue
            bibkey_map[bi.get('id').upper()] = process_bibentry(bi.find_parent('p').text)

        soup.Bibliography.decompose()

    # remove floats
    for fl in soup.find_all('float'):
        fl.decompose()

    # process body text
    section_title = ''
    body_text = []

    for div in soup.find_all('div0'):
        for el in div:
            if el.name == 'head':
                section_title = el.text

            # if paragraph treat as paragraph
            elif el.name == 'p':
                body_text.append(
                    process_paragraph(soup, el, section_title)
                )

            # if subdivision, treat each paragraph unit separately
            elif el.name == 'div1':
                section_title = el.head.text
                for p in el.find_all('p'):
                    body_text.append(
                        process_paragraph(soup, p, section_title)
                    )
        div.decompose()

    # try to get head info (title, author, abstract etc)
    try:
        title = soup.title.text
    except AttributeError:
        title = ""

    try:
        authors = process_authors(soup.author.text.strip())
    except AttributeError:
        authors = []

    try:
        year = soup.year.text
    except AttributeError:
        year = ""

    abstract = []

    # get abstract from head paragraphs
    ps = soup.find_all('p')

    if ps:
        text_len = [len(p.text) for p in ps]
        abstract_entry = text_len.index(max(text_len))
        abs_p = ps[abstract_entry]

        if len(abs_p) == 1:
            text = re.sub(r'\s', ' ', abs_p.text)
            abstract = {
                "text": text,
                "mention_spans": [],
                "section": None
            }
        else:
            # replace formula, figures and tables with corresponding keyword string
            strip_tags = ['formula', 'figure', 'table']
            for tag in strip_tags:
                for stag in abs_p.find_all(tag):
                    stag.replace_with(soup.new_string(f"{tag.upper()}"))

            # replace non citation references with REF keyword
            for rtag in abs_p.find_all('ref'):
                if rtag.get('target') and not rtag.get('target').startswith('bid'):
                    rtag.replace_with(soup.new_string("REF"))

            # replace all citations with cite keyword
            citations = abs_p.find_all('cit')
            for cite in citations:
                target = cite.ref.get('target').upper()
                cite.replace_with(soup.new_string(target))
            text = re.sub(r'\s', ' ', abs_p.text)

            # get all cite spans
            all_cite_spans = []
            for span in re.finditer(r'(BID\d+)', text):
                all_cite_spans.append([
                    span.start(),
                    span.start() + len(span.group()),
                    span.group()
                ])
            abstract = {
                "text": text,
                "mention_spans": all_cite_spans,
                "section": None
            }

        del ps[abstract_entry]

        # try to get year first if doesn't exist
        if not year and ps:
            for i, p in enumerate(ps):
                if re.match(r'\d{4}', p.text):
                    year = p.text
                    del ps[i]

        # try to get title if doesn't exist
        if not title and ps:
            title = ps[0].text

        # try to get authors if doesn't exist
        if not authors and len(ps) > 1:
            authors = process_authors(ps[1].text.strip())

    # form final gorc entry
    gorc_entry = {
        "paper_id": arxiv_id,
        "metadata": {
            "title": title,
            "authors": authors,
            "year": year,
        },
        "abstract": [abstract],
        "body_text": body_text,
        "bib_entries": bibkey_map
    }

    with open(out_file, 'w') as outf:
        json.dump(gorc_entry, outf, indent=4)





