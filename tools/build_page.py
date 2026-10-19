"""Собирает site/index.html: подставляет data/project.json в шаблон."""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
tpl = open(os.path.join(ROOT, 'site', 'template.html'), encoding='utf-8').read()
data = open(os.path.join(ROOT, 'data', 'project.json'), encoding='utf-8').read()
out = os.path.join(ROOT, 'site', 'index.html')
open(out, 'w', encoding='utf-8').write(tpl.replace('__PROJECT_JSON__', data.replace('</', '<\\/')))
print(out, os.path.getsize(out) // 1024, 'КБ')
