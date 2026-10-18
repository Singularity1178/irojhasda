"""2D geometry for the arena floor (screen px, y down): boxes, rays, the nav grid and A*.

Box          one axis-aligned obstacle on the floor: a spawned prop or a real desktop window.
seg_box      where a segment first enters a box (slab test), or None.
seg_circle   where a segment first enters a circle, or None.
NavGrid      occupancy grid inflated by the student radius, A* with octile moves and
             string-pulling, nearest free cell. Rebuilt whenever the boxes change.
"""
from __future__ import annotations

import heapq
import math

SQ2 = math.sqrt(2.0)


class Box:
    """kind: crate / sandbags / barrier / barrel / vending / container / window.
    cover: 'full' blocks bullets, 'half' blocks some (shooting over sandbags)."""
    __slots__ = ("l", "t", "r", "b", "kind", "height", "cover", "hp", "hp_max", "owner", "alive", "vx", "vy",
                 "hwnd", "seed")

    def __init__(self, l, t, r, b, kind, height, cover="full", hp=None, owner=None, hwnd=None, seed=0):
        self.l, self.t, self.r, self.b = float(l), float(t), float(r), float(b)
        self.kind, self.height, self.cover = kind, float(height), cover
        self.hp = self.hp_max = hp
        self.owner = owner
        self.alive = True
        self.vx = self.vy = 0.0
        self.hwnd = hwnd
        self.seed = seed

    @property
    def rect(self):
        return (self.l, self.t, self.r, self.b)

    def cx(self): return (self.l + self.r) * 0.5

    def cy(self): return (self.t + self.b) * 0.5

    def contains(self, x, y, pad=0.0):
        return self.l - pad <= x <= self.r + pad and self.t - pad <= y <= self.b + pad

    def push_circle(self, x, y, rad):
        """(nx, ny, pen) to push a circle out of this box, or None."""
        cx = min(max(x, self.l), self.r); cy = min(max(y, self.t), self.b)
        dx, dy = x - cx, y - cy
        d2 = dx * dx + dy * dy
        if d2 > 1e-9:
            if d2 >= rad * rad: return None
            d = math.sqrt(d2)
            return dx / d, dy / d, rad - d
        el, er, et, eb = x - self.l, self.r - x, y - self.t, self.b - y
        m = min(el, er, et, eb)
        if m == el: return -1.0, 0.0, el + rad
        if m == er: return 1.0, 0.0, er + rad
        if m == et: return 0.0, -1.0, et + rad
        return 0.0, 1.0, eb + rad

    def dist(self, x, y):
        cx = min(max(x, self.l), self.r); cy = min(max(y, self.t), self.b)
        return math.hypot(x - cx, y - cy)


def seg_box(x0, y0, x1, y1, bx):
    """Entry parameter t in [0, 1] of segment (x0,y0)-(x1,y1) into box bx, or None."""
    l, t, r, b = bx.l, bx.t, bx.r, bx.b
    if (x0 < l and x1 < l) or (x0 > r and x1 > r) or (y0 < t and y1 < t) or (y0 > b and y1 > b):
        return None
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - l), (dx, r - x0), (-dy, y0 - t), (dy, b - y0)):
        if abs(p) < 1e-12:
            if q < 0: return None
        else:
            u = q / p
            if p < 0:
                if u > t1: return None
                if u > t0: t0 = u
            else:
                if u < t0: return None
                if u < t1: t1 = u
    return t0


def seg_circle(x0, y0, x1, y1, cx, cy, r):
    dx, dy = x1 - x0, y1 - y0
    fx, fy = x0 - cx, y0 - cy
    a = dx * dx + dy * dy
    if a < 1e-12: return None
    b = 2 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - r * r
    if c <= 0: return 0.0
    disc = b * b - 4 * a * c
    if disc < 0: return None
    s = math.sqrt(disc)
    t = (-b - s) / (2 * a)
    if 0.0 <= t <= 1.0: return t
    return None


def point_seg_dist(px, py, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    a = dx * dx + dy * dy
    if a < 1e-12: return math.hypot(px - x0, py - y0), 0.0
    u = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / a))
    return math.hypot(px - (x0 + dx * u), py - (y0 + dy * u)), u


