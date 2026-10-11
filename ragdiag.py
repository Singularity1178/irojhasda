#!/usr/bin/env python3
"""
ragdiag.py - what actually happens to a character the moment she goes limp.

--rag-trace already prints the pelvis and two joint errors. That is enough to
see that something is wrong and not enough to say what: it cannot tell a
self-collision shove from a window shove from a bad joint, and it stops at the
frame where the pop is largest, which is exactly the frame you want to keep
looking at.

This prints, per character, per ragdoll:
  * the entry state - which entry point was taken, with which kick, why
  * every spawn overlap that got muted, by body name, with the depth
  * every arbiter that is muted or live, per frame
  * every contact that starts, with the impulse that came with it
  * per-body speed and depth into the floor, so a limb that is jittering is
    named instead of being hidden inside one aggregate speed number
  * a one-line verdict, so a run that looks fine can be skipped

Every probe is wrapped so a missing attribute costs one line, never a crash.
This code runs while she is mid-ragdoll; a traceback here would be a worse bug
than the one being diagnosed.

    from ragdiag import ragdiag_on, diag_start, diag_frame, diag_contact
    if ragdiag_on(app): diag_start(pet, "ctrl+1")
"""
from __future__ import annotations

import time

_ON = False                 # set once at startup
_OWNERS = {}                # owner id -> the Pet
_LABEL = {}                 # owner id -> what started this ragdoll
_SEEN = {}                  # owner id -> spawn frame, to avoid double counting
_PENDING = 0                # contacts that arrived before we knew the owner
_LAST_MOVERS = {}           # owner -> last set of limbs over 40 px/s
_LAST_STATE = {}            # owner -> last rest-tick state, to skip repeats
_stamp = time.strftime("%H:%M:%S")


def enable(app):
    """Turn diagnostics on for this run and print the header. Call once."""
    global _ON, _stamp
    n = int(getattr(app, "rag_diag", 0) or 0)
    if not n:
        return 0
    _ON = True
    _stamp = time.strftime("%H:%M:%S")
    import ragphys
    print(f"\n{'=' * 78}\n[ragdiag] ON  frames={n}  "
          f"self_collide={ragphys.RAGP_SELF_COLLIDE}  "
          f"rest_speed={ragphys.RAGP_REST_SPEED:g}  "
          f"rest_time={ragphys.RAGP_REST_TIME:g}s  "
          f"max_lin_v={ragphys.RAGP_MAX_LIN_V:g}\n{'=' * 78}", flush=True)
    print("[ragdiag] engine knobs that decide how she goes down:", flush=True)
    for k in ("RAGP_SELF_COLLIDE", "RAGP_START_TILT", "RAGP_START_SPIN",
              "RAGP_KICK_VX", "RAGP_KICK_VY", "RAGP_KICK_W",
              "RAGP_REST_SPEED", "RAGP_REST_TIME", "RAGP_LIMP_K",
              "RAGP_BODY_FRICTION", "RAGP_BODY_ELASTICITY", "RAGP_SUBSTEP",
              "RAGP_ITERATIONS", "RAGP_MAX_LIN_V"):
        print(f"[ragdiag]   {k} = {getattr(ragphys, k, '<missing>')}", flush=True)
    return n


def on():
    return _ON


def _p(tag, msg):
    print(f"[ragdiag {time.strftime('%H:%M:%S', time.localtime())}] {tag}: {msg}",
          flush=True)


def _g(obj, attr, dflt=None):
    """getattr that never raises - a probe must not become the bug."""
    try:
        v = getattr(obj, attr, dflt)
        return dflt if v is None else v
    except Exception:
        return dflt


def _label(owner):
    pet = _OWNERS.get(owner)
    n = _g(pet, "name", None)
    return f"{n or 'owner%d' % owner}"


# ------------------------------------------------------------------ entry
def diag_start(pet, why, **kw):
    """A character is about to go limp. Records who, why, and the intent."""
    if not _ON:
        return
    # The physics owner id, which is what the world and every callback use.
    # NOT `id(pet)`: that changes every run and would not match the ids in the
    # per-frame lines, which come from skel.owner.
    owner = _g(pet, "rag_owner", None)
    if owner is None:
        owner = _g(pet, "owner", None)
    if owner is None:
        owner = id(pet) % 100000
    _OWNERS[owner] = pet
    _LABEL[owner] = why
    _SEEN[owner] = True
    eng = _g(pet, "cfg", {}).get("ragdoll_engine", "pymunk")
    vis = "?"
    f = _g(pet, "isVisible", None)
    if callable(f):
        try:
            vis = f()
        except Exception:
            vis = "?"
    _p(_label(owner),
       f"GOING LIMP via {why}  engine={eng}  "
       f"window=({_g(pet, 'px', 0):.1f},{_g(pet, 'py', 0):.1f})  "
       f"scale={_g(_g(pet, 'cfg', {}), 'scale', 1.0):g}  "
       f"grounded={_g(pet, 'grounded', None)}  visible={vis}  "
       f"dragging={_g(pet, 'dragging', None)}")


