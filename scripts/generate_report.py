#!/usr/bin/env python3
import argparse
import html
import sqlite3
from pathlib import Path


TABLES = [
    "movimientos",
    "seguros",
    "gestoria",
    "hipotecas",
    "alquileres",
    "inversores",
    "inversure_operaciones",
]

PRODUCT_NAME = "Verifika²"


def fetch_all(conn, query, params=None):
    cur = conn.execute(query, params or ())
    cols = [c[0] for c in cur.description]
    rows = cur.fetchall()
    return cols, rows


def render_table(title, cols, rows, limit_note=None):
    out = []
    out.append(f"<h3>{html.escape(title)}</h3>")
    if limit_note:
        out.append(f"<p class='note'>{html.escape(limit_note)}</p>")
    out.append("<table>")
    out.append("<thead><tr>")
    for col in cols:
        out.append(f"<th>{html.escape(col)}</th>")
    out.append("</tr></thead><tbody>")
    for row in rows:
        out.append("<tr>")
        for cell in row:
            text = "" if cell is None else str(cell)
            out.append(f"<td>{html.escape(text)}</td>")
        out.append("</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description="Generate an HTML report from SQLite.")
    parser.add_argument("--db", default="data/erp_import2.sqlite", help="SQLite path.")
    parser.add_argument(
        "--out", default="reports/erp_report.html", help="HTML output path."
    )
    parser.add_argument(
        "--logo",
        default="assets/verifika2/verifika2_wordmark_check_green.png",
        help="Path to a logo image to show in the report (wordmark recomendado).",
    )
    parser.add_argument("--limit", type=int, default=100, help="Rows per table.")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)

    companies_cols, companies_rows = fetch_all(
        conn,
        "SELECT nombre FROM empresas ORDER BY nombre",
    )

    counts_cols, counts_rows = fetch_all(
        conn,
        """
        SELECT e.nombre AS empresa,
          (SELECT COUNT(*) FROM movimientos m WHERE m.empresa_id = e.id) AS bdt,
          (SELECT COUNT(*) FROM seguros s WHERE s.empresa_id = e.id) AS seguros,
          (SELECT COUNT(*) FROM gestoria g WHERE g.empresa_id = e.id) AS gestoria,
          (SELECT COUNT(*) FROM hipotecas h WHERE h.empresa_id = e.id) AS hipotecas,
          (SELECT COUNT(*) FROM alquileres a WHERE a.empresa_id = e.id) AS alquileres,
          (SELECT COUNT(*) FROM inversores i WHERE i.empresa_id = e.id) AS inversores,
          (SELECT COUNT(*) FROM inversure_operaciones io WHERE io.empresa_id = e.id) AS inversure_ops
        FROM empresas e
        ORDER BY e.nombre
        """,
    )

    out = []
    out.append(
        f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
	  <title>{PRODUCT_NAME} - Reporte</title>
  <style>
    :root {{
      color-scheme: light;
	      --gold: #F2C14E;
	      --gold-deep: #B9892B;
	      --sage: #22C55E;
	      --ink: #0B1D33;
	      --paper: #F5F7FB;
	      --mist: #EEF2F6;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
	      font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
      color: var(--ink);
	      background: radial-gradient(circle at 10% 0%, rgba(242, 193, 78, 0.14), var(--paper) 35%, #ffffff 60%) fixed;
    }}
    header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 28px 32px;
	      background: linear-gradient(120deg, #ffffff 0%, rgba(242, 193, 78, 0.08) 45%, rgba(34, 197, 94, 0.04) 100%);
	      border-bottom: 1px solid rgba(226, 232, 240, 0.9);
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 18px;
    }}
	    .brand img {{
	      width: 220px;
	      height: auto;
	      border-radius: 0;
	      background: transparent;
	      box-shadow: none;
	    }}
	    .brand h1 {{
	      margin: 0;
	      font-size: 22px;
	      letter-spacing: 0.2px;
	    }}
	    .brand p {{
	      margin: 6px 0 0;
	      color: var(--ink);
	      font-size: 14px;
	      letter-spacing: 0.3px;
	    }}
	    .meta {{
	      text-align: right;
	      color: rgba(11, 29, 51, 0.72);
	      font-size: 13px;
	      letter-spacing: 0.2px;
	    }}
    main {{
      padding: 28px 32px 48px;
      display: grid;
      gap: 24px;
    }}
    section {{
      background: var(--paper);
      border: 1px solid #e4e0d7;
      border-radius: 16px;
      padding: 20px 22px;
      box-shadow: 0 12px 28px rgba(34, 28, 20, 0.08);
      animation: fadeUp 0.7s ease both;
    }}
    section:nth-of-type(2) {{ animation-delay: 0.08s; }}
    section:nth-of-type(3) {{ animation-delay: 0.16s; }}
	    h2 {{
	      margin: 0 0 12px;
	      font-size: 22px;
	      color: var(--ink);
	      display: flex;
	      align-items: center;
	      gap: 10px;
	    }}
	    .pill {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 10px;
      border-radius: 999px;
	      background: rgba(242, 193, 78, 0.18);
	      color: var(--ink);
      font-size: 12px;
      letter-spacing: 0.4px;
      text-transform: uppercase;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 16px;
    }}
    .card {{
      border: 1px solid #e2ddd3;
      padding: 14px 16px;
      border-radius: 12px;
      background: #fffefb;
    }}
    .card h3 {{
      margin: 0 0 6px;
      font-size: 16px;
      color: var(--sage);
    }}
    .muted {{ color: #6c675f; font-size: 13px; }}
    table {{
      border-collapse: collapse;
      width: 100%;
      margin-top: 10px;
      font-size: 13px;
      background: white;
      border-radius: 12px;
      overflow: hidden;
    }}
    th, td {{
      border-bottom: 1px solid #ece7dd;
      padding: 8px 10px;
      text-align: left;
    }}
	    th {{
	      background: linear-gradient(90deg, rgba(242, 193, 78, 0.16) 0%, rgba(56, 189, 248, 0.06) 100%);
	      color: var(--ink);
	      font-weight: 600;
	    }}
    tbody tr:nth-child(even) {{ background: #fbfaf7; }}
    .note {{ color: #7b7369; margin-top: -4px; }}
    .toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
      margin-bottom: 12px;
    }}
    .toolbar input {{
      border: 1px solid #d8d1c4;
      border-radius: 999px;
      padding: 8px 14px;
      background: #ffffff;
      min-width: 240px;
    }}
	    .tag {{
	      background: rgba(34, 197, 94, 0.12);
	      color: var(--ink);
	      padding: 4px 10px;
	      border-radius: 999px;
	      font-size: 12px;
	      letter-spacing: 0.3px;
	    }}
    @keyframes fadeUp {{
      from {{ opacity: 0; transform: translateY(14px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}
    @media (max-width: 720px) {{
      header {{ flex-direction: column; align-items: flex-start; gap: 12px; }}
      .meta {{ text-align: left; }}
      main {{ padding: 20px; }}
    }}
  </style>
</head>
<body>
  <header>
	    <div class="brand">
	      <img src="{html.escape(args.logo)}" alt="{PRODUCT_NAME}" onerror="this.style.display='none'" />
	      <div>
	        <h1>{PRODUCT_NAME}</h1>
	        <p>Panel base de datos · Fase 1</p>
	      </div>
	    </div>
    <div class="meta">
      <div>Reporte interno</div>
      <div>Datos importados desde Excel</div>
    </div>
  </header>
  <main>
"""
    )

    out.append("<section>")
    out.append("<h2>Empresas <span class='pill'>Activas</span></h2>")
    out.append(render_table("Listado", companies_cols, companies_rows))
    out.append("</section>")

    out.append("<section>")
    out.append("<h2>Conteo por empresa <span class='pill'>Modulos</span></h2>")
    out.append(render_table("Conteos", counts_cols, counts_rows))
    out.append("</section>")

    out.append("<section>")
    out.append(
        "<div class='toolbar'>"
        "<span class='tag'>Muestras</span>"
        "<input id='filter' placeholder='Buscar en las tablas...' />"
        "</div>"
    )
    out.append("<h2>Tablas principales</h2>")
    for table in TABLES:
        cols, rows = fetch_all(
            conn, f"SELECT * FROM {table} LIMIT ?", (args.limit,)
        )
        out.append(
            render_table(
                table,
                cols,
                rows,
                limit_note=f"Muestra de {args.limit} filas (max).",
            )
        )

    out.append(
        """
    </section>
  </main>
  <script>
    const filter = document.getElementById("filter");
    if (filter) {
      filter.addEventListener("input", (event) => {
        const term = event.target.value.toLowerCase();
        document.querySelectorAll("table").forEach((table) => {
          const rows = table.querySelectorAll("tbody tr");
          rows.forEach((row) => {
            const text = row.innerText.toLowerCase();
            row.style.display = text.includes(term) ? "" : "none";
          });
        });
      });
    }
  </script>
</body></html>
"""
    )

    Path(args.out).write_text("\n".join(out), encoding="utf-8")
    print(f"Reporte generado: {args.out}")


if __name__ == "__main__":
    main()
