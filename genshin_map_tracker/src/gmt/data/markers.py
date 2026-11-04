"""Banco local (SQLite) de marcadores e do progresso de coleta.

Os marcadores vêm do site do mapa (lidos pela própria página) ou de um arquivo
JSON. As coordenadas ficam no sistema do site, para casar direto com o mapa web.
O progresso (o que já foi pego) é guardado aqui também, como cópia local do que
foi marcado no site, e pode ser exportado/importado em JSON.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS markers (
    id      TEXT PRIMARY KEY,
    kind    TEXT NOT NULL,          -- 'chest', 'anemoculus', 'geoculus', ...
    layer   TEXT NOT NULL,          -- 'teyvat', 'enkanomiya', ...
    x       REAL NOT NULL,          -- coordenada do site
    y       REAL NOT NULL,
    name    TEXT,
    source  TEXT
);
CREATE INDEX IF NOT EXISTS markers_kind_layer ON markers(kind, layer);
CREATE TABLE IF NOT EXISTS progress (
    marker_id TEXT PRIMARY KEY REFERENCES markers(id),
    found_at  REAL NOT NULL,
    how       TEXT NOT NULL         -- 'auto', 'confirmed', 'manual', 'import'
);
"""

OCULUS_KINDS = (
    "anemoculus",
    "geoculus",
    "electroculus",
    "dendroculus",
    "hydroculus",
    "pyroculus",
)
CHEST_KIND = "chest"


@dataclass(frozen=True)
class Marker:
    id: str
    kind: str
    layer: str
    x: float
    y: float
    name: str | None = None
    found: bool = False


class MarkerStore:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._db:
            yield self._db

    # ---------------------------------------------------------- marcadores

    def upsert(self, markers: Iterable[Marker], source: str = "") -> int:
        rows = [(m.id, m.kind, m.layer, m.x, m.y, m.name, source) for m in markers]
        with self._tx() as db:
            db.executemany(
                "INSERT INTO markers(id, kind, layer, x, y, name, source) VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, layer=excluded.layer,"
                " x=excluded.x, y=excluded.y, name=excluded.name, source=excluded.source",
                rows,
            )
        return len(rows)

    def count(self, kind: str | None = None) -> int:
        q = "SELECT COUNT(*) FROM markers"
        args: tuple[str, ...] = ()
        if kind:
            q, args = q + " WHERE kind = ?", (kind,)
        return int(self._db.execute(q, args).fetchone()[0])

    def get(self, marker_id: str) -> Marker | None:
        row = self._db.execute(
            "SELECT m.*, p.marker_id IS NOT NULL AS found FROM markers m"
            " LEFT JOIN progress p ON p.marker_id = m.id WHERE m.id = ?",
            (marker_id,),
        ).fetchone()
        return _row(row) if row else None

    def nearby(
        self,
        layer: str,
        x: float,
        y: float,
        radius: float,
        kinds: Iterable[str] | None = None,
        include_found: bool = False,
    ) -> list[tuple[Marker, float]]:
        """Marcadores dentro do raio, do mais perto para o mais longe, com a distância."""
        q = (
            "SELECT m.*, p.marker_id IS NOT NULL AS found FROM markers m"
            " LEFT JOIN progress p ON p.marker_id = m.id"
            " WHERE m.layer = ? AND m.x BETWEEN ? AND ? AND m.y BETWEEN ? AND ?"
        )
        args: list[Any] = [layer, x - radius, x + radius, y - radius, y + radius]
        kinds = list(kinds or [])
        if kinds:
            q += f" AND m.kind IN ({','.join('?' * len(kinds))})"
            args += kinds
        if not include_found:
            q += " AND p.marker_id IS NULL"
        out = []
        for row in self._db.execute(q, args):
            d = math.hypot(row["x"] - x, row["y"] - y)
            if d <= radius:
                out.append((_row(row), d))
        out.sort(key=lambda t: t[1])
        return out

    # ------------------------------------------------------------ progresso

    def mark_found(self, marker_id: str, how: str = "auto", when: float | None = None) -> None:
        with self._tx() as db:
            db.execute(
                "INSERT OR REPLACE INTO progress(marker_id, found_at, how) VALUES (?,?,?)",
                (marker_id, when or time.time(), how),
            )

    def unmark(self, marker_id: str) -> None:
        with self._tx() as db:
            db.execute("DELETE FROM progress WHERE marker_id = ?", (marker_id,))

    def found_ids(self) -> set[str]:
        return {r[0] for r in self._db.execute("SELECT marker_id FROM progress")}

    def export_progress(self, path: Path) -> int:
        rows = self._db.execute("SELECT marker_id, found_at, how FROM progress ORDER BY found_at")
        data = [{"id": r[0], "found_at": r[1], "how": r[2]} for r in rows]
        path.write_text(json.dumps({"version": 1, "found": data}, indent=2), encoding="utf-8")
        return len(data)

    def import_progress(self, path: Path) -> int:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data["found"] if isinstance(data, dict) else data
        n = 0
        with self._tx() as db:
            for it in items:
                mid = str(it["id"] if isinstance(it, dict) else it)
                when = (
                    float(it.get("found_at", time.time())) if isinstance(it, dict) else time.time()
                )
                db.execute(
                    "INSERT OR IGNORE INTO progress(marker_id, found_at, how) VALUES (?,?,?)",
                    (mid, when, "import"),
                )
                n += 1
        return n


def _row(row: sqlite3.Row) -> Marker:
    return Marker(
        id=row["id"],
        kind=row["kind"],
        layer=row["layer"],
        x=float(row["x"]),
        y=float(row["y"]),
        name=row["name"],
        found=bool(row["found"]),
    )


# ------------------------------------------------------------------ importação


@dataclass(frozen=True)
class ImportMapping:
    """Como ler um JSON de marcadores de qualquer site.

    `items` é o caminho até a lista (ex.: "data.points"); os demais são nomes de
    campos de cada item (aceitam caminho com ponto, ex.: "pos.lat"). `kind_map`
    traduz o tipo do site para o tipo interno (ex.: {"12": "chest"}).
    """

    items: str = ""
    id: str = "id"
    kind: str = "kind"
    x: str = "x"
    y: str = "y"
    layer: str | None = None
    name: str | None = "name"
    default_layer: str = "teyvat"
    kind_map: dict[str, str] | None = None


def _dig(obj: Any, path: str) -> Any:
    for part in [p for p in path.split(".") if p]:
        obj = obj[int(part)] if isinstance(obj, list) else obj[part]
    return obj


def parse_markers(data: Any, mapping: ImportMapping) -> list[Marker]:
    items = _dig(data, mapping.items) if mapping.items else data
    out = []
    for it in items:
        raw_kind = str(_dig(it, mapping.kind))
        kind = (mapping.kind_map or {}).get(raw_kind, raw_kind)
        if mapping.kind_map is not None and raw_kind not in mapping.kind_map:
            continue  # tipo que não interessa (ex.: minérios, NPCs)
        layer = str(_dig(it, mapping.layer)) if mapping.layer else mapping.default_layer
        name = None
        if mapping.name:
            try:
                name = str(_dig(it, mapping.name))
            except (KeyError, IndexError, TypeError):
                name = None
        out.append(
            Marker(
                id=str(_dig(it, mapping.id)),
                kind=kind,
                layer=layer,
                x=float(_dig(it, mapping.x)),
                y=float(_dig(it, mapping.y)),
                name=name,
            )
        )
    return out
