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
from src.scanner.routes import ALL_DIRECTIONS, active_directions, route_for_direction
from src.vnx.deposits import min_deposit_usdc, min_deposit_vnxau
from src.vnx.trading import vnxau_min_order

# (row_label, steps[(kind, text)], recon_text or None)
# kind: hub | act | vnx | recon
ROUTE_FLOWS: dict[str, tuple[str, list[tuple[str, str]], str | None]] = {
    "base_to_solana": (
        "base$\\rightarrow$sol",
        [
            ("hub", "Base\\\\USDC"),
            ("act", "Kyber\\\\USDC$\\rightarrow$VNXAU"),
            ("vnx", "VNX\\\\bridge"),
            ("act", "Jupiter\\\\VNXAU$\\rightarrow$USDC"),
            ("hub", "Sol\\\\USDC"),
        ],
        "Wormhole\\\\USDC\\\\Base$\\leftrightarrow$Sol",
    ),
    "solana_to_base": (
        "sol$\\rightarrow$base",
        [
            ("hub", "Sol\\\\USDC"),
            ("act", "Jupiter\\\\USDC$\\rightarrow$VNXAU"),
            ("vnx", "VNX\\\\bridge"),
            ("act", "Kyber\\\\VNXAU$\\rightarrow$USDC"),
            ("hub", "Base\\\\USDC"),
        ],
        "Wormhole\\\\USDC\\\\Sol$\\leftrightarrow$Base",
    ),
    "base_to_vnx": (
        "base$\\rightarrow$vnx",
        [
            ("hub", "Base\\\\USDC"),
            ("act", "Kyber\\\\USDC$\\rightarrow$VNXAU"),
            ("vnx", "VNX\\\\deposit"),
            ("vnx", "Platform\\\\sell"),
            ("hub", "VNX\\\\USDC"),
        ],
        None,
    ),
    "vnx_to_base": (
        "vnx$\\rightarrow$base",
        [
            ("hub", "VNX\\\\USDC"),
            ("vnx", "Platform\\\\buy"),
            ("vnx", "Withdraw\\\\BASE"),
            ("act", "Kyber\\\\VNXAU$\\rightarrow$USDC"),
            ("hub", "Base\\\\USDC"),
        ],
        None,
    ),
    "ethereum_to_vnx": (
        "eth$\\rightarrow$vnx",
        [
            ("hub", "ETH\\\\USDC"),
            ("act", "Kyber\\\\USDC$\\rightarrow$VNXAU"),
            ("vnx", "VNX\\\\deposit"),
            ("vnx", "Platform\\\\sell"),
            ("hub", "VNX\\\\USDC"),
        ],
        None,
    ),
    "vnx_to_ethereum": (
        "vnx$\\rightarrow$eth",
        [
            ("hub", "VNX\\\\USDC"),
            ("vnx", "Platform\\\\buy"),
            ("vnx", "Withdraw\\\\ETH"),
            ("act", "Kyber\\\\VNXAU$\\rightarrow$USDC"),
            ("hub", "ETH\\\\USDC"),
        ],
        None,
    ),
    "solana_to_vnx": (
        "sol$\\rightarrow$vnx",
        [
            ("hub", "Sol\\\\USDC"),
            ("act", "Jupiter\\\\USDC$\\rightarrow$VNXAU"),
            ("vnx", "VNX\\\\deposit"),
            ("vnx", "Platform\\\\sell"),
            ("hub", "VNX\\\\USDC"),
        ],
        "CCTP\\\\reconcile\\\\on return",
    ),
    "vnx_to_solana": (
        "vnx$\\rightarrow$sol",
        [
            ("hub", "VNX\\\\USDC"),
            ("vnx", "Platform\\\\buy"),
            ("vnx", "Withdraw\\\\SOL"),
            ("act", "Jupiter\\\\VNXAU$\\rightarrow$USDC"),
            ("hub", "Sol\\\\USDC"),
        ],
        "CCTP\\\\USDC\\\\Sol$\\rightarrow$ETH$\\rightarrow$VNX",
    ),
}

