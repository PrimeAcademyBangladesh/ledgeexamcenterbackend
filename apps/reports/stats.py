# reports/stats.py
from django.db.models import Count, Avg, Q

GRADES = ("distinction", "merit", "pass", "did_not_pass")
SCORE_BUCKETS = [
    ("0-19%",   0, 19), ("20-39%", 20, 39), ("40-59%", 40, 59),
    ("60-69%", 60, 69), ("70-84%", 70, 84), ("85-100%", 85, 100),
]

def compute_stats(qs):
    total = qs.count()
    pass_ct = qs.filter(passed=True).count()
    avg = qs.aggregate(a=Avg("score_percent"))["a"] or 0

    grade_dist = {g: qs.filter(grade=g).count() for g in GRADES}

    score_dist = [
        {"range": label, "count": qs.filter(score_percent__gte=lo,
                                            score_percent__lte=hi).count()}
        for label, lo, hi in SCORE_BUCKETS
    ]

    return {
        "totalAttempts":     total,
        "passRate":          round((pass_ct / total) * 100, 1) if total else 0,
        "averageScore":      round(avg, 1),
        "distinctionCount":  grade_dist["distinction"],
        "gradeDistribution": grade_dist,
        "scoreDistribution": score_dist,
    }
