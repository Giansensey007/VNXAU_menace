#!/usr/bin/env python3
"""
Generate docs/vnxau-menace-routes-executive.pdf — executive route map with chain/token arrows.

Usage:
  python scripts/generate_executive_routes_pdf.py
  python scripts/generate_executive_routes_pdf.py --no-compile
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
sys.path.insert(0, str(ROOT))

from src.config_loader import load_bot_config
from src.scanner.routes import ALL_DIRECTIONS, active_directions
from src.vnx.deposits import min_deposit_usdc, min_deposit_vnxau
from src.vnx.trading import vnxau_min_order

PDF_STEM = "vnxau-menace-routes-executive"
ETH_CONTRACT = "0x6d57B2E05F26C26b549231c866bdd39779e4a488"

# label, nodes: (style, line1, line2, dex_tag)
ROUTE_FLOWS: dict[str, tuple[str, list[tuple[str, str, str, str | None]]]] = {
    "base_to_solana": (
        "base$\\rightarrow$sol",
        [
            ("hub_base", "Base", "USDC", None),
            ("act", "Kyber", "USDC$\\rightarrow$VNXAU", "Kyber"),
            ("hub_vnx", "VNX", "bridge", "VNX"),
            ("act", "Jupiter", "VNXAU$\\rightarrow$USDC", "Jupiter"),
            ("hub_sol", "Sol", "USDC", None),
            ("recon", "Wormhole", "USDC", "WH"),
        ],
    ),
    "solana_to_base": (
        "sol$\\rightarrow$base",
        [
            ("hub_sol", "Sol", "USDC", None),
            ("act", "Jupiter", "USDC$\\rightarrow$VNXAU", "Jupiter"),
            ("hub_vnx", "VNX", "bridge", "VNX"),
            ("act", "Kyber", "VNXAU$\\rightarrow$USDC", "Kyber"),
            ("hub_base", "Base", "USDC", None),
            ("recon", "Wormhole", "USDC", "WH"),
        ],
    ),
    "base_to_vnx": (
        "base$\\rightarrow$vnx",
        [
            ("hub_base", "Base", "USDC", None),
            ("act", "Kyber", "USDC$\\rightarrow$VNXAU", "Kyber"),
            ("hub_vnx", "VNX", "deposit", "VNX"),
            ("act", "Platform", "sell VNXAU", "VNX"),
            ("hub_vnx", "VNX", "USDC", None),
        ],
    ),
    "vnx_to_base": (
        "vnx$\\rightarrow$base",
        [
            ("hub_vnx", "VNX", "USDC", None),
            ("act", "Platform", "buy VNXAU", "VNX"),
            ("hub_vnx", "VNX", "withdraw", "VNX"),
            ("act", "Kyber", "VNXAU$\\rightarrow$USDC", "Kyber"),
            ("hub_base", "Base", "USDC", None),
        ],
    ),
    "ethereum_to_vnx": (
        "eth$\\rightarrow$vnx",
        [
            ("hub_eth", "ETH", "USDC", None),
            ("act", "Kyber", "USDC$\\rightarrow$VNXAU", "Kyber"),
            ("hub_vnx", "VNX", "deposit", "VNX"),
            ("act", "Platform", "sell VNXAU", "VNX"),
            ("hub_vnx", "VNX", "USDC", None),
        ],
    ),
    "vnx_to_ethereum": (
        "vnx$\\rightarrow$eth",
        [
            ("hub_vnx", "VNX", "USDC", None),
            ("act", "Platform", "buy VNXAU", "VNX"),
            ("hub_vnx", "VNX", "withdraw", "VNX"),
            ("act", "Kyber", "VNXAU$\\rightarrow$USDC", "Kyber"),
            ("hub_eth", "ETH", "USDC", None),
        ],
    ),
    "solana_to_vnx": (
        "sol$\\rightarrow$vnx",
        [
            ("hub_sol", "Sol", "USDC", None),
            ("act", "Jupiter", "USDC$\\rightarrow$VNXAU", "Jupiter"),
            ("hub_vnx", "VNX", "deposit", "VNX"),
            ("act", "Platform", "sell VNXAU", "VNX"),
            ("hub_vnx", "VNX", "USDC", None),
            ("recon", "CCTP", "return", "CCTP"),
        ],
    ),
    "vnx_to_solana": (
        "vnx$\\rightarrow$sol",
        [
            ("hub_vnx", "VNX", "USDC", None),
            ("act", "Platform", "buy VNXAU", "VNX"),
            ("hub_vnx", "VNX", "withdraw", "VNX"),
            ("act", "Jupiter", "VNXAU$\\rightarrow$USDC", "Jupiter"),
            ("hub_sol", "Sol", "USDC", None),
            ("recon", "CCTP", "Sol$\\rightarrow$ETH", "CCTP"),
        ],
    ),
}

GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("Base $\\leftrightarrow$ Solana", ("base_to_solana", "solana_to_base")),
    ("Base $\\leftrightarrow$ VNX platform", ("base_to_vnx", "vnx_to_base")),
    ("Ethereum $\\leftrightarrow$ VNX platform", ("ethereum_to_vnx", "vnx_to_ethereum")),
    ("Solana $\\leftrightarrow$ VNX (+ CCTP)", ("solana_to_vnx", "vnx_to_solana")),
]

STYLES = r"""
% !TeX program = lualatex
\documentclass[9pt,a4paper,landscape]{article}
\usepackage[a4paper,landscape,margin=7mm]{geometry}
\usepackage{fontspec}
\usepackage{microtype}
\defaultfontfeatures{Ligatures=TeX}
\IfFontExistsTF{Inter}{\usepackage[sfdefault,tabular]{inter}}{
  \IfFontExistsTF{Helvetica Neue}{\setmainfont{Helvetica Neue}}{\setmainfont{TeX Gyre Heros}}}
