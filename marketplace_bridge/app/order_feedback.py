import math


def next_scan_seconds(enabled,running,completed,now):
    if not enabled or running: return None
    return max(0,math.ceil(300-(now-completed))) if completed is not None else 0


def summarize_run(states,writes,new_imports):
    linked=states.count('linked')
    imported=min(linked,new_imports) if writes else 0
    return dict(checked=len(states),imported=imported,existing=linked-imported,
                ready=states.count('preview'),
                review=sum(s in {'review','validation_review','tracking_uncertain'} for s in states),
                failed=sum(s in {'uncertain','claimed','source_failed'} for s in states))
