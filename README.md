# Квартира на Шагала — проект планировки

Источник: обмерный план (PDF из AutoCAD, planium.tech), наб. Марка Шагала 15к2, кв. 214, 117,2 м².

- `tools/source_walls.json` — стены, извлечённые из векторного PDF (мм; монолит / газоблок).
- `tools/geom.py` — геометрия и системы координат (N — как на чертеже, R — повернутое на 43,75° крыло).
- `tools/design.py` — варианты A и B: демонтаж, новые перегородки, двери, помещения, мебель → `data/project.json`.
- `tools/render_check.py` — быстрый PNG-рендер для проверки.
- `tools/build_page.py` — собирает `site/index.html` (2D-план, 3D, прогулка) из `site/template.html`.

```
pip install shapely opencv-python-headless numpy pillow
python3 tools/design.py && python3 tools/build_page.py
```
