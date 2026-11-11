"""What the text layer says, page by page, for every PDF in a package folder (loose or attached to an .eml):
the layer's word count, the page's image count, and the layer lines that match a regex. A scanned page with
a planted wrong layer shows its lies here; a page with no layer shows zero words.
usage: python3 scripts/trials/layer_dump.py PKG_DIR REGEX"""
import email
import email.policy
import os
import re
import sys

import fitz

pkg, rx = sys.argv[1], re.compile(sys.argv[2], re.I)


def dump(label, data):
    doc = fitz.open(stream=data, filetype='pdf')
    for i, page in enumerate(doc):
        words = page.get_text('words')
        print(f'== {label} p{i} layer_words={len(words)} images={len(page.get_images())}')
        for line in page.get_text('text').splitlines():
            if rx.search(line):
                print('   ', line.strip())


for name in sorted(os.listdir(pkg)):
    path = os.path.join(pkg, name)
    if name.lower().endswith('.pdf'):
        with open(path, 'rb') as f:
            dump(name, f.read())
    elif name.lower().endswith('.eml'):
        with open(path, 'rb') as f:
            msg = email.message_from_binary_file(f, policy=email.policy.default)
        body = (msg.get_body(preferencelist=('plain',)) or msg).get_content() if msg.get_body() else ''
        print(f'== {name} subject={msg["subject"]!r} date={msg["date"]} body={str(body)[:120]!r}')
        for part in msg.iter_attachments():
            fn = part.get_filename() or 'attachment'
            if fn.lower().endswith('.pdf'):
                dump(f'{name}:{fn}', part.get_payload(decode=True))
