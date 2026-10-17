"""Rebuild the self-hosted Japanese UI font from the licensed upstream font."""
from fontTools import subset
from fontTools.ttLib import TTFont
from pathlib import Path
import argparse
parser=argparse.ArgumentParser(description='Build the local Noto Sans JP UI subset; requires fonttools and brotli.')
parser.add_argument('source',type=Path,help='Original NotoSansJP[wght].ttf')
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
font=TTFont(args.source)
chars=set(range(0x20,0x100))|set(range(0x3000,0x3100))|set(range(0xff00,0xfff0))
for a in range(0x88,0x99):
 for b in range(0x40,0xfd):
  pair=bytes([a,b])
  if pair < bytes.fromhex('889f') or pair > bytes.fromhex('9872'):continue
  try:chars.add(ord(pair.decode('shift_jis')))
  except (UnicodeDecodeError,TypeError):pass
for file in list((root / 'frontend').rglob('*.html'))+list((root / 'frontend/js').glob('*.js')):
 chars.update(map(ord,file.read_text()))
opts=subset.Options();opts.flavor='woff2';opts.layout_features=['*']
sub=subset.Subsetter(options=opts);sub.populate(unicodes=chars);sub.subset(font)
from fontTools.varLib.instancer import instantiateVariableFont
instantiateVariableFont(font,{'wght':(400,400,700)},inplace=True)
font.flavor='woff2';font.save(root / 'frontend/fonts/noto-sans-jp-ui.woff2')
print('font size:',(root / 'frontend/fonts/noto-sans-jp-ui.woff2').stat().st_size)