def diag_pm_ready(skel, pet=None):
    """Skeleton is in the world. Dump spawn geometry and what was muted."""
    if not _ON:
        return
    owner = _g(skel, "owner", 0)
    if pet is not None:
        _OWNERS[owner] = pet
        _SEEN.setdefault(owner, True)
    try:
        names = skel_shape_names(skel)
        ign = getattr(skel.world, "_ignore", ())
        mine = {id(s) for s in _g(skel, "shapes", ())}
        mut = []
        for k in ign:
            if k[0] in mine and k[1] in mine:
                mut.append((_shape_name(skel, k[0], names), _shape_name(skel, k[1], names)))
        anch, rel = skel.joint_error()
        _p(_label(owner),
           f"PM SKELETON IN  bodies={len(_g(skel, 'bodies', ()))}  "
           f"joints={len(_g(skel, 'joints', ()))}  "
           f"spawn_anchor_err={anch:.3f}px  spawn_rel_err={rel:.4f}rad  "
           f"anc_pairs={len(_g(skel, 'anc', ()))}  self_mute_pairs={len(mut)}  "
           f"start_tilt={_g(skel, 'tilt', 0.0):+.4f}rad  "
           f"drop={_g(skel, 'drop', 0.0):.2f}px")
        for i, b in enumerate(_g(skel, "bodies", ())):
            _p(_label(owner),
               f"  spawn body {_body_name(skel, i):<12} "
               f"pos=({b.position[0]:8.2f},{b.position[1]:8.2f}) "
               f"v=({b.velocity[0]:7.1f},{b.velocity[1]:7.1f}) "
               f"w={b.angular_velocity:+6.2f} mass={b.mass:.4g}")
        for a, b in sorted(mut):
            _p(_label(owner), f"  muted at spawn (overlapping): {a} <-> {b}")
        if not mut:
            _p(_label(owner), "  no spawn overlaps needed muting")
    except Exception as e:
        _p(_label(owner), f"  (spawn probe failed: {type(e).__name__}: {e})")


def diag_pm_failed(pet, reason):
    if not _ON:
        return
    owner = _g(pet, "rag_owner", _g(pet, "owner", 0))
    _OWNERS[owner] = pet
    _p(_label(owner), f"PM FAILED -> falling back to rod ragdoll: {reason}")


# ------------------------------------------------------------------ contact
def diag_getup(owner, why, rest):
    if not _ON:
        return
    _p(_label(owner), f"GET UP via {why} after {rest:.2f}s at rest")


def diag_end(owner, skel, reason):
    """The ragdoll is over, for a reason other than a get-up."""
    if not _ON:
        return
    _p(_label(owner), f"END: {reason}  final_speed={_g(skel, 'speed', lambda: 0.0)():.1f}")