\usepackage{xcolor}
\usepackage{tikz}
\usetikzlibrary{arrows.meta}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\definecolor{ink}{RGB}{25,35,55}
\definecolor{surface}{RGB}{245,248,252}
\definecolor{primary}{RGB}{0,82,155}
\definecolor{profit}{RGB}{21,122,78}
\definecolor{profitbg}{RGB}{220,245,230}
\definecolor{goldfill}{RGB}{255,248,220}
\definecolor{goldstroke}{RGB}{184,134,11}
\definecolor{basefill}{RGB}{232,245,233}
\definecolor{basestroke}{RGB}{46,125,50}
\definecolor{solfill}{RGB}{234,218,255}
\definecolor{solstroke}{RGB}{122,43,210}
\definecolor{ethfill}{RGB}{221,228,250}
\definecolor{ethstroke}{RGB}{67,85,187}
\definecolor{vnxfill}{RGB}{224,242,240}
\definecolor{vnxstroke}{RGB}{0,107,98}
\definecolor{callout}{RGB}{255,243,224}
\definecolor{calloutstroke}{RGB}{230,126,34}
\definecolor{warnbg}{RGB}{254,235,235}
\definecolor{warnstroke}{RGB}{197,48,48}
\newcommand{\statlabel}[1]{{\fontsize{6}{7.5}\selectfont\bfseries\textcolor{ink!55}{\MakeUppercase{#1}}}}
\tikzset{
  hub_base/.style={draw=basestroke,thick,fill=basefill,rounded corners=2pt,minimum height=6.8mm,minimum width=12.5mm,align=center,font=\fontsize{6.2}{7.5}\selectfont\bfseries,inner sep=1pt},
  hub_sol/.style={draw=solstroke,thick,fill=solfill,rounded corners=2pt,minimum height=6.8mm,minimum width=12.5mm,align=center,font=\fontsize{6.2}{7.5}\selectfont\bfseries,inner sep=1pt},
  hub_eth/.style={draw=ethstroke,thick,fill=ethfill,rounded corners=2pt,minimum height=6.8mm,minimum width=12.5mm,align=center,font=\fontsize{6.2}{7.5}\selectfont\bfseries,inner sep=1pt},
  hub_vnx/.style={draw=vnxstroke,thick,fill=vnxfill,rounded corners=2pt,minimum height=6.8mm,minimum width=12.5mm,align=center,font=\fontsize{6.2}{7.5}\selectfont\bfseries,inner sep=1pt},
  act/.style={draw=goldstroke!60,fill=goldfill!35,rounded corners=2pt,minimum height=6.8mm,minimum width=12mm,align=center,font=\fontsize{6}{7.2}\selectfont,inner sep=1pt},
  recon/.style={draw=primary!55,fill=primary!8,dashed,thick,rounded corners=2pt,minimum height=6.8mm,minimum width=11mm,align=center,font=\fontsize{5.8}{7}\selectfont\bfseries,text=primary,inner sep=1pt},
  arr/.style={-{Stealth[length=1.5mm]},thick,draw=ink!45},
  rowlbl/.style={anchor=east,font=\fontsize{6.2}{7.5}\selectfont\bfseries,text=ink!70,minimum width=15mm,align=right},
  grp/.style={anchor=west,font=\fontsize{8}{9.5}\selectfont\bfseries,text=primary},
}
\def\FxA{0}\def\FxB{16.5}\def\FxC{32.5}\def\FxD{48.5}\def\FxE{64.5}\def\FxF{80.5}\def\FxG{96.5}
"""


def _flow_row(row: int, y: int, label: str, nodes: list[tuple], active: bool) -> list[str]:
    cols = ["A", "B", "C", "D", "E", "F", "G"]
    lines: list[str] = []
    opacity = "" if active else ", opacity=0.42"
    lines.append(rf"\node[rowlbl,text={('primary' if active else 'ink!40')}] at (-2,{y}) {{{label}}};")
    prev = None
    for i, (kind, l1, l2, tag) in enumerate(nodes):
        if i >= len(cols):
            break
        nid = f"r{row}_{i}"
        tag_tex = rf"\\{{\fontsize{{4.8}}{{5.8}}\selectfont\textcolor{{ink!45}}{{{tag}}}}}" if tag else ""
        lines.append(
            rf"\node[{kind}{opacity},anchor=west] ({nid}) at (\Fx{cols[i]},{y}) {{{l1}\\{l2}{tag_tex}}};"
        )
        if prev:
            lines.append(rf"\draw[arr{opacity}] ({prev})--({nid});")
        prev = nid
    return lines


def build_latex() -> str:
    cfg = load_bot_config()
    active = set(active_directions(cfg))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    contract_short = ETH_CONTRACT[:6] + "…" + ETH_CONTRACT[-4:]

    lines = [
        STYLES,
        r"\begin{document}",
        r"\color{ink}",
        rf"{{\fontsize{{16}}{{18}}\selectfont\bfseries\color{{primary}} VNXAU Menace --- Executive Route Map}}\\[1pt]",
        rf"{{\fontsize{{9}}{{11}}\selectfont 8 directed VNXAU routes · Base + Ethereum mainnet + Solana · VNXAU/USDC}}\\[1pt]",
        rf"{{\fontsize{{7}}{{8.5}}\selectfont\textcolor{{ink!55}}{{{now} · KyberSwap Base+ETH · Jupiter Sol · github.com/Giansensey007/VNXAU\_menace}}}}",
        r"\vspace{1.5mm}\noindent\rule{\linewidth}{0.3pt}\vspace{1.5mm}",
        r"\noindent\renewcommand{\arraystretch}{1.1}",
        r"\begin{tabular}{@{}>{\centering\arraybackslash}p{0.19\linewidth}"
        r">{\centering\arraybackslash}p{0.19\linewidth}"
        r">{\centering\arraybackslash}p{0.19\linewidth}"
        r">{\centering\arraybackslash}p{0.19\linewidth}"
        r">{\centering\arraybackslash}p{0.19\linewidth}@{}}",
        rf"\fcolorbox{{primary!25}}{{surface}}{{\begin{{minipage}}[c][12mm][c]{{0.9\linewidth}}"
        rf"\statlabel{{Trade}}{{\fontsize{{9}}{{10.5}}\selectfont\bfseries {cfg.min_trade_vnxau:.1f}--{cfg.max_trade_vnxau:.0f} VNXAU}}"
        r"\end{minipage}}} &",
        rf"\fcolorbox{{primary!25}}{{surface}}{{\begin{{minipage}}[c][12mm][c]{{0.9\linewidth}}"
        rf"\statlabel{{Min profit}}{{\fontsize{{9}}{{10.5}}\selectfont\bfseries\textcolor{{profit}}{{$\geq$\${cfg.min_profit_usd:.2f}}}}}"
        r"\end{minipage}}} &",
        rf"\fcolorbox{{goldstroke!35}}{{goldfill!50}}{{\begin{{minipage}}[c][12mm][c]{{0.9\linewidth}}"
        rf"\statlabel{{ETH VNXAU}}{{\fontsize{{6.5}}{{8}}\selectfont\ttfamily {contract_short}}}"
        r"\end{minipage}}} &",
        rf"\fcolorbox{{primary!25}}{{surface}}{{\begin{{minipage}}[c][12mm][c]{{0.9\linewidth}}"
        rf"\statlabel{{Platform}}{{\fontsize{{9}}{{10.5}}\selectfont\bfseries {vnxau_min_order():.1f} VNXAU}}"
        r"\end{minipage}}} &",
        rf"\fcolorbox{{primary!25}}{{surface}}{{\begin{{minipage}}[c][12mm][c]{{0.9\linewidth}}"
        rf"\statlabel{{Deposit}}{{\fontsize{{9}}{{10.5}}\selectfont\bfseries {min_deposit_vnxau('BASE'):.0f} VNXAU / {min_deposit_usdc('ETH'):.0f} USDC}}"
        r"\end{minipage}}} \\",
        r"\end{tabular}",
        r"\vspace{1.5mm}\noindent\rule{\linewidth}{0.3pt}\vspace{1.5mm}",
        r"\noindent\begin{tikzpicture}[x=1mm,y=-1mm]",
        r"\node[hub_base,anchor=west] (tb) at (0,0) {Base\\USDC};",
        r"\node[hub_sol,anchor=west] (ts) at (36,0) {Sol\\USDC};",
        r"\node[hub_eth,anchor=west] (te) at (72,0) {ETH\\USDC};",
        r"\node[hub_vnx,anchor=west] (tv) at (108,0) {VNX\\VNXAU};",
        r"\draw[arr] (tb)--node[above,font=\fontsize{5}{6}\selectfont]{VNX VNXAU} (ts);",
        r"\draw[arr] (tb)--node[below,font=\fontsize{5}{6}\selectfont,pos=0.4]{VNX} (tv);",
        r"\draw[arr] (te)--node[above,font=\fontsize{5}{6}\selectfont]{VNX} (tv);",
        r"\draw[arr,dashed] (tb)--node[above,font=\fontsize{5}{6}\selectfont]{Wormhole USDC} (te);",
        r"\draw[arr,dashed] (ts)--node[below,font=\fontsize{5}{6}\selectfont]{CCTP USDC} (te);",
        r"\end{tikzpicture}",
        r"\vspace{1mm}",
        r"\noindent\begin{tikzpicture}[x=1mm,y=-1mm]",
    ]

    y = 0
    row_idx = 0
    for group_title, directions in GROUPS:
        y += 7
        lines.append(rf"\node[grp] at (0,{y}) {{{group_title}}};")
        y += 7
        for direction in directions:
            label, nodes = ROUTE_FLOWS[direction]
            lines += _flow_row(row_idx, y, label, nodes, direction in active)
            row_idx += 1
            y += 7

    lines += [
        r"\end{tikzpicture}",
        r"\vspace{1mm}\noindent\rule{\linewidth}{0.3pt}\vspace{1mm}",
        r"\noindent\fcolorbox{warnstroke}{warnbg}{\begin{minipage}{\linewidth}",
        r"{\fontsize{7.5}{9}\selectfont\bfseries\color{warnstroke} VNX ETH = USDC only} "
        r"{\fontsize{6.8}{8}\selectfont --- platform credits USDC deposits on Ethereum; "
        r"CCTP return path lands ETH USDC before \texttt{cctp\_sol\_usdc\_to\_vnx}.}",
        r"\end{minipage}}",
        r"\vspace{1mm}\noindent\rule{\linewidth}{0.3pt}\vspace{1mm}",
        r"\noindent\begin{minipage}[t]{0.55\linewidth}{\fontsize{6.8}{8}\selectfont",
        r"\textbf{Legend:} colored hub = chain stable · gold = swap leg · dashed = rebalance · ",
        rf"\textbf{{VNX}} bridge/platform · \textbf{{WH}} Wormhole USDC · \textbf{{CCTP}} Sol$\leftrightarrow$ETH · ETH contract \texttt{{{ETH_CONTRACT}}}",
        r"}\end{minipage}\hfill\begin{minipage}[t]{0.42\linewidth}\raggedleft{\fontsize{6.8}{8}\selectfont",
        r"\textbf{Flags:} \texttt{enable\_vnx\_arb\_routes} · \texttt{enable\_vnx\_cctp\_routes} · ",
        r"\textbf{Return:} \texttt{cctp\_sol\_usdc\_to\_vnx}",
        r"}\end{minipage}",
        r"\end{document}",
    ]
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--no-compile", action="store_true")
    args = p.parse_args()

    DOCS.mkdir(parents=True, exist_ok=True)
    tex_path = DOCS / f"{PDF_STEM}.tex"
    pdf_path = DOCS / f"{PDF_STEM}.pdf"
    tex_path.write_text(build_latex(), encoding="utf-8")
    print(f"Wrote {tex_path}")

    if args.no_compile:
        return 0

    proc = None
    for _ in range(2):
        proc = subprocess.run(
            ["lualatex", "-interaction=nonstopmode", "-output-directory", str(DOCS), tex_path.name],
            cwd=DOCS,
            capture_output=True,
            text=True,
        )
    if proc and pdf_path.exists():
        print(f"Wrote {pdf_path} ({pdf_path.stat().st_size:,} bytes)")
        return 0 if proc.returncode == 0 else 1

    print((proc.stdout if proc else "")[-3000:])
    print("lualatex failed", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
