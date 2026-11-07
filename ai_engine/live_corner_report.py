"""Command-line report for the local live-corner SQLite database.

Run with: python -m ai_engine.live_corner_report [--db PATH] [--json]
This command is offline and read-only; it never calls API-Football.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

from ai_engine.live_corner_audit import audit_live_corner_database
from ai_engine.live_corner_backtest import run_live_corner_baseline_backtest


def build_live_corner_report(
    database_path: str | Path, *, over_under_lines: tuple[float, ...] = ()
) -> dict:
    """Combine structural coverage audit and chronological baseline evaluation."""
    path = Path(database_path)
    return {
        "database_path": str(path),
        "audit": audit_live_corner_database(path),
        "backtest": run_live_corner_baseline_backtest(
            path, over_under_lines=over_under_lines
        ),
        "safety": {
            "read_only": True,
            "api_requests": 0,
            "betting_signals_enabled": False,
        },
    }


def _human_summary(report: dict) -> str:
    audit = report["audit"]
    backtest = report["backtest"]
    captures = audit.get("captures", {})
    verified = audit.get("verified_history", {})
    quality = audit.get("quality", {})
    lines = [
        "FOOTBALL LAB — INFORME DE CÓRNERS EN VIVO",
        f"Base de datos: {report['database_path']}",
        "",
        "COBERTURA",
        f"- Snapshots capturados: {captures.get('snapshots', 0)}",
        f"- Partidos capturados: {captures.get('fixtures', 0)}",
        f"- Partidos pendientes de cierre: {captures.get('pending_fixtures', 0)}",
        f"- Observaciones verificadas: {verified.get('observations', 0)}",
        f"- Partidos con histórico verificado: {verified.get('fixtures', 0)}",
        f"- Parejas incompletas / inconsistentes: {quality.get('incomplete_pairs', 0)} / {quality.get('mismatched_pairs', 0)}",
        "",
        "BACKTEST CRONOLÓGICO",
    ]
    if backtest.get("available"):
        split = backtest["split"]
        metrics = backtest["metrics"]
        lines.extend([
            f"- Partidos entrenamiento / prueba: {split['train_fixtures']} / {split['test_fixtures']}",
            f"- MAE de córners restantes: {metrics['mae_remaining_corners']:.3f}",
            f"- Sesgo medio: {metrics['mean_signed_error']:.3f}",
            f"- MAE referencia media global: {backtest['benchmark']['mae_remaining_corners']:.3f}",
            (
                f"- Mejora de MAE vs referencia global: {backtest['mae_improvement_vs_global_mean']:.1%}"
                if backtest.get("mae_improvement_vs_global_mean") is not None
                else "- Mejora vs referencia global: no calculable (MAE de referencia = 0)"
            ),
            (
                f"- Evaluación rolling-origin: {backtest['rolling_origin']['fold_count']} bloques, "
                f"MAE ponderado {backtest['rolling_origin']['weighted_mae_remaining_corners']:.3f}, "
                f"estabilidad {backtest['rolling_origin']['stability']}, "
                f"rango MAE {backtest['rolling_origin']['fold_mae_range']:.3f}"
                if backtest.get("rolling_origin", {}).get("available")
                else f"- Evaluación rolling-origin no disponible: {backtest.get('rolling_origin', {}).get('reason', 'unknown')}"
            ),
            *[
                (
                    f"- Línea córners restantes O/U {item['line']:.1f}: "
                    f"acierto {item['accuracy']:.1%}, balanced accuracy "
                    f"{item['balanced_accuracy']:.1%}"
                    if item["balanced_accuracy"] is not None
                    else f"- Línea córners restantes O/U {item['line']:.1f}: balanced accuracy no disponible"
                )
                for item in backtest.get("over_under_line_evaluation", [])
            ],
            f"- Desgloses por liga/minuto: {len(backtest.get('by_league_minute_bucket', []))}",
            "- Interpretación: baseline experimental; no demuestra rentabilidad.",
        ])
    else:
        lines.append(f"- No disponible todavía: {backtest.get('reason', 'unknown')}")
    warnings = audit.get("warnings", [])
    if warnings:
        lines.extend(["", "ADVERTENCIAS"])
        lines.extend(f"- {warning}" for warning in warnings)
    lines.extend(["", "Solo lectura: sí | Solicitudes API: 0 | Señales de apuestas: desactivadas"])
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audita y evalúa el histórico live de córners sin llamadas de API."
    )
    default_path = os.environ.get("FOOTBALL_LAB_DB_PATH", "data/football_lab.sqlite3")
    parser.add_argument("--db", default=default_path, help="Ruta de la base SQLite.")
    parser.add_argument(
        "--corner-lines", default="",
        help="Líneas O/U de córners restantes separadas por coma (solo líneas x.5).",
    )
    parser.add_argument("--json", action="store_true", help="Imprime el informe completo en JSON.")
    args = parser.parse_args(argv)
    try:
        lines = tuple(float(value.strip()) for value in args.corner_lines.split(",") if value.strip())
    except ValueError as exc:
        parser.error(f"Líneas de córners no válidas: {exc}")
    report = build_live_corner_report(args.db, over_under_lines=lines)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else _human_summary(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
