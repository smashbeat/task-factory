"""Render one page of a package document (a PDF, or a PDF attached to an .eml) to PNG, to look at what the
agent looked at.
usage: python3 scripts/trials/render_page.py PKG_DIR NAME_SUBSTR OUT.png [dpi] [page]
NAME_SUBSTR matches the document's file name, or 'EMLNAME:ATTACHMENT' for an attachment."""
import email
import email.policy
import os
import sys

import fitz

pkg, needle, out = sys.argv[1], sys.argv[2], sys.argv[3]
dpi = int(sys.argv[4]) if len(sys.argv) > 4 else 80
pno = int(sys.argv[5]) if len(sys.argv) > 5 else 0
data = None
for name in sorted(os.listdir(pkg)):
    path = os.path.join(pkg, name)
    if name.lower().endswith('.eml'):
        with open(path, 'rb') as f:
            msg = email.message_from_binary_file(f, policy=email.policy.default)
        for part in msg.iter_attachments():
            key = f'{name}:{part.get_filename() or ""}'
            if needle in key:
                data = part.get_payload(decode=True)
                print('attachment', key)
                break
    elif needle in name and name.lower().endswith('.pdf'):
        with open(path, 'rb') as f:
            data = f.read()
        print('file', name)
    if data:
        break
if not data:
    sys.exit('no match')
doc = fitz.open(stream=data, filetype='pdf')
page = doc[pno]
print('pages', len(doc), 'rect', page.rect, 'rotation', page.rotation)
pix = page.get_pixmap(dpi=dpi)
pix.save(out)
print('saved', out, pix.width, pix.height)
