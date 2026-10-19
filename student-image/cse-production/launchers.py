"""Route image desktop entries through the tested CLI settings."""
from pathlib import Path
changed = 0
for path in Path('/usr/share/applications').glob('*.desktop'):
    lines = path.read_text().splitlines()
    output = []
    touched = False
    for line in lines:
        if line.startswith('Exec='):
            executable, sep, args = line[5:].partition(' ')
            if executable in ('/usr/share/code/code', '/usr/share/code/bin/code', '/usr/bin/code', 'code'):
                line = 'Exec=/usr/local/bin/code' + (sep + args if sep else '')
                touched = True
        output.append(line)
    if touched:
        path.write_text('\n'.join(output) + '\n')
        changed += 1
if not changed:
    raise SystemExit('No known VS Code desktop entries found; refusing release.')
print('Updated VS Code desktop entries:', changed)