GROUPS: list[tuple[str, str, tuple[str, ...]]] = [
    ("base\\_sol", "Base $\\leftrightarrow$ Solana (always on)", ("base_to_solana", "solana_to_base")),
    ("base\\_vnx", "Base $\\leftrightarrow$ VNX platform", ("base_to_vnx", "vnx_to_base")),
    ("eth\\_vnx", "Ethereum $\\leftrightarrow$ VNX platform", ("ethereum_to_vnx", "vnx_to_ethereum")),
    ("vnx\\_sol", "Solana $\\leftrightarrow$ VNX (+ CCTP)", ("solana_to_vnx", "vnx_to_solana")),
]


def _tikz_route_row(row: int, y: int, direction: str, active: bool) -> list[str]:
    label, steps, recon = ROUTE_FLOWS[direction]
    xs = [0, 19, 38, 57, 76, 93]
    lines: list[str] = []
    opacity = "" if active else ", opacity=0.45"
    lines.append(rf"\node[rowlbl] at (-2,{y}) {{{label}}};")

    nodes: list[str] = []
    for i, (kind, text) in enumerate(steps):
        x = xs[i]
        nid = f"n{row}{i}"
        if kind == "hub":
            chain = text.split("\\\\")[0].lower()
            style = {
                "base": ("basestroke", "basefill"),
                "sol": ("solstroke", "solfill"),
                "eth": ("ethstroke", "ethfill"),
                "vnx": ("vnxstroke", "vnxfill"),
            }.get(chain, ("ink", "surface"))
            stroke, fill = style
            lines.append(
                rf"\node[hub={stroke}, fill={fill}{opacity}, anchor=west] ({nid}) at ({x},{y}) {{{text}}};"
            )
        elif kind == "vnx":
            lines.append(
                rf"\node[act=vnxstroke, fill=vnxfill{opacity}, anchor=west] ({nid}) at ({x},{y}) {{{text}}};"
            )
        else:
            chain_hint = "solstroke" if "Jupiter" in text else "basestroke"
            lines.append(
                rf"\node[act={chain_hint}{opacity}, anchor=west] ({nid}) at ({x},{y}) {{{text}}};"
            )
        nodes.append(nid)

    if recon:
        rid = f"r{row}"
        lines.append(
            rf"\node[recon{opacity}, anchor=west] ({rid}) at ({xs[5]},{y}) {{{recon}}};"
        )
        lines.append(
            rf"\draw[arr{opacity}] ({nodes[0]})--({nodes[1]})--({nodes[2]})--({nodes[3]})--({nodes[4]})--({rid});"
        )
    else:
        lines.append(
            rf"\draw[arr{opacity}] ({nodes[0]})--({nodes[1]})--({nodes[2]})--({nodes[3]})--({nodes[4]});"
        )
    return lines


