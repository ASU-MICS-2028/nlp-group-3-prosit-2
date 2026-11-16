"""Compare a generated spec with a reference spec (Role 2 evaluation).

    python -m eval.spec_compare GENERATED REFERENCE [--csv results/specs.csv] [--json]

GENERATED and REFERENCE are a spec.json, or a run's state.json (its "spec" is used).

Names alone are a bad measure: the Architect may call it "Booking" where the reference says
"Appointment", and every path then looks wrong. So we compare in layers, matching by meaning:

  1. entities   matched by name, or else by how many similar fields they share
  2. fields     inside matched entities: present, same type, same required/unique flags
  3. endpoints  paths renamed through the entity match (/bookings -> /appointments), parameter names
                ignored, PUT and PATCH both count as "update" (the difference is listed)
  4. access     matched endpoints with the same access level (public / user / admin): the security rules
  5. rules      counted only; whether two sentences state the same rule needs a person or a model

Each layer gets precision (how much of the generated spec is right), recall (how much of the
reference was found) and F1. `score` is the mean of the entity, field and endpoint F1 and the access
agreement. It is a guide for comparing runs, not a grade: read the differences list too.
"""
import argparse
import csv
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

from core.spec import Endpoint, Entity, Field, Spec

ENTITY_MATCH = 0.4    # least similarity for two entities to count as the same thing
FIELD_MATCH = 0.6     # least name similarity for two differently named fields of the same type
UPDATES = {"PUT", "PATCH"}


# ---------- helpers ----------

def prf(matched: int, generated: int, reference: int) -> dict:
    p = matched / generated if generated else 1.0
    r = matched / reference if reference else 1.0
    return {"precision": round(p, 2), "recall": round(r, 2), "f1": round(2 * p * r / (p + r), 2) if p + r else 0.0}


def best_pairs(gen: list, ref: list, score) -> list[tuple]:
    """Greedy one-to-one matching: the most similar pair first. Returns (gen, ref, score) above 0."""
    scored = sorted(((score(g, r), i, j) for i, g in enumerate(gen) for j, r in enumerate(ref)), reverse=True)
    used_g, used_r, pairs = set(), set(), []
    for s, i, j in scored:
        if s > 0 and i not in used_g and j not in used_r:
            used_g.add(i), used_r.add(j)
            pairs.append((gen[i], ref[j], s))
    return pairs


def field_similarity(a: Field, b: Field) -> float:
    """1 for the same name. Otherwise similar names of the same type, e.g. start_time / starts_at."""
    if a.name == b.name:
        return 1.0
    if a.type != b.type:
        return 0.0
    ratio = SequenceMatcher(None, a.name, b.name).ratio()
    shared_word = bool(set(a.name.split("_")) & set(b.name.split("_")) - {"id"})
    return ratio if ratio >= FIELD_MATCH or shared_word else 0.0


def field_pairs(a: Entity, b: Entity) -> list[tuple[Field, Field, float]]:
    return best_pairs(a.fields, b.fields, field_similarity)


def entity_similarity(a: Entity, b: Entity) -> float:
    """Same name counts fully; otherwise the share of fields that match (out of the larger entity)."""
    if a.name.lower() == b.name.lower():
        return 1.0
    pairs = field_pairs(a, b)
    return sum(s for *_, s in pairs) / max(len(a.fields), len(b.fields), 1)


def resource(path: str) -> str:
    return path.strip("/").split("/")[0]


def normalise(path: str, renames: dict[str, str]) -> str:
    """/bookings/{booking_id}/cancel -> /appointments/{}/cancel, when Booking matched Appointment."""
    parts = path.strip("/").split("/")
    if parts and parts[0] in renames:
        parts[0] = renames[parts[0]]
    return "/" + "/".join(re.sub(r"\{[^}]*\}", "{}", p) for p in parts)


def collection(spec: Spec, entity: str) -> str | None:
    """The first path segment the spec uses for an entity, e.g. "bookings" for Booking."""
    return next((resource(e.path) for e in spec.endpoints if e.entity == entity), None)


def label(e: Endpoint) -> str:
    return f"{e.method} {e.path}"


# ---------- the comparison ----------

