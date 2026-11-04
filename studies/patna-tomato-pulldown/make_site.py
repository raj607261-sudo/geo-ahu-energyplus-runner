#!/usr/bin/env python3
"""Copy the dashboard (fragment + data.json) into docs/patna-tomato/ as a full HTML page for GitHub Pages."""
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
dest = HERE.parent.parent / "docs" / "patna-tomato"
dest.mkdir(parents=True, exist_ok=True)
frag = (HERE / "dashboard" / "index.html").read_text()
page = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        + frag.split("</style>", 1)[0] + "</style>\n</head>\n<body>\n" + frag.split("</style>", 1)[1] + "\n</body>\n</html>\n")
(dest / "index.html").write_text(page)
shutil.copy(HERE / "dashboard" / "data.json", dest / "data.json")
print("wrote", dest)