class NavGrid:
    def __init__(self, rect, cell):
        self.l, self.t, self.r, self.b = rect
        self.cs = max(8.0, float(cell))
        self.w = max(2, int(math.ceil((self.r - self.l) / self.cs)))
        self.h = max(2, int(math.ceil((self.b - self.t) / self.cs)))
        self.block = bytearray(self.w * self.h)
        self.version = 0

    def rebuild(self, boxes, inflate):
        blk = bytearray(self.w * self.h)
        cs, w, h = self.cs, self.w, self.h
        edge = int(math.ceil(inflate / cs))
        for i in range(w):                      # the screen edges are walls too
            for j in range(edge):
                blk[j * w + i] = 1; blk[(h - 1 - j) * w + i] = 1
        for j in range(h):
            for i in range(edge):
                blk[j * w + i] = 1; blk[j * w + (w - 1 - i)] = 1
        for bx in boxes:
            if not bx.alive: continue
            i0 = max(0, int((bx.l - inflate - self.l) / cs)); i1 = min(w - 1, int((bx.r + inflate - self.l) / cs))
            j0 = max(0, int((bx.t - inflate - self.t) / cs)); j1 = min(h - 1, int((bx.b + inflate - self.t) / cs))
            for j in range(j0, j1 + 1):
                cyc = self.t + (j + 0.5) * cs
                row = j * w
                for i in range(i0, i1 + 1):
                    cxc = self.l + (i + 0.5) * cs
                    if bx.dist(cxc, cyc) < inflate:
                        blk[row + i] = 1
        self.block = blk
        self.version += 1

    def cell(self, x, y):
        i = int((x - self.l) / self.cs); j = int((y - self.t) / self.cs)
        return min(self.w - 1, max(0, i)), min(self.h - 1, max(0, j))

    def center(self, i, j):
        return self.l + (i + 0.5) * self.cs, self.t + (j + 0.5) * self.cs

    def free(self, x, y):
        i, j = self.cell(x, y)
        return not self.block[j * self.w + i]

    def free_ij(self, i, j):
        return 0 <= i < self.w and 0 <= j < self.h and not self.block[j * self.w + i]

    def nearest_free(self, x, y, max_r=60):
        i0, j0 = self.cell(x, y)
        if self.free_ij(i0, j0): return x, y
        for rad in range(1, max_r):
            best = None
            for di in range(-rad, rad + 1):
                for dj in (-rad, rad) if abs(di) != rad else range(-rad, rad + 1):
                    i, j = i0 + di, j0 + dj
                    if self.free_ij(i, j):
                        cx, cy = self.center(i, j)
                        d = (cx - x) ** 2 + (cy - y) ** 2
                        if best is None or d < best[0]: best = (d, cx, cy)
            if best: return best[1], best[2]
        return x, y

    def line_free(self, x0, y0, x1, y1):
        """Grid walk: is the straight line between two points walkable?"""
        d = math.hypot(x1 - x0, y1 - y0)
        n = max(1, int(d / (self.cs * 0.5)))
        for k in range(n + 1):
            u = k / n
            if not self.free(x0 + (x1 - x0) * u, y0 + (y1 - y0) * u): return False
        return True

    def path(self, x0, y0, x1, y1, max_nodes=6000):
        """List of waypoints from start to goal (start excluded), or [] if unreachable."""
        if self.line_free(x0, y0, x1, y1): return [(x1, y1)]
        sx, sy = self.nearest_free(x0, y0, 6)
        gx, gy = self.nearest_free(x1, y1, 12)
        si, sj = self.cell(sx, sy); gi, gj = self.cell(gx, gy)
        w, blk = self.w, self.block
        start, goal = sj * w + si, gj * w + gi
        if start == goal: return [(gx, gy)]
        openh = [(0.0, start)]
        g = {start: 0.0}
        came = {}
        n = 0
        nbrs = ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, SQ2), (1, -1, SQ2), (-1, 1, SQ2),
                (-1, -1, SQ2))
        found = False
        while openh and n < max_nodes:
            _f, cur = heapq.heappop(openh)
            if cur == goal: found = True; break
            n += 1
            ci, cj = cur % w, cur // w
            gc = g[cur]
            for di, dj, c in nbrs:
                ni, nj = ci + di, cj + dj
                if not (0 <= ni < w and 0 <= nj < self.h): continue
                k = nj * w + ni
                if blk[k]: continue
                if di and dj and (blk[cj * w + ni] or blk[nj * w + ci]): continue   # no corner cutting
                ng = gc + c
                if ng < g.get(k, 1e18):
                    g[k] = ng; came[k] = cur
                    dx, dy = abs(ni - gi), abs(nj - gj)
                    heapq.heappush(openh, (ng + (dx + dy) + (SQ2 - 2) * min(dx, dy), k))
        if not found: return []
        cells = [goal]
        while cells[-1] != start:
            cells.append(came[cells[-1]])
        cells.reverse()
        pts = [self.center(c % w, c // w) for c in cells[1:]]
        pts[-1] = (gx, gy)
        # string pulling: skip waypoints that have a free straight line past them
        out = []
        cx, cy = x0, y0
        i = 0
        while i < len(pts):
            j = len(pts) - 1
            while j > i and not self.line_free(cx, cy, pts[j][0], pts[j][1]):
                j -= 1
            out.append(pts[j]); cx, cy = pts[j]; i = j + 1
        return out
