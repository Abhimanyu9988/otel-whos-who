"""Render site/template.html + data/otel-people.json into _site/index.html."""
import datetime
import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    with open(os.path.join(ROOT, "data", "otel-people.json"), encoding="utf-8") as f:
        data = json.load(f)
    data["generated"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    with open(os.path.join(ROOT, "site", "template.html"), encoding="utf-8") as f:
        html = f.read().replace("__DATA__", blob)
    out = os.path.join(ROOT, "_site")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    shutil.copy(os.path.join(ROOT, "data", "otel-people.json"), os.path.join(out, "otel-people.json"))
    print("wrote _site/index.html", len(html), "bytes")


if __name__ == "__main__":
    main()
