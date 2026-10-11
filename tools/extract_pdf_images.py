#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 PDF 中批量提取图片 / 裁剪图表 / 整页渲染。

==========================================================================
 快速上手
==========================================================================
    python extract_pdf_images.py 论文.pdf              # 抠内嵌图，多半不是你要的
    python extract_pdf_images.py 论文.pdf --figures    # ← 要论文里的插图就用这个

 想要 Fig.1 / Table 2？直接 --figures。
 论文插图是「背景图层 + 一堆小图 + 矢量箭头 + 文字标注」拼起来的，PDF 里
 根本没有单一图片对象，默认模式只会抠出一堆碎片，只有按区域重画才拿得到整张。

==========================================================================
 三种模式（--figures 与 --render 互斥；都不加则走默认模式）
==========================================================================
 默认：提取内嵌位图
     取出 PDF 里真实的图片对象，按页命名 p003_01.png，同一张图被多页复用
     只导一次。适合抠照片、扫描页。
     ⚠ 论文插图基本是多图层拼的，这个模式只会给你碎片。

 --figures [DPI]   按标题裁剪图表   ← 推荐
     在正文里找 "Fig. N" / "Table N" 标题，把旁边那一整块裁出来渲染成
     fig001.png / tbl001.png，默认 200 dpi。
       · 图的定位：从图题往上扫，遇到明显留白就停（图内元素挨得紧）
       · 表的定位：认通栏横线（三线表只有首尾两条线，中间隔几百 pt，
                   不能沿用图形那套间隙算法）

 --render DPI      整页渲染
     每页画成 PNG，命名 p001.png，版面关系完整保留。配合 --pages 圈定范围。

==========================================================================
 参数
==========================================================================
 位置参数
   inputs              一个或多个 .pdf 文件，或装着 PDF 的目录

 输出
   -o, --output DIR    输出根目录（默认 ./images）
                       <目录>/<文件名>_images/ 下每个文档一个文件夹；
                       加 --flatten 则不分子文件夹，全部平铺到 <目录>
   --csv FILE          导出清单：来源文件 / 序号 / 位置尺寸 / 大小 / 输出文件名

 选页与筛选
   --pages SPEC        只处理指定页：1-5,8,12-（三种模式通用）
   --min-bytes N       小于 N 字节的图跳过，滤占位图
   --min-dim PX        宽或高小于 PX 像素的跳过，滤 logo/图标（仅默认模式）
   --no-dedup          关闭按内容 MD5 去重
   --keep-cmyk         保留 CMYK 原编码不转 RGB（仅默认模式）

 其它
   -r, --recursive     递归扫描输入目录
   --dry-run           只打印会写什么，不落盘
   -v, --verbose       打印每张图的明细

==========================================================================
 常用组合
==========================================================================
    --figures 300                   只要插图，最高清
    --figures 300 --pages 2,4       只要第 2、4 页的图
    --render 150                    把整本 PDF 每页存成图
    --figures --dry-run             先看看会导出什么，不落盘
    ./papers --recursive -o out --figures    批量处理一个目录

==========================================================================
 依赖
==========================================================================
    pip install pymupdf      必须，PDF 读写
    pip install pillow       可选，仅用于合成透明通道(SMask)、CMYK→RGB

==========================================================================
 输出命名
==========================================================================
    p003_01.png    默认模式：第 3 页的第 2 张内嵌图
    fig001.png     --figures：Fig. 1
    tbl002.png     --figures：Table 2
    p001.png       --render：第 1 页整页