def _build_latex() -> str:
    cfg = load_bot_config()
    active = set(active_directions(cfg))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    n_active = len(active)

    preamble = r"""% !TeX program = lualatex
\documentclass[9pt,a4paper,landscape]{article}
\usepackage[a4paper,landscape,margin=8mm]{geometry}
\usepackage{fontspec}
\usepackage{microtype}
\defaultfontfeatures{Ligatures=TeX}
\IfFontExistsTF{Inter}{\usepackage[sfdefault,tabular]{inter}}{
  \IfFontExistsTF{Helvetica Neue}{\setmainfont{Helvetica Neue}}{\setmainfont{TeX Gyre Heros}}}
\IfFontExistsTF{JetBrains Mono}{\setmonofont{JetBrains Mono}[Scale=0.88]}{
  \setmonofont{Latin Modern Mono}[Scale=0.88]}
\usepackage{xcolor}
\usepackage{array}
\usepackage{adjustbox}
\usepackage{tikz}
\usetikzlibrary{arrows.meta,calc,positioning}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\definecolor{ink}{RGB}{25,35,55}
\definecolor{surface}{RGB}{245,248,252}
\definecolor{primary}{RGB}{0,82,155}
\definecolor{gold}{RGB}{180,130,20}
\definecolor{basefill}{RGB}{221,235,250}
\definecolor{basestroke}{RGB}{37,99,168}
\definecolor{solfill}{RGB}{234,218,255}
\definecolor{solstroke}{RGB}{122,43,210}
\definecolor{ethfill}{RGB}{221,228,250}
\definecolor{ethstroke}{RGB}{67,85,187}
\definecolor{vnxfill}{RGB}{224,242,240}
\definecolor{vnxstroke}{RGB}{0,107,98}
\definecolor{profit}{RGB}{21,122,78}
\definecolor{profitbg}{RGB}{220,245,230}
\definecolor{badgeamber}{RGB}{252,238,186}
\definecolor{badgeambertext}{RGB}{168,44,0}
\newcommand{\statlabel}[1]{{\fontsize{6.5}{8}\selectfont\bfseries\textcolor{ink!55}{\MakeUppercase{#1}}}}
\newcommand{\badge}[3]{\tikz[baseline=(b.base)]{
  \node[draw=#2!40, fill=#2, rounded corners=1mm, inner xsep=1.8mm, inner ysep=0.6mm] (b)
    {{\fontsize{7}{8.5}\selectfont\bfseries\textcolor{#3}{\MakeUppercase{#1}}}};}}
\tikzset{
  hub/.style={draw=#1, thick, rounded corners=2pt, minimum height=7mm, minimum width=13mm,
    align=center, font=\fontsize{6.5}{7.5}\selectfont\bfseries, inner sep=0pt},
  hub/.default=ink,
  act/.style={draw=#1!55, fill=white, rounded corners=2pt, minimum height=7mm, minimum width=12mm,
    align=center, font=\fontsize{6.2}{7.2}\selectfont, inner sep=0pt},
  act/.default=ink,
  recon/.style={draw=primary!55, fill=primary!6, dashed, thick, rounded corners=2pt,
    minimum width=15mm, minimum height=7mm, align=center,
    font=\fontsize{6}{7}\selectfont\bfseries, text=primary, inner sep=1pt},
  rowlbl/.style={anchor=east, font=\fontsize{6.5}{7.5}\selectfont\bfseries, text=ink!65,
    minimum width=18mm, align=right},
  arr/.style={-{Stealth[length=1.6mm]}, thick, draw=ink!50},
  topnode/.style={draw=#1, thick, rounded corners=3pt, minimum height=9mm, minimum width=18mm,
    align=center, font=\fontsize{7}{8.5}\selectfont\bfseries, inner sep=1pt},
  toparr/.style={-{Stealth[length=2mm]}, thick, draw=ink!45},
}
\begin{document}
\color{ink}
"""

    header = rf"""
\noindent\begin{{tabular}}{{@{{}}>{{\raggedright\arraybackslash}}p{{0.62\linewidth}}@{{\hspace{{0.02\linewidth}}}}>{{\raggedright\arraybackslash}}p{{0.35\linewidth}}@{{}}}}
\begin{{minipage}}[t]{{\linewidth}}
  {{\fontsize{{17}}{{19}}\selectfont\bfseries\color{{primary}} VNXAU Menace --- Executive Route Map}}\\[1pt]
  {{\fontsize{{9}}{{11}}\selectfont 8 directed arb routes · Base + Ethereum + Solana · VNXAU/USDC}}\\[1pt]
  {{\fontsize{{7}}{{9}}\selectfont\textcolor{{ink!60}}{{KyberSwap on Base \& ETH · Jupiter on Sol · VNX bridge + CCTP}}}}
\end{{minipage}}
&
\begin{{minipage}}[t]{{\linewidth}}
  \raggedleft
  \badge{{{n_active} routes active}}{{profitbg}}{{profit}}\hspace{{1.5mm}}
  \badge{{platform treasury}}{{badgeamber}}{{badgeambertext}}\\[2pt]
  {{\fontsize{{7}}{{8.5}}\selectfont\textcolor{{ink!50}}{{{now} · github.com/Giansensey007/VNXAU\_menace}}}}
\end{{minipage}}\\
\end{{tabular}}
\vspace{{1mm}}\noindent\rule{{\linewidth}}{{0.3pt}}\vspace{{1.5mm}}
"""

    kpi = rf"""
\noindent\renewcommand{{\arraystretch}}{{1.12}}
\begin{{tabular}}{{@{{}}>{{\centering\arraybackslash}}p{{0.19\linewidth}}
  >{{\centering\arraybackslash}}p{{0.19\linewidth}}
  >{{\centering\arraybackslash}}p{{0.19\linewidth}}
  >{{\centering\arraybackslash}}p{{0.19\linewidth}}
  >{{\centering\arraybackslash}}p{{0.19\linewidth}}@{{}}}}
\fcolorbox{{primary!25}}{{surface}}{{\begin{{minipage}}[c][14mm][c]{{0.9\linewidth}}
  \statlabel{{Trade size}}\\[1pt]{{\fontsize{{9.5}}{{11}}\selectfont\bfseries {cfg.min_trade_vnxau:.1f}--{cfg.max_trade_vnxau:.0f}}}\\[0pt]
  {{\fontsize{{6.5}}{{8}}\selectfont\textcolor{{ink!65}}{{VNXAU}}}}
\end{{minipage}}}} &
\fcolorbox{{primary!25}}{{surface}}{{\begin{{minipage}}[c][14mm][c]{{0.9\linewidth}}
  \statlabel{{Min profit}}\\[1pt]{{\fontsize{{9.5}}{{11}}\selectfont\bfseries\textcolor{{profit}}{{$\geq$\${cfg.min_profit_usd:.2f}}}}}\\[0pt]
  {{\fontsize{{6.5}}{{8}}\selectfont\textcolor{{ink!65}}{{round-trip}}}}
\end{{minipage}}}} &
\fcolorbox{{gold!35}}{{badgeamber!30}}{{\begin{{minipage}}[c][14mm][c]{{0.9\linewidth}}
  \statlabel{{VNXAU contract}}\\[1pt]{{\fontsize{{6.5}}{{8}}\selectfont\ttfamily 0x6d57\ldots e4a488}}\\[0pt]
  {{\fontsize{{6.5}}{{8}}\selectfont\textcolor{{ink!65}}{{Ethereum mainnet}}}}
\end{{minipage}}}} &
\fcolorbox{{primary!25}}{{surface}}{{\begin{{minipage}}[c][14mm][c]{{0.9\linewidth}}
  \statlabel{{Platform min}}\\[1pt]{{\fontsize{{9.5}}{{11}}\selectfont\bfseries {vnxau_min_order():.1f} VNXAU}}\\[0pt]
  {{\fontsize{{6.5}}{{8}}\selectfont\textcolor{{ink!65}}{{buy/sell order}}}}
\end{{minipage}}}} &
\fcolorbox{{primary!25}}{{surface}}{{\begin{{minipage}}[c][14mm][c]{{0.9\linewidth}}
  \statlabel{{Deposit min}}\\[1pt]{{\fontsize{{9.5}}{{11}}\selectfont\bfseries {min_deposit_vnxau("BASE"):.0f} VNXAU}}\\[0pt]
  {{\fontsize{{6.5}}{{8}}\selectfont\textcolor{{ink!65}}{{BASE/SOL · {min_deposit_usdc("ETH"):.0f} USDC ETH}}}}
\end{{minipage}}}} \\
\end{{tabular}}
\vspace{{2mm}}\noindent\rule{{\linewidth}}{{0.3pt}}\vspace{{1.5mm}}
"""

    topology = r"""
\noindent\begin{tabular}{@{}>{\raggedright\arraybackslash}p{0.62\linewidth}@{\hspace{0.02\linewidth}}>{\raggedright\arraybackslash}p{0.35\linewidth}@{}}
\begin{minipage}[t]{\linewidth}
\begin{tikzpicture}[x=1mm,y=-1mm]
  \node[topnode=basestroke, fill=basefill] (b) at (0,0) {Base\\USDC hub};
  \node[topnode=solstroke, fill=solfill] (s) at (42,0) {Solana\\USDC hub};
  \node[topnode=ethstroke, fill=ethfill] (e) at (84,0) {Ethereum\\USDC hub};
  \node[topnode=vnxstroke, fill=vnxfill] (v) at (126,0) {VNX\\VNXAU treasury};
  \draw[toparr] (b) -- node[above, font=\fontsize{5.5}{7}\selectfont, text=ink!60] {VNX VNXAU} (s);
  \draw[toparr] (b) -- node[above, font=\fontsize{5.5}{7}\selectfont, text=ink!60, pos=0.35] {VNX} (v);
  \draw[toparr] (e) -- node[above, font=\fontsize{5.5}{7}\selectfont, text=ink!60] {VNX} (v);
  \draw[toparr, dashed] (b) -- node[above, font=\fontsize{5.5}{7}\selectfont, text=ink!50] {Wormhole USDC} (e);
  \draw[toparr, dashed] (s) -- node[below, font=\fontsize{5.5}{7}\selectfont, text=ink!50] {CCTP USDC} (e);
\end{tikzpicture}
\end{minipage}
&
\begin{minipage}[t]{\linewidth}
\noindent\fcolorbox{primary}{surface}{\begin{minipage}[t]{\dimexpr\linewidth-2\fboxsep-2\fboxrule\relax}
{\fontsize{7.5}{9}\selectfont\bfseries\color{primary} Hub stables \& DEX}\\[2pt]
{\fontsize{6.5}{8}\selectfont
\textbf{Base} USDC · \textbf{KyberSwap}\\
\textbf{Solana} USDC · \textbf{Jupiter}\\
\textbf{Ethereum} USDC · \textbf{KyberSwap}\\
\textbf{VNX} USDC · platform API\\
Idle VNXAU lives on platform only}
\end{minipage}}
\end{minipage}\\
\end{tabular}
\vspace{2mm}\noindent\rule{\linewidth}{0.3pt}\vspace{1.5mm}
"""

    body_lines: list[str] = []
    y = 0
    group_header_step = 10
    row_step = 9
    row_idx = 0

    body_lines.append(r"\noindent\adjustbox{width=\linewidth,center}{%")
    body_lines.append(r"\begin{tikzpicture}[x=0.82mm,y=-0.82mm]")
    body_lines.append(r"\useasboundingbox (-21,-2) rectangle (112,92);")

    for _g_idx, (_group_id, group_title, directions) in enumerate(GROUPS):
        gy = y
        body_lines.append(
            rf"\node[anchor=west, font=\fontsize{{8.5}}{{10}}\selectfont\bfseries\color{{primary}}] at (0,{gy}) {{{group_title}}};"
        )
        y += group_header_step
        for direction in directions:
            body_lines.extend(_tikz_route_row(row_idx, y, direction, direction in active))
            row_idx += 1
            y += row_step

    body_lines.append(
        rf"\node[anchor=west, font=\fontsize{{6}}{{7.5}}\selectfont, text=ink!55, text width=112mm] at (0,{y + 2}) "
        r"{Each row = one scanned direction. Dashed recon box = post-trade stable rebalance. Greyed rows = flag-disabled.};"
    )
    body_lines.append(r"\end{tikzpicture}}")

    footer = r"""
\vspace{1mm}\noindent\rule{\linewidth}{0.3pt}\vspace{1mm}
\noindent\begin{tabular}{@{}>{\raggedright\arraybackslash}p{0.62\linewidth}@{\hspace{0.02\linewidth}}>{\raggedright\arraybackslash}p{0.35\linewidth}@{}}
\begin{minipage}[t]{\linewidth}
{\fontsize{7}{8.5}\selectfont
\textbf{Flags:} \texttt{enable\_vnx\_arb\_routes} (base\_vnx + eth\_vnx) ·
\texttt{enable\_vnx\_cctp\_routes} (vnx\_sol)\\
\textbf{Return:} \texttt{cctp\_sol\_usdc\_to\_vnx} closes platform $\rightarrow$ sol loops via CCTP}
\end{minipage}
&
\begin{minipage}[t]{\linewidth}
\raggedleft
{\fontsize{7}{8.5}\selectfont
\textbf{Matrix:} \texttt{scripts/execute\_route\_matrix.py}\\
\textbf{Full map:} \texttt{scripts/generate\_routes\_pdf.py}}
\end{minipage}\\
\end{tabular}
\end{document}
"""

    return preamble + header + kpi + topology + "\n".join(body_lines) + footer


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--no-compile", action="store_true")
    args = p.parse_args()

    DOCS.mkdir(parents=True, exist_ok=True)
    tex_path = DOCS / "vnxau-menace-routes-executive.tex"
    pdf_path = DOCS / "vnxau-menace-routes-executive.pdf"
    tex = _build_latex()
    tex_path.write_text(tex, encoding="utf-8")
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
    if proc and proc.returncode == 0 and pdf_path.exists():
        print(f"Wrote {pdf_path} ({pdf_path.stat().st_size:,} bytes)")
        return 0

    if proc:
        print(proc.stdout[-3000:] if proc.stdout else "")
        print(proc.stderr[-1000:] if proc.stderr else "")
    print("lualatex compile failed", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
