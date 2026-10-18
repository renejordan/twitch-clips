#!/usr/bin/env python3
"""Reuse the existing Twitch pipeline, isolated for the 14/day publishing route.

Keeps existing .github/workflows/tiktok.yml and Metricool queue unchanged.
Fails closed if the legacy workflow's inline Python layout changes.
"""
import re
import subprocess
import sys
import textwrap
from pathlib import Path

WORKFLOW = Path('.github/workflows/tiktok.yml')
SCRIPT = Path('pipeline_tiktok14.py')


def replace_once(source, old, new):
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f'Expected exactly one existing fragment ({old[:65]!r}), found {count}; refusing to guess')
    return source.replace(old, new)


def extract_pipeline(yaml_text):
    chunks = []
    lines = yaml_text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() not in ("cat > pipeline.py <<'PY'", "cat >> pipeline.py <<'PY'"):
            continue
        chunk = []
        for part in lines[index + 1:]:
            if part.strip() == 'PY':
                break
            chunk.append(part)
        else:
            raise RuntimeError('Unclosed pipeline.py heredoc')
        chunks.append(textwrap.dedent('\n'.join(chunk)).rstrip() + '\n')
    if len(chunks) != 2:
        raise RuntimeError(f'Expected 2 original pipeline sections, found {len(chunks)}')
    return ''.join(chunks)


def generate():
    code = extract_pipeline(WORKFLOW.read_text(encoding='utf-8'))
    alterations = [
        ("STATE = Path('state/auto20.json')", "STATE = Path('state/auto14_queue.json')"),
        ("if len(monthly) >= 60:", "if len(monthly) >= 15 * calendar.monthrange(now.year, now.month)[1]:"),
        ("'GitHub-Pufferlimit von 60 Produktionen in diesem Monat erreicht'", "'TikTok14: Produktionslimit fuer diesen Monat erreicht'"),
        ("'Heute bereits zwei Clip-Kandidaten erstellt'", "'TikTok14: heute bereits 15 Clip-Kandidaten erstellt'"),
        ("for rec in monthly) >= 2:", "for rec in monthly) >= 15:"),
        ("if event == 'schedule' and not 9 <= now.hour <= 22:", "if event == 'schedule' and not 0 <= now.hour <= 23:"),
        ("tag = f'tiktok-{now:%Y-%m}'", "tag = f'tiktok14-{now:%Y-%m}'"),
        ("'status': 'awaiting_metricool',", "'status': 'ready_tiktok14', 'delivery_route': 'github14',"),
        ("'created': [example_record, example_record]", "'created': [example_record] * 15"),
        ("        clip_url = info.get('webpage_url') or link",
         "        # Verify the broadcaster, not the viewer who created the clip.\n"
         "        if (str(info.get('channel', '')).casefold() != channel.casefold() or\n"
         "                str(info.get('creator', '')).casefold() != channel.casefold()):\n"
         "            return None\n"
         "        clip_url = info.get('webpage_url') or link"),
    ]
    for old, new in alterations:
        code = replace_once(code, old, new)
    # This queue must also exclude anything ever prepared by the legacy pipeline.
    marker = "    return used, used_urls\n"
    replacement = """
    legacy_file = Path('state/auto20.json')
    if legacy_file.exists():
        legacy = json.loads(legacy_file.read_text(encoding='utf-8'))
        used.update(str(value) for value in legacy.get('processed_ids', []))
        for rec in legacy.get('created', []):
            used.update(str(rec.get(key, '')) for key in ('clip_id', 'clip_slug'))
            source = rec.get('source_url', '')
            used_urls.add(source)
            if twitch_slug(source):
                used.add(twitch_slug(source))
    return used, used_urls
"""
    code = replace_once(code, marker, replacement)
    # Changed limits: keep the original code's production tests aligned.
    compile(code, str(SCRIPT), 'exec')
    SCRIPT.write_text(code, encoding='utf-8')
    print('Generated isolated 15/day producer; original media code remains unchanged')


def main():
    generate()
    if '--test' in sys.argv:
        subprocess.run([sys.executable, str(SCRIPT), '--self-test'], check=True)
    else:
        subprocess.run([sys.executable, str(SCRIPT)], check=True)


if __name__ == '__main__':
    main()
