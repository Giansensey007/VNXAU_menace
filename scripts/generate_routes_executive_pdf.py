#!/usr/bin/env python3
"""Generate docs/vnxau-menace-routes-executive.pdf — executive route diagram deck."""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
sys.path.insert(0, str(ROOT))

from src.scanner.routes import ALL_DIRECTIONS, active_directions

PDF_STEM = "vnxau-menace-routes-executive"
GITHUB = "VNXAU_menace"
BOT = "VNXAU Menace"
TOKEN = "VNXAU"
N_ROUTES = 8
VNX_MIN = 0.4
ETH_CONTRACT = "0x6d57B2E05F26C26b549231c866bdd39779e4a488"

ROUTE_FLOWS: dict[str, list[tuple[str, list[tuple[str, str, str, str | None]]]]] = {
    "base_to_solana": [("base→sol", [
        ("hub_base", "Base", "USDC", None), ("act", "Buy", TOKEN, "Kyber"),
        ("hub_vnx", "VNX", "bridge", "VNX"), ("act", "Sell", TOKEN, "Jupiter"),
        ("hub_sol", "Sol", "USDC", None), ("recon", "Wormhole", "USDC", "WH"),
    ])],
    "solana_to_base": [("sol→base", [
        ("hub_sol", "Sol", "USDC", None), ("act", "Buy", TOKEN, "Jupiter"),
        ("hub_vnx", "VNX", "bridge", "VNX"), ("act", "Sell", TOKEN, "Kyber"),
        ("hub_base", "Base", "USDC", None), ("recon", "Wormhole", "USDC", "WH"),
    ])],
    "base_to_vnx": [("base→vnx", [
        ("hub_base", "Base", "USDC", None), ("act", "Buy", TOKEN, "Kyber"),
        ("hub_vnx", "VNX", "deposit", "VNX"), ("act", "Sell", TOKEN, "Platform"),
        ("hub_vnx", "VNX", "USDC", None), ("recon", "Hub ETH", "WH+swap", "WH"),
    ])],
    "vnx_to_base": [("vnx→base", [
        ("hub_vnx", "VNX", "USDC", None), ("act", "Buy", TOKEN, "Platform"),
        ("hub_vnx", "VNX", "withdraw", "VNX"), ("act", "Sell", TOKEN, "Kyber"),
        ("hub_base", "Base", "USDC", None),
    ])],
    "ethereum_to_vnx": [("eth→vnx", [
        ("hub_eth", "ETH", "USDC", None), ("act", "Buy", TOKEN, "Kyber"),
        ("hub_vnx", "VNX", "deposit", "VNX"), ("act", "Sell", TOKEN, "Platform"),
        ("hub_vnx", "VNX", "USDC", None),
    ])],
    "vnx_to_ethereum": [("vnx→eth", [
        ("hub_vnx", "VNX", "USDC", None), ("act", "Buy", TOKEN, "Platform"),
        ("hub_vnx", "VNX", "withdraw", "VNX"), ("act", "Sell", TOKEN, "Kyber"),
        ("hub_eth", "ETH", "USDC", None),
    ])],
    "solana_to_vnx": [("sol→vnx", [
        ("hub_sol", "Sol", "USDC", None), ("act", "Buy", TOKEN, "Jupiter"),
        ("hub_vnx", "VNX", "deposit", "VNX"), ("act", "Sell", TOKEN, "Platform"),
        ("hub_vnx", "VNX", "USDC", None), ("recon", "CCTP", "Sol→ETH", "CCTP"),
    ])],
    "vnx_to_solana": [("vnx→sol", [
        ("hub_eth", "ETH", "USDC", None), ("act", "Buy", TOKEN, "Platform"),
        ("hub_vnx", "VNX", "withdraw", "VNX"), ("act", "Sell", TOKEN, "Jupiter"),
        ("hub_sol", "Sol", "USDC", None), ("recon", "CCTP", "ETH→Sol", "CCTP"),
    ])],
}

