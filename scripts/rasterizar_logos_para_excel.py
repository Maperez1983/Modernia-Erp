"""Genera los PNG de los logos de banco para el Excel.

Excel no admite SVG. Se rasterizan una vez, se guardan en assets/logos/excel/ y el
servidor solo tiene que incrustarlos: así no hace falta un rasterizador en producción.
"""
import subprocess, sys, base64, pathlib, json
RAIZ = pathlib.Path("/Volumes/Mac Satecchi/Mac/Library/Mobile Documents/com~apple~CloudDocs/CRM MODERNIA")
sys.path.insert(0, str(RAIZ))
from web import pdf_utils
from PIL import Image

DESTINO = RAIZ / "assets" / "logos" / "excel"
DESTINO.mkdir(parents=True, exist_ok=True)
TMP = pathlib.Path("/private/tmp/claude-501/-Volumes-Mac-Satecchi-Mac-Library-Mobile-Documents-com-apple-CloudDocs-CRM-MODERNIA/5ccdf14a-d6c9-43fd-9f1f-856b57b35091/scratchpad/raster")
TMP.mkdir(exist_ok=True)
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Logos con la tinta en blanco: sobre fondo blanco desaparecen y hay que ponerlos
# sobre el color de su marca. Se listan a mano porque medir el contraste confunde
# "logo blanco" con "logo pequeño": bajando el umbral lo justo para cazar a Caja
# Rural del Sur, CaixaBank y UCI salían peor de lo que estaban.
TINTA_BLANCA = {"caja-rural-del-sur"}

# 320x100 a escala 2 => 640x200 reales; luego se reduce a 160x50 para el Excel.
ANCHO, ALTO = 320, 100
hechos = []
for marca in pdf_utils.HIPOTECA_BANK_BRANDS:
    ruta = RAIZ / "assets" / marca["logo"].replace("/assets/", "", 1)
    if not ruta.exists():
        print("  falta", ruta.name); continue
    slug = ruta.stem
    datos = base64.b64encode(ruta.read_bytes()).decode()
    tipo = "image/svg+xml" if ruta.suffix == ".svg" else "image/png"
    sobre_color = marca.get("logo_on_dark") or ruta.stem in TINTA_BLANCA
    fondo = marca.get("color") if sobre_color else "#ffffff"
    html = TMP / f"{slug}.html"
    html.write_text(
        f'<meta charset="utf-8"><style>html,body{{margin:0;padding:0;width:{ANCHO}px;height:{ALTO}px;'
        f'display:flex;align-items:center;justify-content:center;background:{fondo}}}'
        f'img{{max-width:92%;max-height:82%;object-fit:contain}}</style>'
        f'<img src="data:{tipo};base64,{datos}">', encoding="utf-8")
    png = TMP / f"{slug}.png"
    subprocess.run([CHROME, "--headless", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
                    "--force-device-scale-factor=2", f"--window-size={ANCHO},{ALTO}",
                    f"--screenshot={png}", f"file://{html}"],
                   capture_output=True, timeout=90)
    if not png.exists():
        print("  no se pudo rasterizar", slug); continue
    im = Image.open(png).convert("RGB")
    im = im.resize((160, 50), Image.LANCZOS)
    salida = DESTINO / f"{slug}.png"
    im.save(salida, optimize=True)
    hechos.append((marca["short"], salida.name, salida.stat().st_size))

print(f"{len(hechos)} logos generados en assets/logos/excel/")
for s, n, b in hechos: print(f"   {s:<14} {n:<28} {b:>6} bytes")