def compare(gen: Spec, ref: Spec) -> dict:
    notes = []

    # 1. entities
    ent_pairs = [(g, r) for g, r, s in best_pairs(gen.entities, ref.entities, entity_similarity) if s >= ENTITY_MATCH]
    entity_map = {g.name: r.name for g, r in ent_pairs}
    for g, r in ent_pairs:
        if g.name != r.name:
            notes.append(f"entity {g.name} = reference {r.name}")
    matched_ref = set(entity_map.values())
    notes += [f"missing entity {r.name}" for r in ref.entities if r.name not in matched_ref]
    notes += [f"extra entity {g.name}" for g in gen.entities if g.name not in entity_map]

    # 2. fields, inside matched entities (fields of unmatched entities count as missing / extra)
    f_matched = f_type = f_flags = 0
    field_maps = {}   # generated entity -> {generated field: reference field}
    for g, r in ent_pairs:
        pairs = [(a, b) for a, b, s in field_pairs(g, r)]
        field_maps[g.name] = {a.name: b.name for a, b in pairs}
        f_matched += len(pairs)
        for a, b in pairs:
            if a.name != b.name:
                notes.append(f"field {g.name}.{a.name} = reference {r.name}.{b.name}")
            if a.type == b.type:
                f_type += 1
            else:
                notes.append(f"field {r.name}.{b.name}: type {a.type}, reference {b.type}")
            flags = [k for k in ("required", "unique") if getattr(a, k) != getattr(b, k)]
            if flags:
                notes.append(f"field {r.name}.{b.name}: {', '.join(flags)} differs from the reference")
            else:
                f_flags += 1
        got = {b.name for _, b in pairs}
        notes += [f"missing field {r.name}.{f.name}" for f in r.fields if f.name not in got]
    gen_fields = sum(len(e.fields) for e in gen.entities)
    ref_fields = sum(len(e.fields) for e in ref.entities)

    # 3. endpoints, with paths renamed through the entity match
    renames = {}
    for g, r in ent_pairs:
        a, b = collection(gen, g.name), collection(ref, r.name)
        if a and b and a != b:
            renames[a] = b
    gen_by_key = {}
    for e in gen.endpoints:
        gen_by_key.setdefault((e.method, normalise(e.path, renames)), e)
    ep_pairs, unmatched_ref = [], []
    for r in ref.endpoints:
        key = (r.method, normalise(r.path, {}))
        g = gen_by_key.pop(key, None)
        if g is None and r.method in UPDATES:   # PUT where the reference has PATCH, or the other way
            other = (({"PUT", "PATCH"} - {r.method}).pop(), key[1])
            g = gen_by_key.pop(other, None)
            if g is not None:
                notes.append(f"{label(g)} = reference {label(r)} (different update method)")
        if g is None:
            unmatched_ref.append(r)
        else:
            ep_pairs.append((g, r))
    notes += [f"missing endpoint {label(r)} ({r.access})" for r in unmatched_ref]
    notes += [f"extra endpoint {label(g)} ({g.access})" for g in gen_by_key.values()]

    # 4. access level and request fields of matched endpoints
    same_access, body_scores = 0, []
    for g, r in ep_pairs:
        if g.access == r.access:
            same_access += 1
        else:
            notes.append(f"{label(r)}: access {g.access}, reference {r.access}")
        mapping = field_maps.get(g.entity or "", {})
        got, want = {mapping.get(f, f) for f in g.request_fields}, set(r.request_fields)
        if got or want:
            body_scores.append(len(got & want) / len(got | want))
            if got != want:
                notes.append(f"{label(r)}: body {sorted(got)}, reference {sorted(want)}")

    entities = prf(len(ent_pairs), len(gen.entities), len(ref.entities))
    fields = prf(f_matched, gen_fields, ref_fields)
    endpoints = prf(len(ep_pairs), len(gen.endpoints), len(ref.endpoints))
    access = round(same_access / len(ep_pairs), 2) if ep_pairs else 0.0
    return {
        "score": round((entities["f1"] + fields["f1"] + endpoints["f1"] + access) / 4, 2),
        "entities": entities,
        "fields": {**fields, "same_type": round(f_type / f_matched, 2) if f_matched else 0.0,
                   "same_flags": round(f_flags / f_matched, 2) if f_matched else 0.0},
        "endpoints": endpoints,
        "access_agreement": access,
        "request_fields": round(sum(body_scores) / len(body_scores), 2) if body_scores else 1.0,
        "rules": {"generated": len(gen.rules), "reference": len(ref.rules)},
        "notes": notes,
    }


def flat(result: dict) -> dict:
    """One CSV row: every number, no notes."""
    row = {"score": result["score"]}
    for layer in ("entities", "fields", "endpoints"):
        row.update({f"{layer}_{k}": v for k, v in result[layer].items()})
    row.update(access_agreement=result["access_agreement"], request_fields=result["request_fields"],
               rules_generated=result["rules"]["generated"], rules_reference=result["rules"]["reference"])
    return row


def show(result: dict) -> str:
    out = [f"Spec score {result['score']}  (mean of entity, field and endpoint F1 and access agreement)",
           f"{'':12}{'precision':>10}{'recall':>8}{'F1':>6}"]
    for layer in ("entities", "fields", "endpoints"):
        m = result[layer]
        out.append(f"{layer:12}{m['precision']:>10}{m['recall']:>8}{m['f1']:>6}")
    f = result["fields"]
    out.append(f"fields: same type {f['same_type']}, same required/unique {f['same_flags']}")
    out.append(f"endpoints: same access level {result['access_agreement']}, "
               f"same request fields {result['request_fields']}")
    out.append(f"rules: {result['rules']['generated']} generated, {result['rules']['reference']} in the reference")
    out += ["Differences:"] + [f"  - {n}" for n in result["notes"]] if result["notes"] else ["No differences."]
    return "\n".join(out)


def load(path: str) -> Spec:
    data = json.loads(Path(path).read_text())
    if "spec" in data and "entities" not in data:   # a run's state.json
        data = data["spec"]
    return Spec.model_validate(data)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Compare a generated spec with a reference spec.")
    p.add_argument("generated", help="spec.json or a run's state.json")
    p.add_argument("reference", help="the reference spec.json, e.g. golden/clinic/spec.json")
    p.add_argument("--csv", help="append one row of numbers to this CSV file")
    p.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = p.parse_args(argv)
    result = compare(load(args.generated), load(args.reference))
    print(json.dumps(result, indent=1) if args.json else show(result))
    if args.csv:
        path = Path(args.csv)
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {"generated": args.generated, "reference": args.reference, **flat(result)}
        new = not path.exists()
        with path.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(row))
            if new:
                w.writeheader()
            w.writerow(row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
