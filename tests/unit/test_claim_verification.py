from rag.verify import check_claim, remove_unsupported


def test_typographic_spaces_and_hyphens_in_reported_outcomes():
    claim = "I created a revenue dashboard in Power\u202fBI and replaced a 6‑hour manual report for 40 managers."
    evidence = [{"id": "dashboard", "skills": ["Power BI"],
                 "text": "Power BI dashboard replaced a 6-hour manual report for 40 managers."}]
    assert check_claim(claim, evidence)["label"] == "supported"


def test_invented_numeric_result_cannot_be_partly_supported():
    claim = "I built a PyTorch and Docker inspection service that caught 90% of defects."
    evidence = [{"id": "inspection", "skills": ["PyTorch", "Docker"],
                 "text": "Built a PyTorch and Docker inspection service that caught 190% of the baseline count."}]
    check = check_claim(claim, evidence)
    assert check["label"] == "unsupported"
    assert remove_unsupported(claim, [check]) == ("", [claim])


def test_live_reporting_does_not_prove_real_time_operation():
    claim = "I delivered a people-analytics dashboard so executives could track attrition in real time."
    evidence = [{"id": "hr-dashboard", "skills": [],
                 "text": "Built attrition and hiring dashboards for HR. Time-to-hire reporting went from quarterly to live."}]
    check = check_claim(claim, evidence)
    assert check["label"] == "unsupported"
    assert "real-time operation" in check["reason"]
