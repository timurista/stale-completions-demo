"""Code-rendered diagram: old job starts -> goal changes -> old job completes -> admission decision.
Writes diagram.svg. The labels match fixture case "out-of-order" in fixtures.json. Run: python3 build_diagram.py"""
W, H = 1200, 520
INK, PANEL, LINE, FG, MUTED, TEAL, ROSE = "#0B0F14", "#0F141B", "#1E2733", "#E8EDF3", "#9AA6B5", "#35D0B0", "#EF7A6D"
steps = [
    ("1", "Job j1 starts", "bound to goal h1", "“Hotel in Lisbon”", LINE),
    ("2", "User changes the goal", "h2 replaces h1", "“Hotel in Porto”", LINE),
    ("3", "Old job finishes", "result c1, made for h1", "arrives after c2", LINE),
    ("4", "Admission decision", "is h1 still the goal?", "no: keep c1 as superseded", TEAL),
]
x0, bw, gap, y = 40, 250, 33, 150
parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-labelledby="t d">',
         '<title id="t">Admission decision for a result that finishes after the goal changed</title>',
         '<desc id="d">Four steps: job j1 starts for goal h1; the user replaces h1 with h2; j1 finishes and its result c1 arrives; admission compares c1\'s goal h1 with the current goal h2 and keeps c1 as superseded instead of making it active.</desc>',
         f'<rect width="{W}" height="{H}" fill="{INK}"/>',
         f'<text x="40" y="58" fill="{TEAL}" font-family="JetBrains Mono, Menlo, monospace" font-size="15" letter-spacing="2">SYNTHETIC SCHEDULE · CASE “OUT-OF-ORDER”</text>',
         f'<text x="40" y="98" fill="{FG}" font-family="Inter, system-ui, sans-serif" font-size="30" font-weight="700">The worker finished. Does the result still apply?</text>']
for i, (n, title, sub, note, border) in enumerate(steps):
    x = x0 + i * (bw + gap)
    parts.append(f'<rect x="{x}" y="{y}" width="{bw}" height="190" rx="16" fill="{PANEL}" stroke="{border}" stroke-width="2"/>')
    parts.append(f'<text x="{x+22}" y="{y+40}" fill="{TEAL if border==TEAL else MUTED}" font-family="JetBrains Mono, Menlo, monospace" font-size="15">STEP {n}</text>')
    parts.append(f'<text x="{x+22}" y="{y+80}" fill="{FG}" font-family="Inter, system-ui, sans-serif" font-size="21" font-weight="700">{title}</text>')
    parts.append(f'<text x="{x+22}" y="{y+114}" fill="{MUTED}" font-family="Inter, system-ui, sans-serif" font-size="17">{sub}</text>')
    parts.append(f'<text x="{x+22}" y="{y+146}" fill="{MUTED}" font-family="Inter, system-ui, sans-serif" font-size="17">{note}</text>')
    if i < 3:
        ax = x + bw + 4
        parts.append(f'<path d="M{ax} {y+95} h{gap-12}" stroke="{MUTED}" stroke-width="3"/><path d="M{ax+gap-12} {y+87} l9 8 l-9 8 z" fill="{MUTED}"/>')
parts.append(f'<rect x="40" y="380" width="{W-80}" height="92" rx="14" fill="none" stroke="{LINE}" stroke-width="2"/>')
parts.append(f'<text x="64" y="418" fill="{ROSE}" font-family="JetBrains Mono, Menlo, monospace" font-size="15">OVERWRITE ON ARRIVAL</text>')
parts.append(f'<text x="64" y="448" fill="{FG}" font-family="Inter, system-ui, sans-serif" font-size="18">c1 arrives last, so it becomes the active hotel: Lisbon, a goal the user already replaced.</text>')
parts.append(f'<text x="{W-40}" y="505" text-anchor="end" fill="{MUTED}" font-family="Inter, system-ui, sans-serif" font-size="14">Code-rendered from build_diagram.py · outcomes from results.json</text>')
parts.append('</svg>')
open("diagram.svg", "w").write("\n".join(parts) + "\n")
print("diagram.svg written")
