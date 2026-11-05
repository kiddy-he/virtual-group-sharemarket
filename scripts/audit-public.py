#!/usr/bin/env python3
"""Fail closed on common sensitive files/values in the public source set.

This is a heuristic, not proof of absence. Findings never echo matched values.
"""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {'README.md','README.en.md','LICENSE','THIRD_PARTY_NOTICES.md','CONTRIBUTING.md','SECURITY.md','CHANGELOG.md','pyproject.toml','package.json','requirements.txt','requirements-lock.txt','.gitignore','MANIFEST.in'}
PUBLIC_DIRS = {'src','sdk','tests','config','examples','docs','scripts','deployment','.github'}
PATTERNS = {
    'API credential': re.compile(r'\b(?:sk-[A-Za-z0-9_-]{24,}|AIza[A-Za-z0-9_-]{30,}|gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,})'),
    'private key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'credential URL': re.compile(r'https?://[^\s/\"\']+:[^\s/@\"\']+@'),
    'private IPv4': re.compile(r'\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b'),
    'private home path': re.compile(r'(?:/[r]oot/|/home/(?!example\b)[A-Za-z0-9_.-]+/)'),
    'credential assignment': re.compile(r'(?i)[\"\']?(?:api[_-]?key|access[_-]?token|auth[_-]?token|password)[\"\']?\s*[:=]\s*[\"\'](?!placeholder|example|your-|SHAREMARKET_|EXAMPLE_|\$|[\"\'])[A-Za-z0-9_./+\-=]{16,}[\"\']'),
}
FORBIDDEN_PARTS = {'.env','.venv','node_modules','state','data','backups','artifacts','output','__pycache__'}
ALLOWED_EXT = {'.py','.mjs','.js','.json','.md','.toml','.txt','.yml','.yaml','.service'}

def candidates():
    if (ROOT/'.git').exists():
        result=subprocess.run(['git','ls-files','-z'],cwd=ROOT,check=True,capture_output=True)
        return [Path(x.decode()) for x in result.stdout.split(b'\0') if x]
    return sorted(p.relative_to(ROOT) for p in ROOT.rglob('*') if p.is_file() and
                  (p.relative_to(ROOT).parts[0] in PUBLIC_DIRS or p.name in ROOT_FILES) and
                  not any(x in {'__pycache__','.venv'} or x.endswith('.egg-info') for x in p.parts))

def main():
    issues=[];files=candidates()
    for rel in files:
        path=ROOT/rel
        if path.is_symlink():issues.append((rel,'symlink'));continue
        if any(p in FORBIDDEN_PARTS or p.startswith('.env.') for p in rel.parts):issues.append((rel,'private path'))
        if rel.suffix not in ALLOWED_EXT and rel.name not in ROOT_FILES:issues.append((rel,'unapproved file type'));continue
        try: text=path.read_text(encoding='utf8')
        except (UnicodeError,OSError):issues.append((rel,'non-text or unreadable file'));continue
        for label,pattern in PATTERNS.items():
            if pattern.search(text):issues.append((rel,label))
        for email in re.findall(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',text):
            if not email.endswith('@users.noreply.github.com'):issues.append((rel,'personal email'))
        for ident in re.findall(r'[\"\']([1-9]\d{7,11})[\"\']',text):
            if not ident.startswith('700000'):issues.append((rel,'non-example numeric identifier'))
    for rel,label in issues:print(f'FAIL {rel}: {label}')
    print(f'Public source audit: {len(files)} files, {len(issues)} findings')
    return bool(issues)

if __name__=='__main__':sys.exit(main())