STYLES = r"""
\documentclass[9pt,a4paper,landscape]{article}
\usepackage[a4paper,landscape,margin=8mm]{geometry}
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
\definecolor{primary}{RGB}{0,82,155}
\definecolor{goldfill}{RGB}{255,248,220}\definecolor{goldstroke}{RGB}{184,134,11}
\definecolor{basefill}{RGB}{232,245,233}\definecolor{basestroke}{RGB}{46,125,50}
\definecolor{solfill}{RGB}{234,218,255}\definecolor{solstroke}{RGB}{122,43,210}
\definecolor{ethfill}{RGB}{221,228,250}\definecolor{ethstroke}{RGB}{67,85,187}
\definecolor{vnxfill}{RGB}{224,242,240}\definecolor{vnxstroke}{RGB}{0,107,98}
\definecolor{callout}{RGB}{255,243,224}\definecolor{calloutstroke}{RGB}{230,126,34}
\tikzset{
  hub_base/.style={draw=basestroke,thick,fill=basefill,rounded corners=2pt,minimum height=7mm,minimum width=13mm,align=center,font=\fontsize{6.5}{8}\selectfont\bfseries,inner sep=1pt},
  hub_sol/.style={draw=solstroke,thick,fill=solfill,rounded corners=2pt,minimum height=7mm,minimum width=13mm,align=center,font=\fontsize{6.5}{8}\selectfont\bfseries,inner sep=1pt},
  hub_eth/.style={draw=ethstroke,thick,fill=ethfill,rounded corners=2pt,minimum height=7mm,minimum width=13mm,align=center,font=\fontsize{6.5}{8}\selectfont\bfseries,inner sep=1pt},
  hub_vnx/.style={draw=vnxstroke,thick,fill=vnxfill,rounded corners=2pt,minimum height=7mm,minimum width=13mm,align=center,font=\fontsize{6.5}{8}\selectfont\bfseries,inner sep=1pt},
  act/.style={draw=goldstroke!60,fill=goldfill!30,rounded corners=2pt,minimum height=7mm,minimum width=11mm,align=center,font=\fontsize{6.2}{7.5}\selectfont,inner sep=1pt},
  recon/.style={draw=primary!55,fill=primary!8,dashed,thick,rounded corners=2pt,minimum height=7mm,minimum width=12mm,align=center,font=\fontsize{6}{7.5}\selectfont\bfseries,text=primary,inner sep=1pt},
  arr/.style={-{Stealth[length=1.6mm]},thick,draw=ink!45},
  rowlbl/.style={anchor=east,font=\fontsize{6.5}{8}\selectfont\bfseries,text=ink!70,minimum width=16mm,align=right},
}
\def\FxA{0}\def\FxB{17}\def\FxC{33}\def\FxD{49}\def\FxE{65}\def\FxF{81}\def\FxG{97}
"""


def _flow_row(y: float, label: str, nodes: list[tuple], active: bool) -> list[str]:
    cols = ["A", "B", "C", "D", "E", "F", "G"]
    lines: list[str] = []
    color = "primary" if active else "ink!40"
    lines.append(rf"\node[rowlbl,text={color}] at (-2,{y}) {{{label}}};")
    prev = None
    for i, (kind, l1, l2, tag) in enumerate(nodes):
        if i >= len(cols):
            break
        nid = f"n{int(y)}_{i}"
        tag_tex = rf"\\{{\fontsize{{5}}{{6}}\selectfont\textcolor{{ink!45}}{{{tag}}}}}" if tag else ""
        lines.append(rf"\node[{kind},anchor=west] ({nid}) at (\Fx{cols[i]},{y}) {{{l1}\\{l2}{tag_tex}}};")
        if prev:
            lines.append(rf"\draw[arr] ({prev})--({nid});")
        prev = nid
    return lines


