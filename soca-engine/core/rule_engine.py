from functools import reduce
from models.schemas import Detection, Rule, RuleResult


def _resolve(ctx: dict, path: str):
    try:
        return reduce(lambda d, k: d[k] if isinstance(d, dict) else d[int(k)], path.split("."), ctx)
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _evaluate(ctx: dict, condition) -> bool:
    val = _resolve(ctx, condition.path)
    target = condition.value
    op = condition.op

    if op == "eq":           return val == target
    if op == "neq":          return val != target
    if op == "gte":          return val is not None and val >= target
    if op == "lte":          return val is not None and val <= target
    if op == "gt":           return val is not None and val > target
    if op == "lt":           return val is not None and val < target
    if op == "contains":     return isinstance(val, (list, str)) and target in val
    if op == "not_contains": return isinstance(val, (list, str)) and target not in val
    if op == "exists":       return val is not None
    return False


def _build_context(detections: list[Detection], aging: dict, frame_meta: dict) -> dict:
    in_roi = [d for d in detections if d.in_roi]
    cls_counts = {}
    for d in in_roi:
        cls_counts[str(d.cls_id)] = cls_counts.get(str(d.cls_id), 0) + 1

    return {
        "detections": {
            "count":        len(detections),
            "in_roi_count": len(in_roi),
            "cls_ids":      [d.cls_id for d in detections],
            "cls_counts":   cls_counts,
        },
        "aging": aging,
        "frame": frame_meta,
    }


def evaluate(rules: list[Rule], detections: list[Detection], aging: dict, frame_meta: dict) -> list[RuleResult]:
    ctx = _build_context(detections, aging, frame_meta)
    results = []

    for rule in sorted(rules, key=lambda r: r.priority):
        all_pass = all(_evaluate(ctx, c) for c in rule.when_all) if rule.when_all else True
        any_pass = any(_evaluate(ctx, c) for c in rule.when_any) if rule.when_any else True
        triggered = all_pass and any_pass

        results.append(RuleResult(
            rule_name=rule.name,
            triggered=triggered,
            actions_fired=[a.type for a in rule.actions] if triggered else [],
        ))

    return results
