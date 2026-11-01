"""Turn Material Symbols ligatures into a name-to-character map.

Qt on the Frame does not apply the font's required ligatures, so the shell
paints the codepoint instead of the icon name.
"""
import sys
from fontTools.ttLib import TTFont


def glyph_map(font):
    cmap = font.getBestCmap()
    glyph_char = {name: chr(cp) for cp, name in cmap.items()}
    glyph_char["underscore"] = glyph_char.get("underscore", "_")
    out = {}
    for lookup in font["GSUB"].table.LookupList.Lookup:
        for subtable in lookup.SubTable:
            table = subtable
            if lookup.LookupType == 7 and hasattr(subtable, "ExtSubTable"):
                table = subtable.ExtSubTable
            ligatures = getattr(table, "ligatures", None)
            if not ligatures:
                continue
            for first, items in ligatures.items():
                for lig in items:
                    chars = []
                    for glyph in (first,) + tuple(lig.Component):
                        char = glyph_char.get(glyph)
                        if char is None:
                            chars = None
                            break
                        chars.append(char)
                    if not chars:
                        continue
                    point = glyph_char.get(lig.LigGlyph)
                    if point:
                        out["".join(chars)] = point
    return out


def render(mapping):
    lines = [".pragma library", "const glyphs = {"]
    for name in sorted(mapping):
        if not name.isascii() or any(c in name for c in "\\\"\n"):
            continue
        lines.append(f'  "{name}": "{mapping[name]}",')
    lines.append("};")
    lines.append('function map(name) { return glyphs[name] || name || ""; }')
    return "\n".join(lines) + "\n"


def main():
    font = TTFont(sys.argv[1])
    mapping = glyph_map(font)
    if "settings" not in mapping:
        raise SystemExit("frametop: the settings icon is missing from the font")
    sys.stdout.write(render(mapping))


if __name__ == "__main__":
    main()
