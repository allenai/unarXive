"""
Convert latex files to xml format

"""

import os
import subprocess
import glob
import tqdm


LATEX_DIR = 'data/normalized/'
XML_DIR = 'data/latex_xml/'

ERROR_FILE = 'data/latex_xml/err.log'
SKIPPED_FILE = 'data/latex_xml/skipped_files.txt'

if __name__ == '__main__':
    os.makedirs(XML_DIR, exist_ok=True)

    with open(ERROR_FILE, 'w+') as err_f, open(SKIPPED_FILE, 'w+') as skip_f:
        for tex_file in tqdm.tqdm(glob.glob(os.path.join(LATEX_DIR, '*.tex'))):
            _, arxiv_id = os.path.split(os.path.splitext(tex_file)[0])

            tmp_xml_dir = os.path.join(XML_DIR, arxiv_id)
            tmp_xml_path = os.path.join(tmp_xml_dir, '{}.xml'.format(arxiv_id))
            if not os.path.exists(tmp_xml_path):
                # run tralics
                tralics_args = ['tralics',
                                '-silent',
                                '-noxmlerror',
                                '-utf8',
                                '-oe8',
                                '-entnames=false',
                                '-nomathml',
                                '-output_dir={}'.format(tmp_xml_dir),
                                tex_file]

                try:
                    subprocess.run(tralics_args, stderr=err_f, timeout=5)
                except subprocess.TimeoutExpired as e:
                    continue

            # if no output, skip
            if not os.path.exists(tmp_xml_path):
                skip_f.write(f'{arxiv_id}\n')
                continue

    print('done.')