"""

from __future__ import annotations

import argparse
import hashlib
import math
import re
import sys
from io import BytesIO
from pathlib import Path

try:
    import pymupdf
except ImportError:  # 老版本包名
    try:
        import fitz as pymupdf  # type: ignore
    except ImportError:
        pymupdf = None

PDF_SUFFIXES = {".pdf"}

# "Fig. 1" / "Figure 1" / "Table 1" / "Tab. 1" 开头的段落视为图表标题
CAPTION_RE = re.compile(r"^\s*(Fig(?:ure)?\.?|Tab(?:le)?\.?)\s*(\d+)\b", re.IGNORECASE)

# 从标题往图内吸收相邻图形时允许的垂直间隙（pt）
CAPTION_GAP = 12.0        # 连续图形之间
CAPTION_FIRST_GAP = 30.0  # 标题与图体之间（图表底部常留白）


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #

def parse_pages(spec: str | None) -> set[int] | None:
    """把 "1-5,8,12-" 解析成 1 基页码集合，None 表示全部。"""
    if not spec:
        return None
    pages: set[int] = set()
    for chunk in spec.replace("，", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            lo, _, hi = chunk.partition("-")
            start = int(lo) if lo.strip() else 1
            end = int(hi) if hi.strip() else 10 ** 6
            pages.update(range(start, end + 1))
        else:
            pages.add(int(chunk))
    return pages or None


def unique_path(folder: Path, stem: str, ext: str, used: set[str]) -> Path:
    """在目标目录里生成不冲突的文件名。"""
    candidate = f"{stem}.{ext}"
    index = 2
    while candidate.lower() in used or (folder / candidate).exists():
        candidate = f"{stem}_{index}.{ext}"
        index += 1
    used.add(candidate.lower())
    return folder / candidate


def normalize_image(data: bytes, ext: str, force_rgb: bool):
    """用 Pillow 做一次无损整理，返回 (bytes, ext)。

    * CMYK JPEG 直接打开会偏色/反相，转成 RGB 更通用
    * JPEG2000 等 Pillow 解不开的格式原样返回
    """
    try:
        from PIL import Image
    except ImportError:
        return data, ext
    if not force_rgb:
        return data, ext
    try:
        with Image.open(BytesIO(data)) as im:
            if im.mode in ("CMYK", "YCbCr", "LAB"):
                im = im.convert("RGB")
                buf = BytesIO()
                im.save(buf, format="PNG")
                return buf.getvalue(), "png"
    except Exception:
        pass
    return data, ext


def compose_alpha(base: bytes, mask: bytes):
    """把 SMask（透明蒙版）合成为 RGBA 的 PNG，失败返回 None。"""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(BytesIO(base)) as img, Image.open(BytesIO(mask)) as msk:
            rgb = img.convert("RGB")
            alpha = msk.convert("L")
            if alpha.size != rgb.size:
                alpha = alpha.resize(rgb.size)
            rgb.putalpha(alpha)
            buf = BytesIO()
            rgb.save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# 图表定位（--figures 模式）
# --------------------------------------------------------------------------- #

def find_captions(page) -> list[tuple[str, int, object]]:
    """找出页面上所有 "Fig. N" / "Table N" 标题，返回 [(类型, 编号, 标题块矩形)]。"""
    found: list[tuple[str, int, object]] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        lines = block.get("lines") or []
        if not lines:
            continue
        head = "".join(span["text"] for span in lines[0]["spans"]).strip()
        match = CAPTION_RE.match(head)
        if not match:
            continue
        kind = "fig" if match.group(1).lower().startswith("fig") else "table"
        found.append((kind, int(match.group(2)), pymupdf.Rect(block["bbox"])))
    return found


def visual_rects(page) -> list:
    """页面上所有图片 / 矢量图形的位置（也就是图表的"可视像素"部分）。"""
    rects = []
    page_area = page.rect.width * page.rect.height
    for info in page.get_images(full=True):
        rects.extend(page.get_image_rects(info[0]))
    for item in page.get_drawings():
        rect = item.get("rect")
        # 注意：三线表的横线高度、竖线宽度是 0，不能按 <=0 丢掉，否则表格全成透明的
        if rect is None or (rect.width <= 0 and rect.height <= 0):
            continue
        # 整页背景框之类会把整页吞进来，直接排除
        if rect.width * rect.height > page_area * 0.85:
            continue
        rects.append(rect)
    return rects


def expand_band(rects: list, edge: float, upward: bool, max_height: float):
    """从 edge 出发朝一个方向吸收相邻图形，返回 (新边界, x0, x1, 吸收个数)。

    用"空白间隙"切分：只要下一个图形与当前边界之间没有明显留白，
    就认为它属于同一张图；一旦出现大间隙就停下，避免把正文段落也吞进来。
    """
    band = edge
    x0, x1 = math.inf, -math.inf
    count = 0
    ordered = sorted(rects, key=(lambda r: -r.y1) if upward else (lambda r: r.y0))

    for rect in ordered:
        near = (band - rect.y1) if upward else (rect.y0 - band)
        if near < -1:                 # 已经在带内或更靠里，跳过
            continue
        limit = CAPTION_FIRST_GAP if count == 0 else CAPTION_GAP
        if near > limit:              # 出现明显留白 —— 图到此为止
            break
        new_band = rect.y0 if upward else rect.y1
        if abs(new_band - edge) > max_height:
            break
        band = new_band
        x0, x1 = min(x0, rect.x0), max(x1, rect.x1)
        count += 1

    return band, x0, x1, count


def table_band(page, cap, rects: list):
    """定位表格区域：从标题往下，抓出同一组“通栏横线”。

    学术论文的表格多是三线表——只有首尾两条通栏横线，中间几百 pt 全是行内容，
    所以不能像图形那样按“小间隙”去吸，只能认横线。
    返回 (下边界, x0, x1, 横线条数)，找不到返回 None。
    """
    min_width = page.rect.width * 0.5
    max_gap = page.rect.height * 0.55      # 相邻横线隔了半页以上，肯定不是同一张表

    rules = [r for r in rects
             if r.height < 3 and r.width >= min_width and r.y0 >= cap.y1 - 1]
    if not rules:
        return None
    rules.sort(key=lambda r: r.y0)

    band = rules[0].y1
    x0, x1 = rules[0].x0, rules[0].x1
    count = 1
    for rule in rules[1:]:
        if rule.y0 - band > max_gap:
            break
        band = max(band, rule.y1)
        x0, x1 = min(x0, rule.x0), max(x1, rule.x1)
        count += 1
    return band, x0, x1, count


# --------------------------------------------------------------------------- #
# 提取
# --------------------------------------------------------------------------- #

class Extractor:
    def __init__(self, doc, dest: Path, args, label: str):
        self.doc = doc
        self.dest = dest
        self.args = args
        self.label = label
        self.used_names: set[str] = set()
        self.seen_xref: dict[int, int] = {}       # xref -> 页码
        self.seen_digest: dict[str, str] = {}     # md5 -> 来源描述
        self.rows: list[tuple[str, str, str, str]] = []   # 供 CSV 输出
        self.written = 0
        self.skipped = 0
        self.notes: list[str] = []

    # -- 输出 --------------------------------------------------------------- #

    def emit(self, stem: str, data: bytes, ext: str, source: str) -> bool:
        """写出一张图，返回是否真的写了。"""
        if len(data) < self.args.min_bytes:
            self.skipped += 1
            if self.args.verbose:
                print(f"    跳过（{len(data)} 字节，小于阈值）: {source}")
            return False

        digest = hashlib.md5(data).hexdigest()
        if not self.args.no_dedup and digest in self.seen_digest:
            self.skipped += 1
            if self.args.verbose:
                print(f"    跳过（与 {self.seen_digest[digest]} 内容重复）: {source}")
            return False
        self.seen_digest[digest] = source

        target = unique_path(self.dest, stem, ext, self.used_names)
        if self.args.dry_run:
            print(f"    [dry-run] {target}")
        else:
            self.dest.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        self.written += 1
        self.rows.append((self.label, f"{self.written}", source,
                          f"{len(data) / 1024:.1f}", target.name))
        if self.args.verbose:
            print(f"    {source}  ->  {target.name}  ({len(data) / 1024:.1f} KB)")
        return True

    # -- 模式 1：内嵌位图 ---------------------------------------------------- #

    def run_images(self, pages: set[int] | None) -> None:
        for pno in range(self.doc.page_count):
            if pages is not None and (pno + 1) not in pages:
                continue
            for index, info in enumerate(self.doc[pno].get_images(full=True)):
                xref = info[0]
                if xref in self.seen_xref:
                    self.skipped += 1
                    if self.args.verbose:
                        print(f"    跳过（与第 {self.seen_xref[xref]} 页复用同一对象）: xref {xref}")
                    continue
                self.seen_xref[xref] = pno + 1

                width, height = info[2], info[3]
                if width < self.args.min_dim or height < self.args.min_dim:
                    self.skipped += 1
                    if self.args.verbose:
                        print(f"    跳过（{width}x{height}，小于 --min-dim）: xref {xref}")
                    continue

                try:
                    raw = self.doc.extract_image(xref)
                except Exception as exc:
                    self.notes.append(f"第 {pno + 1} 页 xref {xref} 解析失败: {exc}")
                    self.skipped += 1
                    continue

                data, ext = raw["image"], raw["ext"]
                source = f"p{pno + 1:03d} xref{xref} {width}x{height}"

                # 有透明蒙版就合成 RGBA PNG
                smask = raw.get("smask")
                if smask:
                    try:
                        mask = self.doc.extract_image(smask)["image"]
                        merged = compose_alpha(data, mask)
                        if merged:
                            data, ext = merged, "png"
                            source += "+alpha"
                    except Exception:
                        pass

                data, ext = normalize_image(data, ext, force_rgb=not self.args.keep_cmyk)
                self.emit(f"p{pno + 1:03d}_{index:02d}", data, ext, source)

    # -- 模式 3：按标题裁剪图表 ---------------------------------------------- #

    def run_figures(self, pages: set[int] | None, dpi: int) -> None:
        """把每个 "Fig. N" / "Table N" 区域单独裁出来渲染成 PNG。

        图表往往是“背景图 + 一堆小图 + 矢量箭头 + 文字标注”拼起来的，
        在 PDF 里根本不存在单一图片对象，只能按区域裁剪重画。
        """
        for pno in range(self.doc.page_count):
            if pages is not None and (pno + 1) not in pages:
                continue
            page = self.doc[pno]
            captions = find_captions(page)
            if not captions:
                continue
            vrects = visual_rects(page)
            max_height = page.rect.height * 0.85

            for kind, number, cap in captions:
                pad = 4.0
                if kind == "fig":
                    # 图题在图下方：从标题往上吸到图顶
                    band, x0, x1, count = expand_band(vrects, cap.y0, True, max_height)
                    if count == 0:
                        rect = None
                    else:
                        # 靠标题那侧要往里收 2pt，否则会切进标题文字里留半行字
                        rect = pymupdf.Rect(x0 - pad, band - pad, x1 + pad, cap.y0 - 2)
                else:
                    # 表题在表格上方：认通栏横线
                    found = table_band(page, cap, vrects)
                    if found is None:
                        rect = None
                    else:
                        band, x0, x1, _ = found
                        rect = pymupdf.Rect(x0 - pad, cap.y1 + 2, x1 + pad, band + pad)

                if rect is None:
                    self.notes.append(f"第 {pno + 1} 页 {kind} {number}: "
                                      "标题附近找不到图形/表格线，可能是纯文字排版")
                    self.skipped += 1
                    continue

                rect = rect & page.rect
                if rect.height < 24 or rect.width < 40:
                    self.notes.append(f"第 {pno + 1} 页 {kind} {number}: "
                                      f"裁出的区域太小（{rect.width:.0f}x{rect.height:.0f}pt），已跳过")
                    self.skipped += 1
                    continue

                pix = page.get_pixmap(clip=rect, dpi=dpi)
                stem = f"{'fig' if kind == 'fig' else 'tbl'}{number:03d}"
                source = (f"p{pno + 1:03d} {kind} {number} "
                          f"[{rect.x0:.0f},{rect.y0:.0f},{rect.x1:.0f},{rect.y1:.0f}] "
                          f"@{dpi}dpi")
                self.emit(stem, pix.tobytes("png"), "png", source)

    # -- 模式 2：整页渲染 ---------------------------------------------------- #

    def run_render(self, pages: set[int] | None, dpi: int) -> None:
        for pno in range(self.doc.page_count):
            if pages is not None and (pno + 1) not in pages:
                continue
            pix = self.doc[pno].get_pixmap(dpi=dpi)
            source = f"page {pno + 1} {pix.width}x{pix.height} @{dpi}dpi"
            if self.args.dry_run:
                print(f"    [dry-run] p{pno + 1:03d}.png")
                self.written += 1
                self.rows.append((self.label, f"{self.written}", source, "-", f"p{pno + 1:03d}.png"))
                continue
            if len(pix.samples) < self.args.min_bytes:
                self.skipped += 1
                continue
            self.dest.mkdir(parents=True, exist_ok=True)
            name = unique_path(self.dest, f"p{pno + 1:03d}", "png", self.used_names).name
            pix.save(self.dest / name)
            self.written += 1
            self.rows.append((self.label, f"{self.written}", source,
                              f"{len(pix.samples) / 1024:.1f}", name))
            if self.args.verbose:
                print(f"    {source}  ->  {name}")


# --------------------------------------------------------------------------- #
# 文件与入口
# --------------------------------------------------------------------------- #

def collect_inputs(inputs: list[str], recursive: bool) -> list[Path]:
    """展开命令行参数：目录只挑 .pdf，显式点名的文件一律保留。"""
    explicit, scanned = [], []
    for raw in inputs:
        p = Path(raw).expanduser()
        if p.is_dir():
            pattern = "**/*" if recursive else "*"
            scanned.extend(sorted(f for f in p.glob(pattern)
                                  if f.is_file() and f.suffix.lower() in PDF_SUFFIXES))
        elif p.is_file():
            explicit.append(p)
        else:
            print(f"警告: 路径不存在，已忽略 -> {p}"
                  "（若本意是指定输出目录，请写成 -o <目录>）", file=sys.stderr)

    seen, result = set(), []
    for f in explicit + scanned:
        key = str(f.resolve()).lower()
        if key not in seen:
            seen.add(key)
            result.append(f)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="extract_pdf_images",
        description="从 PDF 中提取内嵌图片、按标题裁剪图表、或整页渲染。"
                     "论文插图是多图层拼的，想要完整插图请用 --figures。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  python extract_pdf_images.py 论文.pdf
  python extract_pdf_images.py 论文.pdf --figures 300
  python extract_pdf_images.py 论文.pdf --render 300
  python extract_pdf_images.py 01day/ --recursive -o images
  python extract_pdf_images.py 论文.pdf --pages 3-8 --min-bytes 4096 -v
""",
    )
    parser.add_argument("inputs", nargs="+", help="一个或多个 .pdf 文件，或包含 PDF 的目录")
    parser.add_argument("-o", "--output", default="images", help="输出根目录（默认: ./images）")
    parser.add_argument("-r", "--recursive", action="store_true", help="递归扫描输入目录")
    parser.add_argument("--flatten", action="store_true", help="所有图片平铺到输出根目录，不按文档分文件夹")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--render", type=int, default=0, metavar="DPI",
                      help="整页渲染模式，例如 --render 300（矢量图/混合图必须用这个）")
    mode.add_argument("--figures", nargs="?", type=int, const=200, default=None, metavar="DPI",
                      help="按 Fig./Table 标题自动裁剪出每张图表并渲染（默认 200dpi），"
                           "解决“组合图不是一个图片对象”的问题")
    parser.add_argument("--pages", metavar="SPEC",
                        help="只处理指定页，例如 1-5,8,12-（三种模式通用）")
    parser.add_argument("--min-bytes", type=int, default=0, metavar="N",
                        help="小于 N 字节的图片视为占位图并跳过（默认 0）")
    parser.add_argument("--min-dim", type=int, default=0, metavar="PX",
                        help="宽或高小于 PX 像素的图片跳过，可滤掉 logo/图标（默认 0）")
    parser.add_argument("--no-dedup", action="store_true", help="关闭按内容去重")
    parser.add_argument("--keep-cmyk", action="store_true", help="保留 CMYK 原始编码，不做 RGB 转换")
    parser.add_argument("--csv", metavar="FILE", help="把导出清单写成 CSV")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要写出的文件，不实际写入")
    parser.add_argument("-v", "--verbose", action="store_true", help="打印每张图片的详细信息")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if pymupdf is None:
        print("缺少依赖 pymupdf，请先安装：\n"
              "    pip install pymupdf", file=sys.stderr)
        return 2

    files = collect_inputs(args.inputs, args.recursive)
    if not files:
        print("没有找到任何 PDF 文件。", file=sys.stderr)
        return 1

    try:
        pages = parse_pages(args.pages)
    except ValueError:
        print(f"--pages 格式无法解析: {args.pages}", file=sys.stderr)
        return 2

    output_root = Path(args.output).expanduser().resolve()
    if args.figures:
        mode = f"按标题裁剪图表 @{args.figures}dpi"
    elif args.render:
        mode = f"整页渲染 @{args.render}dpi"
    else:
        mode = "提取内嵌位图"
    print(f"共 {len(files)} 个 PDF，模式: {mode}，输出目录: {output_root}")

    all_rows: list[tuple[str, str, str, str, str]] = []
    total_written = total_skipped = failed = 0

    for path in files:
        dest = output_root if args.flatten else output_root / f"{path.stem}_images"
        try:
            doc = pymupdf.open(path)
        except Exception as exc:
            print(f"  ✗ {path.name}: 无法打开（{exc}）", file=sys.stderr)
            failed += 1
            continue

        try:
            if doc.needs_pass:
                print(f"  ✗ {path.name}: 文档已加密，需要密码", file=sys.stderr)
                failed += 1
                continue

            ex = Extractor(doc, dest, args, path.name)
            if args.figures:
                ex.run_figures(pages, args.figures)
            elif args.render:
                ex.run_render(pages, args.render)
            else:
                ex.run_images(pages)

            if ex.written:
                print(f"  ✓ {path.name}: 导出 {ex.written} 张，跳过 {ex.skipped} 张  ->  {dest}")
            else:
                print(f"  ! {path.name}: 没有可导出的图片")
                if not args.render and not args.figures:
                    print("      · 这份 PDF 里的图可能是矢量图形或拼合图，没有独立的图片对象")
                    print("      · 试按标题裁剪：--figures 300       或整页渲染：--render 300")
            for note in ex.notes:
                print(f"      · {note}")

            total_written += ex.written
            total_skipped += ex.skipped
            all_rows.extend(ex.rows)
        finally:
            doc.close()

    if args.csv and all_rows and not args.dry_run:
        import csv
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(["来源文件", "序号", "位置/尺寸", "大小(KB)", "输出文件名"])
            writer.writerows(all_rows)
        print(f"清单已写入: {Path(args.csv).resolve()}")

    print(f"\n完成: 共导出 {total_written} 张图片"
          f"{f'，跳过 {total_skipped} 张' if total_skipped else ''}"
          f"{f'，失败 {failed} 个文件' if failed else ''}。")
    return 0 if total_written or not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
