# -*- coding: utf-8 -*-
import io
import re, os


class Ass2srt:
    def __init__(self, filename):
        self.filename = filename
        self.encoding = "utf-8"
        self.load()

    def output_name(self, tag=None):
        outputfile = self.filename[0:-4]
        if tag:
            outputfile = outputfile+"."+tag
        return outputfile+".srt"

    def load(self, filename=None):
        if filename is None:
            filename = self.filename

        raw = open(filename, "rb").read()

        # Try common encodings for subtitle files
        for enc in ("utf-8-sig", "utf-8", "cp1256", "windows-1256"):
            try:
                text = raw.decode(enc)
                self.encoding = enc
                break
            except Exception:
                text = None

        if text is None:
            text = raw.decode("utf-8", errors="replace")
            self.encoding = "utf-8"

        data = text.splitlines(True)

        self.nodes = []
        for line in data:
            if line.startswith("Dialogue"):
                line = line.split(":", 1)[1]   # safer than lstrip("Dialogue:")
                node = line.split(",")
                node[1] = timefmt(node[1])
                node[2] = timefmt(node[2])
                node[9] = ",".join(node[9:])
                node[9] = re.sub(r'{[^}]*}', "", node[9]).strip()
                node[9] = re.sub(r'\\N', "\n", node[9])
                self.nodes.append(node)

    def to_srt(self, name=None, line=0, tag=None):
        if name is None:
            name = self.output_name(tag=tag)
        with io.open(file=name, mode="w", encoding=self.encoding) as f:
            index = 1
            for node in self.nodes:
                f.writelines(u'{}\n'.format(index))
                f.writelines(u'{} --> {}\n'.format(node[1], node[2]))
                if line == 1:
                    text = node[9].split("\n")[0]
                elif line == 2:
                    tmp = node[9].split("\n")
                    text = tmp[1] if len(tmp) > 1 else node[9]
                else:
                    text = node[9]
                f.writelines(u'{}\n\n'.format(text))
                index += 1

    def __str__(self):
        return u'{}\n{}\n'.format(self.filename, len(self.nodes))


def timefmt(strt):
    strt = strt.replace(".", ",")
    return u'{}0'.format(strt)