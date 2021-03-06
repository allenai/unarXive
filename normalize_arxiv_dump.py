""" Normalize a arXiv dump

    - copy PDF files as is
    - unzip gzipped single files
        - copy if it's a LaTeX file
    - extract gzipped tar archives
        - try to flatten contents to a single LaTeX file
        - ignores non LaTeX contents (HTML, PS, TeX, ...)
"""

import chardet
import gzip
import magic
import tqdm
import os
import re
import glob
import shutil
import subprocess
import sys
import tarfile
import tempfile

MAIN_TEX_PATT = re.compile(r'(\\begin\s*\{\s*document\s*\})', re.I)
# ^ with capturing parentheses so that the pattern can be used for splitting
PDF_EXT_PATT = re.compile(r'^\.pdf$', re.I)
GZ_EXT_PATT = re.compile(r'^\.gz$', re.I)
TEX_EXT_PATT = re.compile(r'^\.tex$', re.I)
NON_TEXT_PATT = re.compile(r'^\.(pdf|eps|jpg|png|gif)$', re.I)
BBL_SIGN = '\\bibitem'
# natbib fix
PRE_FIX_NATBIB = True
NATBIB_PATT = re.compile((r'\\cite(t|p|alt|alp|author|year|yearpar)\s*?\*?\s*?'
                           '(\[[^\]]*?\]\s*?)*?\s*?\*?\s*?\{([^\}]+?)\}'),
                         re.I)
# bibitem option fix
PRE_FIX_BIBOPT = True
BIBOPT_PATT = re.compile(r'\\bibitem\s*?\[[^]]*?\]', re.I|re.M)

# ↑ above two solve most tralics problems; except for mnras style bibitems
# (https://ctan.org/pkg/mnras)

# agressive math pre-removal
PRE_FILTER_MATH = False
FILTER_PATTS = []
for env in ['equation', 'displaymath', 'array', 'eqnarray', 'align', 'gather',
            'multline', 'flalign', 'alignat']:
    s = r'\\begin\{{{0}[*]?\}}.+?\\end\{{{0}\}}'.format(env)
    patt = re.compile(s, re.I | re.M | re.S)
    FILTER_PATTS.append(patt)
FILTER_PATTS.append(re.compile(r'\$\$.+?\$\$', re.S))
FILTER_PATTS.append(re.compile(r'\$.+?\$', re.S))
FILTER_PATTS.append(re.compile(r'\\\(.+?\\\)', re.S))
FILTER_PATTS.append(re.compile(r'\\\[.+?\\\]', re.S))


def read_file(path):
    try:
        with open(path) as f:
            cntnt = f.read()
    except UnicodeDecodeError:
        blob = open(path, 'rb').read()
        m = magic.Magic(mime_encoding=True)
        encoding = m.from_buffer(blob)
        try:
            cntnt = blob.decode(encoding)
        except (UnicodeDecodeError, LookupError) as e:
            encoding = chardet.detect(blob)['encoding']
            if encoding:
                try:
                    cntnt = blob.decode(encoding, errors='replace')
                except:
                    return ''
            else:
                return ''
    return cntnt


def read_gzipped_file(path):
    blob = gzip.open(path, 'rb').read()
    m = magic.Magic(mime_encoding=True)
    encoding = m.from_buffer(blob)
    try:
        cntnt = blob.decode(encoding)
    except (UnicodeDecodeError, LookupError) as e:
        encoding = chardet.detect(blob)['encoding']
        if not encoding:
            return False
        cntnt = blob.decode(encoding, errors='replace')
    return cntnt


def remove_math(latex_str):
    parts = re.split(MAIN_TEX_PATT, latex_str, maxsplit=1)
    for patt in FILTER_PATTS:
         parts[2] = re.sub(patt, '', parts[2])
    return ''.join(parts)


def normalize(IN_DIR, OUT_DIR, write_logs=True):
    def log(msg):
        if write_logs:
            with open(os.path.join(OUT_DIR, 'log.txt'), 'a') as f:
                f.write('{}\n'.format(msg))

    if not os.path.isdir(IN_DIR):
        print('dump directory does not exist')
        return False

    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)

    for fn in tqdm.tqdm(os.listdir(IN_DIR)):

        path = os.path.join(IN_DIR, fn)

        # identify main tex file
        main_tex_path = None
        ignored_names = []

        # check .tex files first
        for tfn in os.listdir(path):

            if not TEX_EXT_PATT.match(os.path.splitext(tfn)[1]):
                ignored_names.append(tfn)
                continue

            try:
                cntnt = read_file(os.path.join(path, tfn))
            except:
                continue

            if re.search(MAIN_TEX_PATT, cntnt) is not None:
                main_tex_path = tfn

        # try other files
        if main_tex_path is None:
            for tfn in ignored_names:
                if NON_TEXT_PATT.match(os.path.splitext(tfn)[1]):
                    continue
                try:
                    cntnt = read_file(os.path.join(path, tfn))
                    if re.search(MAIN_TEX_PATT, cntnt) is not None:
                        main_tex_path = tfn
                except:
                    continue

        # give up
        if main_tex_path is None:
            log(('couldn\'t find main tex file in dump archive {}'
                 '').format(fn))
            continue

        # flatten to single tex file and save
        with tempfile.TemporaryDirectory() as tmp_dir_path:
            temp_tex_fn = os.path.join(tmp_dir_path, f'{fn}.tex')

            # "identify" bbl file
            # https://arxiv.org/help/submit_tex#bibtex
            main_tex_fn = os.path.join(path, main_tex_path)
            bbl_files = glob.glob(os.path.join(path, '*.bbl'))

            if bbl_files:
                latexpand_args = ['latexpand',
                                  '--expand-bbl',
                                  bbl_files[0],
                                  main_tex_fn,
                                  '--output',
                                  temp_tex_fn]
            else:
                latexpand_args = ['latexpand',
                                  main_tex_fn,
                                  '--output',
                                  temp_tex_fn]

            with open(os.path.join(OUT_DIR, 'log_latexpand.txt'), 'a+') as err:
                subprocess.run(latexpand_args, stderr=err)

            # re-read and write to ensure utf-8 b/c latexpand doesn't
            # behave
            new_tex_fn = os.path.join(OUT_DIR, f'{fn}.tex')
            cntnt = read_file(temp_tex_fn)
            if PRE_FIX_NATBIB:
                cntnt = NATBIB_PATT.sub(r'\\cite{\3}', cntnt)
            if PRE_FIX_BIBOPT:
                cntnt = BIBOPT_PATT.sub(r'\\bibitem', cntnt)
            if PRE_FILTER_MATH:
                cntnt = remove_math(cntnt)
            with open(new_tex_fn, mode='w', encoding='utf-8') as f:
                f.write(cntnt)

    return True


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(('usage: python3 nomalize_arxiv_dump.py </path/to/dump/dir> </pa'
               'th/to/out/dir>'))
        sys.exit()
    IN_DIR = sys.argv[1]
    OUT_DIR = sys.argv[2]

    ret = normalize(IN_DIR, OUT_DIR)

    print('done.')