def build_latex() -> str:
    active = set(active_directions())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    contract_short = ETH_CONTRACT[:6] + "…" + ETH_CONTRACT[-4:]
    lines = [STYLES, r"\begin{document}", r"\color{ink}",
        rf"{{\fontsize{{16}}{{18}}\selectfont\bfseries\color{{primary}} {BOT}}}\\[1pt]",
        rf"{{\fontsize{{9}}{{11}}\selectfont {N_ROUTES} directed {TOKEN} routes · Base + Ethereum + Solana (no Celo)}}\\[1pt]",
        rf"{{\fontsize{{7}}{{8.5}}\selectfont\textcolor{{ink!55}}{{{now} · github.com/Giansensey007/{GITHUB}}}}}",
        r"\vspace{2mm}\noindent\rule{\linewidth}{0.3pt}\vspace{2mm}",
        r"\noindent\begin{tikzpicture}[x=1mm,y=-1mm]",
        r"\node[hub_base,anchor=west] (tb) at (0,0) {Base\\USDC};",
        r"\node[hub_sol,anchor=west] (ts) at (38,0) {Sol\\USDC};",
        r"\node[hub_eth,anchor=west] (te) at (76,0) {ETH\\USDC};",
        r"\node[hub_vnx,anchor=west] (tv) at (114,0) {VNX\\USDC};",
        r"\draw[arr] (tb)--node[above,font=\fontsize{5}{6}\selectfont]{VNX VNXAU} (ts);",
        r"\draw[arr,dashed] (tb)--node[below,font=\fontsize{5}{6}\selectfont]{Wormhole} (te);",
        r"\draw[arr,dashed] (ts)--node[below,font=\fontsize{5}{6}\selectfont]{CCTP} (te);",
        r"\draw[arr] (te)--node[above,font=\fontsize{5}{6}\selectfont]{VNX USDC} (tv);",
        r"\draw[arr] (tb)--node[below,font=\fontsize{5}{6}\selectfont]{VNX VNXAU} (tv);",
        r"\draw[arr] (te)--node[below,font=\fontsize{5}{6}\selectfont]{on-chain VNXAU} (tv);",
        r"\end{tikzpicture}",
        r"\vspace{2mm}",
        r"\noindent\fcolorbox{goldstroke}{goldfill!40}{\begin{minipage}{0.98\linewidth}",
        rf"{{\fontsize{{6.8}}{{8}}\selectfont\bfseries ETH mainnet VNXAU contract:}} {{\fontsize{{6.5}}{{8}}\selectfont\texttt{{{contract_short}}}}} "
        rf"({ETH_CONTRACT}) --- KyberSwap on Base+ETH, Jupiter on Sol.",
        r"\end{minipage}}",
        r"\vspace{2mm}\noindent\begin{tikzpicture}[x=1mm,y=-1mm]",
    ]
    y = 0.0
    for direction in ALL_DIRECTIONS:
        for label, nodes in ROUTE_FLOWS.get(direction, []):
            y += 8.5
            lines += _flow_row(y, label, nodes, direction in active)
    lines += [
        r"\end{tikzpicture}",
        r"\vspace{2mm}\noindent\rule{\linewidth}{0.3pt}\vspace{1.5mm}",
        r"\noindent\begin{minipage}[t]{0.48\linewidth}{\fontsize{7}{8.5}\selectfont\bfseries Legend}\\[1pt]",
        r"{\fontsize{6.5}{8}\selectfont \textbf{VNX} VNXAU bridge + platform · \textbf{Wormhole} USDC rebalance · \textbf{CCTP} Sol$\leftrightarrow$ETH · gold token = VNXAU leg}",
        r"\end{minipage}\hfill\begin{minipage}[t]{0.48\linewidth}\raggedleft",
        rf"{{\fontsize{{7}}{{8.5}}\selectfont\bfseries Minimum sizes}}\\[1pt]",
        rf"{{\fontsize{{6.5}}{{8}}\selectfont Deposit 0.01 {TOKEN} · Platform {VNX_MIN} {TOKEN} · ETH USDC 20 · Deploy 0.5 {TOKEN}}}",
        r"\end{minipage}",
        r"\vspace{2mm}",
        r"\noindent\fcolorbox{calloutstroke}{callout}{\begin{minipage}{0.98\linewidth}",
        r"{\fontsize{6.8}{8}\selectfont\bfseries VNX Ethereum accepts USDC deposits only} --- on-chain VNXAU trades on ETH via Kyber; platform credit path uses USDC.",
        r"\end{minipage}}",
        r"\end{document}",
    ]
    return "\n".join(lines)


def main() -> int:
    DOCS.mkdir(parents=True, exist_ok=True)
    tex_path = DOCS / f"{PDF_STEM}.tex"
    pdf_path = DOCS / f"{PDF_STEM}.pdf"
    tex_path.write_text(build_latex(), encoding="utf-8")
    print(f"Wrote {tex_path}")
    for _ in range(2):
        proc = subprocess.run(
            ["lualatex", "-interaction=nonstopmode", "-output-directory", str(DOCS), tex_path.name],
            cwd=DOCS, capture_output=True, text=True,
        )
    if not pdf_path.exists():
        print((proc.stdout or "")[-3000:])
        return 1
    print(f"Wrote {pdf_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