def diag_tick(owner, frame, speed, rest_speed, contact, rest, rest_time,
              want_up, auto):
    """The auto-get-up decision, once every half second.

    This is the line that says WHY a character is still lying there. The usual
    cause is not the physics: `contact` is False while she is visibly on the
    floor, or she is a hair over RAGP_REST_SPEED and rest keeps resetting.
    """
    if not _ON:
        return
    if contact and speed >= rest_speed:
        why = "MOVING"
    elif not contact:
        why = "NOT TOUCHING (contacts lost, so rest can never accumulate)"
    elif rest <= 0.0:
        why = "rest keeps resetting"
    else:
        why = "waiting on rest timer"
    line = (f"f{frame:4d} speed={speed:7.1f} (rest needs <{rest_speed:6.1f})  "
            f"contact={contact!s:5}  rest={rest:5.2f}/{rest_time:g}s  "
            f"auto={auto!s:5} want_up={want_up!s:5}  -> {why}")
    # While she is unsettled this line is noise repeated every frame: the verdict
    # at the end says the same thing. Bucketing the speed coarsely (not
    # per-frame) is what makes it settle down - and once she IS settled, the
    # rest timer is the thing worth watching, so it always prints.
    st = (int(speed // 50.0), bool(contact), rest > 0.0)
    if st != _LAST_STATE.get(owner) or rest > 0.0:
        _LAST_STATE[owner] = st
        _p(_label(owner), line)


def diag_contact(owner, a_name, b_name, impulse, kind):
    if not _ON:
        return
    big = abs(impulse) > 0.0
    _p(_label(owner), f"CONTACT {a_name} <-> {b_name}  kind={kind}  "
                      f"impulse={impulse:.1f}{'   <-- SHOVE' if big and abs(impulse) > 400 else ''}")


def diag_mute(owner, a_name, b_name, why):
    if not _ON:
        return
    _p(_label(owner), f"MUTE {a_name} <-> {b_name}  reason={why}")


# ------------------------------------------------------------------ per frame
def diag_frame(owner, skel, frame, fps):
    """One line per frame, plus a per-body breakdown only when something moves."""
    if not _ON:
        return
    try:
        p = skel.pose()
        anch, rel = skel.joint_error()
        sp = skel.speed()
        ign = getattr(skel.world, "_ignore", ())
        mine = {id(s) for s in _g(skel, "shapes", ())}
        nmut = sum(1 for k in ign if k[0] in mine and k[1] in mine)
        _p(_label(owner),
           f"f{frame:4d} t={frame / float(fps or 60):5.2f}s "
           f"pelvis=({p['x']:8.2f},{p['y']:8.2f}) "
           f"v=({p['vx']:8.1f},{p['vy']:8.1f}) w={p['w']:6.2f} "
           f"speed={sp:7.1f} anchor={anch:6.3f}px rel={rel:6.4f}rad "
           f"contacts={len(_g(skel, 'contacts', ()))} self_mutes={nmut}")

        # The aggregate speed hides WHICH limb is unhappy. Name it.
        moving = []
        for i, b in enumerate(_g(skel, "bodies", ())):
            v = b.velocity.length
            if v > 40.0:
                moving.append((v, _body_name(skel, i)))
        if moving:
            moving.sort(reverse=True)
            # Every frame for the first second, then only when the set of limbs
            # over the threshold changes. Printed flat out it is 15 lines a
            # frame and the line you need is 300 lines into it.
            key = tuple(nm for _, nm in moving)
            if frame <= 45 or key != _LAST_MOVERS.get(owner):
                _LAST_MOVERS[owner] = key
                top = ", ".join(f"{nm}={v:.1f}" for v, nm in moving[:6])
                _p(_label(owner), f"        limbs over 40 px/s: {top}")
    except Exception as e:
        _p(_label(owner), f"        (frame probe failed: {type(e).__name__}: {e})")


def diag_verdict(owner, skel, got_up_at, rest_at, peak_speed, frames):
    """The end of one ragdoll, in one block, so runs can be compared."""
    if not _ON:
        return
    try:
        sp = skel.speed()
        anch, rel = skel.joint_error()
        resting = sp < float(_rest_speed())
        _p(_label(owner),
           f"VERDICT after {frames / 60.0:5.2f}s  final_speed={sp:7.1f}  "
           f"peak_speed={peak_speed:7.1f}  "
           f"resting_now={resting}  rest_at={rest_at if rest_at else '-'}  "
           f"got_up_at={got_up_at if got_up_at else 'NEVER'}")
        _p(_label(owner),
           f"        final anchor={anch:.3f}px rel={rel:.4f}rad  "
           f"judgement={'SETTLED' if resting else 'STILL MOVING'}")
        if not resting:
            moving = sorted(((b.velocity.length, _body_name(skel, i))
                             for i, b in enumerate(_g(skel, "bodies", ()))),
                            reverse=True)[:4]
            _p(_label(owner), "        worst movers: " +
               ", ".join(f"{n}={v:.1f}" for v, n in moving))
    except Exception as e:
        _p(_label(owner), f"        (verdict probe failed: {type(e).__name__}: {e})")


# ------------------------------------------------------------------ helpers
def skel_shape_names(skel):
    """Map id(shape) -> readable limb name. Cached on the skeleton, because the
    contact callback needs it and rebuilding it per contact is the one thing
    that could make diagnostics slow enough to distort what is being measured."""
    c = getattr(skel, "_diag_names", None)
    if c is not None:
        return c
    out = {}
    for i, shapes in enumerate(_g(skel, "_shapes_of", ()) or ()):
        nm = _body_name(skel, i)
        for s in shapes:
            out[id(s)] = nm
    try:
        skel._diag_names = out
    except Exception:
        pass
    return out


def _body_name(skel, i):
    spec = _g(skel, "spec", {}) or {}
    bodies = spec.get("bodies", ())
    try:
        return str(bodies[i].get("name") or bodies[i].get("bone") or "body%d" % i)
    except Exception:
        return "body%d" % i


def _shape_name(skel, sid, names):
    return names.get(sid, "shape@%x" % sid)


def _rest_speed():
    try:
        import ragphys
        return ragphys.RAGP_REST_SPEED
    except Exception:
        return 40.0
